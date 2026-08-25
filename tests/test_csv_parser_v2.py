"""Tests for simulation_v2/csv_parser.py."""
import pytest

from simulation_v2.csv_parser import ParseError, parse_csv

BASE = """[SIMULATION]
name,Test
description,A test config
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
CellA,20,1.0,2,10,5

[PARTS]
part_name
ConnectorX

[JOBS]
job_name,product_name,units,arrival_tick,deadline_tick,capable_cells
Job1,Harness,5,0,200,CellA

[JOB_STEPS]
job_name,station_number,part_name,parts_per_unit,ticks
Job1,1,ConnectorX,1,8
Job1,2,ConnectorX,1,8
"""


def test_parses_valid_config():
    config = parse_csv(BASE)
    assert config.simulation.name == "Test"
    assert config.simulation.max_ticks == 1000
    assert config.simulation.scheduling_policy == "FIFO"
    assert config.simulation.replenishment_policy == "UnitsLeft"
    assert config.simulation.replenishment_value == 2
    assert len(config.cells) == 1
    assert config.cells[0].cell_name == "CellA"
    assert len(config.jobs) == 1
    assert len(config.jobs[0].steps) == 2


def test_comment_lines_ignored():
    text = "# a full-line comment\n" + BASE
    config = parse_csv(text)
    assert config.simulation.name == "Test"


def test_missing_section_raises():
    text = BASE.replace("[PARTS]\npart_name\nConnectorX\n\n", "")
    with pytest.raises(ParseError, match=r"\[PARTS\]"):
        parse_csv(text)


def test_bad_scheduling_policy_raises():
    text = BASE.replace("scheduling_policy,FIFO", "scheduling_policy,ROUND_ROBIN")
    with pytest.raises(ParseError, match="scheduling_policy"):
        parse_csv(text)


def test_bad_replenishment_policy_raises():
    text = BASE.replace("replenishment_policy,UnitsLeft,2", "replenishment_policy,Magic,2")
    with pytest.raises(ParseError, match="replenishment_policy"):
        parse_csv(text)


def test_unknown_capable_cell_raises():
    text = BASE.replace("Job1,Harness,5,0,200,CellA", "Job1,Harness,5,0,200,CellZ")
    with pytest.raises(ParseError, match="unknown cell"):
        parse_csv(text)


def test_unknown_part_in_job_steps_raises():
    text = BASE.replace("Job1,1,ConnectorX,1,8", "Job1,1,Widget,1,8")
    with pytest.raises(ParseError, match="not listed in \\[PARTS\\]"):
        parse_csv(text)


def test_noncontiguous_station_numbers_raises():
    text = BASE.replace("Job1,2,ConnectorX,1,8", "Job1,3,ConnectorX,1,8")
    with pytest.raises(ParseError, match="contiguous"):
        parse_csv(text)


def test_product_name_collides_with_part_raises():
    text = BASE.replace("Job1,Harness,5,0,200,CellA", "Job1,ConnectorX,5,0,200,CellA")
    with pytest.raises(ParseError, match="collides"):
        parse_csv(text)


def test_parts_per_unit_exceeds_buffer_raises():
    text = BASE.replace(
        "CellA,20,1.0,2,10,5", "CellA,20,1.0,2,10,5"
    ).replace("Job1,1,ConnectorX,1,8", "Job1,1,ConnectorX,99,8")
    with pytest.raises(ParseError, match="lineside_buffer_size"):
        parse_csv(text)


def test_steps_exceed_cell_stations_raises():
    text = BASE.replace("CellA,20,1.0,2,10,5", "CellA,20,1.0,1,10,5")
    with pytest.raises(ParseError, match="only has"):
        parse_csv(text)


def test_max_ticks_limit_enforced():
    text = BASE.replace("max_ticks,1000", "max_ticks,999999")
    with pytest.raises(ParseError, match="max_ticks"):
        parse_csv(text)


def test_arrival_tick_defaults_to_zero():
    text = BASE.replace("Job1,Harness,5,0,200,CellA", "Job1,Harness,5,,200,CellA")
    config = parse_csv(text)
    assert config.jobs[0].arrival_tick == 0


def test_missing_deadline_tick_raises():
    text = BASE.replace("Job1,Harness,5,0,200,CellA", "Job1,Harness,5,0,,CellA")
    with pytest.raises(ParseError, match="deadline_tick"):
        parse_csv(text)
