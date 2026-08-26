"""Tests for optional job splitting across cells.

Splitting only applies to single-step ("simple") jobs. A split job is
represented internally as hidden, single-cell shard jobs; the parent is
never itself assigned to a cell.
"""
from collections import deque

from simulation_v2.config import JobStepDef
from simulation_v2.csv_parser import ParseError, parse_csv
from simulation_v2.entities import Cell, Job, Station
from simulation_v2.scheduling import run_job_splitting


def _idle_cell(name, distance=10):
    station = Station(name=f"{name}1", number=1)
    return Cell(name=name, distance_meters=distance, speed_factor=1.0, num_stations=1,
                lineside_buffer_size=20, output_buffer_size=20, stations=[station], state="Idle")


def _simple_job(name, units, deadline, capable_cells, arrival=0, file_index=0, steps_ticks=10):
    steps = [JobStepDef(station_number=1, part_name="X", parts_per_unit=1, ticks=steps_ticks)]
    return Job(name=name, product_name=f"{name}P", units=units, arrival_tick=arrival,
               deadline_tick=deadline, capable_cells=capable_cells, steps=steps, file_index=file_index)


def _log_collector():
    events = []

    def log(event, tick, **attrs):
        events.append((event, tick, attrs))
    return events, log


# ── CSV parsing ──────────────────────────────────────────────────────────────

BASE = """[SIMULATION]
name,Test
description,test
max_ticks,1000
scheduling_policy,FIFO
replenishment_policy,UnitsLeft,2

[AMR_TYPES]
type_name,units_carried,speed_m_per_s,cost_dollars
Cart,5,2.0,5000

[AMRS]
type_name,count
Cart,1

[CELLS]
cell_name,distance_meters,speed_factor,num_stations,lineside_buffer_size,output_buffer_size
CellA,20,1.0,1,10,5

[PARTS]
part_name
ConnectorX

[JOBS]
job_name,product_name,units,arrival_tick,deadline_tick,capable_cells
Job1,Harness,5,0,200,CellA

[JOB_STEPS]
job_name,station_number,part_name,parts_per_unit,ticks
Job1,1,ConnectorX,1,8
"""


def test_job_splitting_defaults_to_disabled():
    config = parse_csv(BASE)
    assert config.simulation.job_splitting_enabled is False


def test_job_splitting_enabled_true_parses():
    text = BASE.replace("replenishment_policy,UnitsLeft,2",
                         "replenishment_policy,UnitsLeft,2\njob_splitting_enabled,true")
    config = parse_csv(text)
    assert config.simulation.job_splitting_enabled is True


def test_job_splitting_enabled_bad_value_rejected():
    text = BASE.replace("replenishment_policy,UnitsLeft,2",
                         "replenishment_policy,UnitsLeft,2\njob_splitting_enabled,perhaps")
    try:
        parse_csv(text)
        assert False, "expected ParseError"
    except ParseError as e:
        assert "job_splitting_enabled" in str(e)


# ── Splitting decision logic ─────────────────────────────────────────────────

def test_splits_across_smallest_sufficient_number_of_cells():
    # 3 idle cells; a single cell alone is nowhere near enough (30 units at
    # 10 ticks/unit ~= 300+ ticks) but 3-way split comfortably makes it.
    cells = [_idle_cell("CellA"), _idle_cell("CellB"), _idle_cell("CellC")]
    job = _simple_job("Big", units=30, deadline=150, capable_cells=["CellA", "CellB", "CellC"])
    jobs = [job]
    jobs_by_name = {"Big": job}
    events, log = _log_collector()

    run_job_splitting(jobs, jobs_by_name, cells, tick=0, min_amr_speed=2.0,
                       request_queue=deque(), log=log, producer_by_product={}, store={})

    assert job.is_split is True
    assert job.assigned_cell is None
    assert len(job.shard_names) == 3
    assert len(jobs) == 4  # parent + 3 shards
    for name in job.shard_names:
        shard = jobs_by_name[name]
        assert shard.assigned_cell is not None
    total_units = sum(jobs_by_name[n].units for n in job.shard_names)
    assert total_units == 30
    split_events = [e for e in events if e[0] == "job_split"]
    assert len(split_events) == 1
    assert split_events[0][2]["shard_count"] == 3


def test_does_not_split_when_one_cell_suffices():
    cells = [_idle_cell("CellA"), _idle_cell("CellB"), _idle_cell("CellC")]
    job = _simple_job("Small", units=5, deadline=5000, capable_cells=["CellA", "CellB", "CellC"])
    jobs = [job]
    jobs_by_name = {"Small": job}
    events, log = _log_collector()

    run_job_splitting(jobs, jobs_by_name, cells, tick=0, min_amr_speed=2.0,
                       request_queue=deque(), log=log, producer_by_product={}, store={})

    assert job.is_split is False
    assert job.assigned_cell is None  # left for normal FIFO/EDD scheduling to place
    assert len(jobs) == 1
    assert not any(e[0] == "job_split" for e in events)


def test_uses_smallest_n_not_always_the_maximum():
    # 1-way estimate is 320 (misses), 2-way is 170 (meets a 200 deadline), so
    # the algorithm should stop at 2 cells rather than also trying the 3rd.
    cells = [_idle_cell("CellA"), _idle_cell("CellB"), _idle_cell("CellC")]
    job = _simple_job("Medium", units=30, deadline=200, capable_cells=["CellA", "CellB", "CellC"])
    jobs = [job]
    jobs_by_name = {"Medium": job}
    events, log = _log_collector()

    run_job_splitting(jobs, jobs_by_name, cells, tick=0, min_amr_speed=2.0,
                       request_queue=deque(), log=log, producer_by_product={}, store={})

    assert len(job.shard_names) == 2


def test_uses_all_available_cells_as_best_effort_if_still_insufficient():
    cells = [_idle_cell("CellA"), _idle_cell("CellB")]
    job = _simple_job("Impossible", units=1000, deadline=10, capable_cells=["CellA", "CellB"])
    jobs = [job]
    jobs_by_name = {"Impossible": job}
    events, log = _log_collector()

    run_job_splitting(jobs, jobs_by_name, cells, tick=0, min_amr_speed=2.0,
                       request_queue=deque(), log=log, producer_by_product={}, store={})

    assert len(job.shard_names) == 2  # used everything it had, even though still late


def test_multistep_job_is_never_split():
    steps = [JobStepDef(station_number=1, part_name="X", parts_per_unit=1, ticks=10),
             JobStepDef(station_number=2, part_name="X", parts_per_unit=1, ticks=10)]
    cells = [_idle_cell("CellA"), _idle_cell("CellB")]
    job = Job(name="MultiStep", product_name="MP", units=30, arrival_tick=0, deadline_tick=150,
              capable_cells=["CellA", "CellB"], steps=steps, file_index=0)
    jobs = [job]
    jobs_by_name = {"MultiStep": job}
    events, log = _log_collector()

    run_job_splitting(jobs, jobs_by_name, cells, tick=0, min_amr_speed=2.0,
                       request_queue=deque(), log=log, producer_by_product={}, store={})

    assert job.is_split is False
    assert len(jobs) == 1


def test_job_is_only_ever_split_evaluated_once():
    cells = [_idle_cell("CellA"), _idle_cell("CellB")]
    job = _simple_job("Small", units=5, deadline=5000, capable_cells=["CellA", "CellB"])
    jobs = [job]
    jobs_by_name = {"Small": job}
    events, log = _log_collector()

    run_job_splitting(jobs, jobs_by_name, cells, tick=0, min_amr_speed=2.0,
                       request_queue=deque(), log=log, producer_by_product={}, store={})
    assert job.split_evaluated is True

    # Even if the deadline becomes unreachable later, it's never reconsidered.
    job.deadline_tick = 0
    events2, log2 = _log_collector()
    run_job_splitting(jobs, jobs_by_name, cells, tick=1, min_amr_speed=2.0,
                       request_queue=deque(), log=log2, producer_by_product={}, store={})
    assert not events2
    assert job.is_split is False


def test_defers_when_no_capable_cell_is_currently_idle():
    cell = _idle_cell("CellA")
    cell.state = "Running"
    job = _simple_job("Big", units=30, deadline=150, capable_cells=["CellA"])
    jobs = [job]
    jobs_by_name = {"Big": job}
    events, log = _log_collector()

    run_job_splitting(jobs, jobs_by_name, [cell], tick=0, min_amr_speed=2.0,
                       request_queue=deque(), log=log, producer_by_product={}, store={})

    assert job.split_evaluated is False  # not evaluated yet -- no idle cell to compare against
    assert job.is_split is False
