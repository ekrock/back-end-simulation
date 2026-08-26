"""Tests for optional job preemption (Section 12.2 extension).

Preemption only applies to single-step ("simple") jobs on both sides: the
incoming job and the victim being displaced.
"""
from collections import deque

from simulation_v2.config import JobStepDef
from simulation_v2.csv_parser import ParseError, parse_csv
from simulation_v2.entities import Cell, Job, Station
from simulation_v2.scheduling import run_preemption


class FakeSimulationConfig:
    def __init__(self, preemption_enabled=True):
        self.preemption_enabled = preemption_enabled


def _log_collector():
    events = []

    def log(event, tick, **attrs):
        events.append((event, tick, attrs))
    return events, log


def _busy_cell(job_name, units_completed, begin_tick, cycle_ticks=10, distance=10,
               buffer_leftover=0):
    station = Station(name="CellA1", number=1, part_name="X", parts_per_unit=1,
                       units_remaining=buffer_leftover)
    cell = Cell(name="CellA", distance_meters=distance, speed_factor=1.0, num_stations=1,
                lineside_buffer_size=10, output_buffer_size=5, stations=[station],
                job=job_name, state="Running", job_cycle_ticks=cycle_ticks,
                units_completed_at_cell=units_completed)
    return cell


def _simple_job(name, units, deadline, arrival=0, begin_tick=None, file_index=0, steps_ticks=10,
                 assigned_cell=None):
    steps = [JobStepDef(station_number=1, part_name="X", parts_per_unit=1, ticks=steps_ticks)]
    job = Job(name=name, product_name=f"{name}P", units=units, arrival_tick=arrival,
              deadline_tick=deadline, capable_cells=["CellA"], steps=steps, file_index=file_index)
    job.begin_tick = begin_tick
    job.assigned_cell = assigned_cell
    return job


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


def test_preemption_defaults_to_disabled():
    config = parse_csv(BASE)
    assert config.simulation.preemption_enabled is False


def test_preemption_enabled_true_parses():
    text = BASE.replace("replenishment_policy,UnitsLeft,2",
                         "replenishment_policy,UnitsLeft,2\npreemption_enabled,true")
    config = parse_csv(text)
    assert config.simulation.preemption_enabled is True


def test_preemption_enabled_bad_value_rejected():
    text = BASE.replace("replenishment_policy,UnitsLeft,2",
                         "replenishment_policy,UnitsLeft,2\npreemption_enabled,maybe")
    try:
        parse_csv(text)
        assert False, "expected ParseError"
    except ParseError as e:
        assert "preemption_enabled" in str(e)


# ── Preemption decision logic ────────────────────────────────────────────────

def test_preempts_when_waiting_would_miss_deadline_but_preempting_would_not():
    # Victim has done 2 of 20 units in 20 ticks (10 ticks/unit observed) -- an
    # enormous amount of work left. New job has a tight deadline only
    # preemption can hit.
    cell = _busy_cell("Victim", units_completed=2, begin_tick=0, cycle_ticks=10)
    victim = _simple_job("Victim", units=20, deadline=5000, begin_tick=0, assigned_cell="CellA")
    new_job = _simple_job("Urgent", units=2, deadline=100, arrival=20)
    events, log = _log_collector()

    run_preemption([victim, new_job], [cell], tick=20, min_amr_speed=2.0,
                    request_queue=deque(), log=log, producer_by_product={}, store={})

    assert new_job.assigned_cell == "CellA"
    assert victim.assigned_cell is None
    assert victim.times_preempted == 1
    preempt_events = [e for e in events if e[0] == "job_preempted"]
    assert len(preempt_events) == 1
    assert preempt_events[0][2]["job"] == "Victim"
    assert preempt_events[0][2]["preempted_by"] == "Urgent"


def test_does_not_preempt_when_waiting_would_meet_deadline():
    # Victim is almost done (18 of 20 units); waiting for it clearly beats
    # the new job's generous deadline, so no need to preempt.
    cell = _busy_cell("Victim", units_completed=18, begin_tick=0, cycle_ticks=10)
    victim = _simple_job("Victim", units=20, deadline=5000, begin_tick=0, assigned_cell="CellA")
    new_job = _simple_job("NotUrgent", units=2, deadline=5000, arrival=180)
    events, log = _log_collector()

    run_preemption([victim, new_job], [cell], tick=180, min_amr_speed=2.0,
                    request_queue=deque(), log=log, producer_by_product={}, store={})

    assert new_job.assigned_cell is None
    assert victim.assigned_cell == "CellA"  # untouched
    assert victim.times_preempted == 0
    assert not any(e[0] == "job_preempted" for e in events)


def test_does_not_preempt_when_even_preempting_would_miss_deadline():
    # Deadline is so tight that even taking over the cell immediately can't
    # make it -- preempting would only strand the victim for nothing.
    cell = _busy_cell("Victim", units_completed=1, begin_tick=0, cycle_ticks=10, distance=1000)
    victim = _simple_job("Victim", units=20, deadline=5000, begin_tick=0, assigned_cell="CellA")
    new_job = _simple_job("Impossible", units=50, deadline=5, arrival=10)
    events, log = _log_collector()

    run_preemption([victim, new_job], [cell], tick=10, min_amr_speed=2.0,
                    request_queue=deque(), log=log, producer_by_product={}, store={})

    assert new_job.assigned_cell is None
    assert victim.times_preempted == 0


def test_multistep_victim_is_never_preempted():
    steps = [JobStepDef(station_number=1, part_name="X", parts_per_unit=1, ticks=10),
             JobStepDef(station_number=2, part_name="X", parts_per_unit=1, ticks=10)]
    cell = Cell(name="CellA", distance_meters=10, speed_factor=1.0, num_stations=2,
                lineside_buffer_size=10, output_buffer_size=5,
                stations=[Station(name="CellA1", number=1), Station(name="CellA2", number=2)],
                job="Victim", state="Running", job_cycle_ticks=10, units_completed_at_cell=1)
    victim = Job(name="Victim", product_name="VP", units=20, arrival_tick=0, deadline_tick=5000,
                 capable_cells=["CellA"], steps=steps, file_index=0, begin_tick=0)
    new_job = _simple_job("Urgent", units=2, deadline=100, arrival=20)
    events, log = _log_collector()

    run_preemption([victim, new_job], [cell], tick=20, min_amr_speed=2.0,
                    request_queue=deque(), log=log, producer_by_product={}, store={})

    assert new_job.assigned_cell is None  # nothing eligible to preempt
    assert victim.times_preempted == 0


def test_multistep_job_is_never_a_preemption_candidate():
    steps = [JobStepDef(station_number=1, part_name="X", parts_per_unit=1, ticks=10),
             JobStepDef(station_number=2, part_name="X", parts_per_unit=1, ticks=10)]
    cell = _busy_cell("Victim", units_completed=2, begin_tick=0, cycle_ticks=10)
    victim = _simple_job("Victim", units=20, deadline=5000, begin_tick=0, assigned_cell="CellA")
    new_job = Job(name="MultiStep", product_name="MP", units=2, arrival_tick=20, deadline_tick=30,
                  capable_cells=["CellA"], steps=steps, file_index=1)
    events, log = _log_collector()

    run_preemption([victim, new_job], [cell], tick=20, min_amr_speed=2.0,
                    request_queue=deque(), log=log, producer_by_product={}, store={})

    assert new_job.assigned_cell is None  # not eligible for preemption at all
    assert victim.times_preempted == 0


def test_job_is_only_ever_evaluated_once():
    cell = _busy_cell("Victim", units_completed=18, begin_tick=0, cycle_ticks=10)
    victim = _simple_job("Victim", units=20, deadline=5000, begin_tick=0, assigned_cell="CellA")
    new_job = _simple_job("NotUrgent", units=2, deadline=5000, arrival=180)
    events, log = _log_collector()

    run_preemption([victim, new_job], [cell], tick=180, min_amr_speed=2.0,
                    request_queue=deque(), log=log, producer_by_product={}, store={})
    assert new_job.preemption_evaluated is True

    # Even if circumstances change later (deadline effectively unreachable
    # now), a job already evaluated once is never reconsidered.
    new_job.deadline_tick = 0
    events2, log2 = _log_collector()
    run_preemption([victim, new_job], [cell], tick=181, min_amr_speed=2.0,
                    request_queue=deque(), log=log2, producer_by_product={}, store={})
    assert not events2


def test_return_trip_queued_for_leftover_buffer_only():
    cell = _busy_cell("Victim", units_completed=2, begin_tick=0, cycle_ticks=10, buffer_leftover=4)
    victim = _simple_job("Victim", units=20, deadline=5000, begin_tick=0, assigned_cell="CellA")
    new_job = _simple_job("Urgent", units=2, deadline=100, arrival=20)
    events, log = _log_collector()
    queue = deque()

    run_preemption([victim, new_job], [cell], tick=20, min_amr_speed=2.0,
                    request_queue=queue, log=log, producer_by_product={}, store={})

    return_reqs = [r for r in queue if r.kind == "return"]
    assert len(return_reqs) == 1
    assert return_reqs[0].qty == 4
    assert return_reqs[0].job_name == "Victim"
