"""P1-2: a job consuming another job's product as an intermediate part must
wait until the producing job has delivered all its units, and the store's
count for that part must be finite (unlike external parts).
"""
import os

from simulation_v2.csv_parser import ParseError, parse_csv
from simulation_v2.engine import run_simulation

CONFIG = """[SIMULATION]
name,Intermediate Parts Test
description,test
max_ticks,5000
scheduling_policy,FIFO
replenishment_policy,UnitsLeft,2

[AMR_TYPES]
type_name,units_carried,speed_m_per_s,cost_dollars
Cart,10,5.0,3000

[AMRS]
type_name,count
Cart,2

[CELLS]
cell_name,distance_meters,speed_factor,num_stations,lineside_buffer_size,output_buffer_size
CellA,10,1.0,1,10,10
CellB,10,1.0,1,10,10

[PARTS]
part_name
RawMaterial

[JOBS]
job_name,product_name,units,arrival_tick,deadline_tick,capable_cells
JobA,SubAssembly,5,0,3000,CellA
JobB,FinalProduct,5,0,3000,CellB

[JOB_STEPS]
job_name,station_number,part_name,parts_per_unit,ticks
JobA,1,RawMaterial,1,10
JobB,1,SubAssembly,1,10
"""


def test_dependent_job_waits_for_producer_and_gets_finite_supply(tmp_path):
    config = parse_csv(CONFIG)
    log_path = str(tmp_path / "run.jsonl")
    sim_result = run_simulation(config, log_path, run_id="test")

    jobs_by_name = {j["name"]: j for j in sim_result["jobs"]}
    job_a, job_b = jobs_by_name["JobA"], jobs_by_name["JobB"]

    assert job_a["completion_tick"] is not None
    assert job_b["completion_tick"] is not None
    # JobB can't be assigned to a cell before JobA has delivered every unit.
    assert job_b["assigned_tick"] >= job_a["complete_at_cell_tick"]
    assert sim_result["store"].get("FinalProduct") == 5


def test_job_cannot_consume_its_own_product():
    bad_config = CONFIG.replace("JobA,1,RawMaterial,1,10", "JobA,1,SubAssembly,1,10")
    try:
        parse_csv(bad_config)
        assert False, "expected ParseError"
    except ParseError as e:
        assert "own product" in str(e)


def test_unknown_intermediate_part_still_rejected():
    bad_config = CONFIG.replace("JobB,1,SubAssembly,1,10", "JobB,1,NoSuchPart,1,10")
    try:
        parse_csv(bad_config)
        assert False, "expected ParseError"
    except ParseError as e:
        assert "not listed in" in str(e)


def test_min_available_lets_dependent_job_start_before_producer_finishes(tmp_path):
    # CellA's output_buffer_size dropped to 1 so JobA's units reach the store
    # one at a time instead of batching all 5 into a single pickup trip --
    # otherwise the store would jump straight from 0 to 5 and never pause at
    # the threshold long enough to prove it's gating on a partial quantity.
    threshold_config = (
        CONFIG.replace("JobB,1,SubAssembly,1,10", "JobB,1,SubAssembly,1,10,2")
              .replace("CellA,10,1.0,1,10,10", "CellA,10,1.0,1,10,1")
    )
    config = parse_csv(threshold_config)
    log_path = str(tmp_path / "run.jsonl")
    sim_result = run_simulation(config, log_path, run_id="test")

    jobs_by_name = {j["name"]: j for j in sim_result["jobs"]}
    job_a, job_b = jobs_by_name["JobA"], jobs_by_name["JobB"]

    assert job_a["completion_tick"] is not None
    assert job_b["completion_tick"] is not None
    # With a threshold of 2 (well under JobA's 5 units), JobB should start
    # well before JobA finishes all 5 units -- the opposite of the legacy
    # full-completion test above.
    assert job_b["assigned_tick"] < job_a["complete_at_cell_tick"]


def test_min_available_on_external_part_rejected():
    bad_config = CONFIG.replace("JobA,1,RawMaterial,1,10", "JobA,1,RawMaterial,1,10,2")
    try:
        parse_csv(bad_config)
        assert False, "expected ParseError"
    except ParseError as e:
        assert "external part" in str(e)


def test_min_available_negative_rejected():
    bad_config = CONFIG.replace("JobB,1,SubAssembly,1,10", "JobB,1,SubAssembly,1,10,-1")
    try:
        parse_csv(bad_config)
        assert False, "expected ParseError"
    except ParseError as e:
        assert "min_available" in str(e)
