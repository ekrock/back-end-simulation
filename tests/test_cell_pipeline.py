"""Hand-computed tick-by-tick tests for the pipelined serial flow (Section 12.5).

This is the most bug-prone part of the V2 engine: the Starving/Holding/hand-off
state machine, and the "apply the start rule to the downstream station
immediately on hand-off, without double-processing it" rule. None of the
P0 claim tests or the engine smoke test would catch a subtle bug here, since
they only check aggregate makespan/lateness ordering or that a run completes.
This file drives the pipeline directly, tick by tick, against hand-computed
expected states.
"""
from simulation_v2.config import JobStepDef
from simulation_v2.engine import _process_cell, _transition_cell
from simulation_v2.entities import Cell, Job, Station


def _log_collector():
    events = []

    def log(event, tick, **attrs):
        events.append((event, tick, attrs))
    return events, log


def _make_two_station_cell_and_job(units=2, buffer_units=10, output_buffer_size=5):
    """2 stations: effective_ticks 3 and 2. Line-side buffers pre-loaded so
    replenishment/scheduling are out of scope -- this file tests only the
    pipeline mechanics of Section 12.5."""
    steps = [
        JobStepDef(station_number=1, part_name="X", parts_per_unit=1, ticks=3),
        JobStepDef(station_number=2, part_name="X", parts_per_unit=1, ticks=2),
    ]
    job = Job(name="Job1", product_name="P", units=units, arrival_tick=0, deadline_tick=100,
              capable_cells=["CellA"], steps=steps, file_index=0)
    stations = [
        Station(name="CellA1", number=1, part_name="X", parts_per_unit=1, effective_ticks=3,
                units_remaining=buffer_units),
        Station(name="CellA2", number=2, part_name="X", parts_per_unit=1, effective_ticks=2,
                units_remaining=buffer_units),
    ]
    cell = Cell(name="CellA", distance_meters=20, speed_factor=1.0, num_stations=2,
                lineside_buffer_size=buffer_units, output_buffer_size=output_buffer_size,
                stations=stations, state="Running", job="Job1", assigned_tick=0)
    return cell, job


def test_two_unit_pipeline_matches_hand_computed_trace():
    cell, job = _make_two_station_cell_and_job(units=2)
    s1, s2 = cell.stations
    events, log = _log_collector()

    # tick 0: station1 is Idle -> rule 4 creates unit 1 and starts it immediately.
    _process_cell(cell, job, tick=0, log=log)
    assert s1.state == "Working" and s1.remaining == 3 and s1.unit_id == 1
    assert s2.state == "Idle"

    # ticks 1-2: station1 counts down, nothing else happens yet.
    _process_cell(cell, job, tick=1, log=log)
    assert s1.remaining == 2
    _process_cell(cell, job, tick=2, log=log)
    assert s1.remaining == 1

    # tick 3: station1 finishes (Holding), hands unit 1 to station2 (was Idle),
    # station2 immediately starts (rule 3 applied on hand-off), and station1,
    # now Idle, immediately creates and starts unit 2 (rule 4) in the SAME tick.
    _process_cell(cell, job, tick=3, log=log)
    assert s1.state == "Working" and s1.unit_id == 2 and s1.remaining == 3
    assert s2.state == "Working" and s2.unit_id == 1 and s2.remaining == 2
    assert s2.entry_tick == 0  # unit 1's entry_tick carried over from station1

    # ticks 4: both stations counting down independently.
    _process_cell(cell, job, tick=4, log=log)
    assert s1.remaining == 2 and s2.remaining == 1

    # tick 5: station2 finishes unit 1 -> output buffer (cycle_ticks = 5-0 = 5).
    _process_cell(cell, job, tick=5, log=log)
    assert s2.state == "Idle"
    assert cell.output_buffer_count == 1
    assert job.cycle_ticks_list == [5]
    assert ("unit_complete", 5, {"job": "Job1", "cell": "CellA", "unit_id": 1, "cycle_ticks": 5}) in events
    assert s1.remaining == 1  # station1 still finishing unit 2

    # tick 6: station1 finishes unit 2 (Holding), hands to station2 (Idle again).
    # units_started_at_station(2) == job.units(2), so station1 does NOT create a third unit.
    _process_cell(cell, job, tick=6, log=log)
    assert s1.state == "Idle" and s1.unit_id is None
    assert s2.state == "Working" and s2.unit_id == 2 and s2.entry_tick == 3

    _process_cell(cell, job, tick=7, log=log)
    assert s2.remaining == 1

    # tick 8: station2 finishes unit 2 -> output buffer. Cell has now produced
    # both units of the job -> Running/Blocked -> Draining transition fires.
    _process_cell(cell, job, tick=8, log=log)
    assert cell.output_buffer_count == 2
    assert job.cycle_ticks_list == [5, 5]
    assert cell.units_completed_at_cell == 2

    _transition_cell(cell, job, tick=8, log=log)
    assert cell.state == "Draining"
    assert job.complete_at_cell_tick == 8


def test_station_enters_and_recovers_from_starving():
    cell, job = _make_two_station_cell_and_job(units=1, buffer_units=10)
    s1, s2 = cell.stations
    s2.units_remaining = 0  # station2 has nothing to consume when unit 1 arrives
    events, log = _log_collector()

    for tick in range(3):
        _process_cell(cell, job, tick=tick, log=log)
    # tick 3: station1 holds and hands off; station2 can't start (no parts) -> Starving.
    _process_cell(cell, job, tick=3, log=log)
    assert s2.state == "Starving"
    assert s2.starving_since == 3
    assert ("station_starving", 3, {"job": "Job1", "cell": "CellA", "station": "CellA2",
                                     "part": "X", "units_remaining": 0, "unit_id": 1}) in events

    _transition_cell(cell, job, tick=3, log=log)
    assert cell.state == "Blocked"
    assert cell.blocked_reason == "starved"

    # ticks 4-6: still starving, retried every tick, still no parts.
    for tick in range(4, 7):
        _process_cell(cell, job, tick=tick, log=log)
        assert s2.state == "Starving"
    assert s2.starving_ticks == 4  # ticks 3, 4, 5, 6

    # A delivery arrives: station2 now has enough parts.
    s2.units_remaining = 1
    _process_cell(cell, job, tick=7, log=log)
    assert s2.state == "Working"
    assert s2.remaining == 2
    starving_end = [e for e in events if e[0] == "station_starving_end"]
    assert len(starving_end) == 1
    assert starving_end[0][2]["starved_ticks"] == 4  # tick 7 - tick 3
    assert s2.starving_ticks == 4  # the recovery tick itself is not counted as starving

    _transition_cell(cell, job, tick=7, log=log)
    assert cell.state == "Running"
