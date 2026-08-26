"""Tests for FIFO and EDD placement (Section 12.2) against hand-computed cases."""
from collections import deque

from simulation_v2.config import CellDef, JobDef, JobStepDef
from simulation_v2.entities import Cell, Job, Station
from simulation_v2.scheduling import run_scheduling


class FakeSimulationConfig:
    def __init__(self, policy):
        self.scheduling_policy = policy
        self.preemption_enabled = False


class FakeConfig:
    def __init__(self, policy):
        self.simulation = FakeSimulationConfig(policy)


def _make_cell(name, distance=20, speed_factor=1.0, num_stations=2):
    return Cell(name=name, distance_meters=distance, speed_factor=speed_factor,
                num_stations=num_stations, lineside_buffer_size=10, output_buffer_size=5,
                stations=[Station(name=f"{name}{n}", number=n) for n in range(1, num_stations + 1)])


def _make_job(name, file_index, deadline, capable_cells, arrival=0, units=5):
    steps = [JobStepDef(station_number=1, part_name="X", parts_per_unit=1, ticks=10),
             JobStepDef(station_number=2, part_name="X", parts_per_unit=1, ticks=10)]
    return Job(name=name, product_name=f"{name}Product", units=units, arrival_tick=arrival,
               deadline_tick=deadline, capable_cells=capable_cells, steps=steps, file_index=file_index)


def _log_collector():
    events = []

    def log(event, tick, **attrs):
        events.append((event, tick, attrs))
    return events, log


def test_fifo_assigns_first_placeable_cell_in_file_order():
    cell_a = _make_cell("CellA")
    cell_b = _make_cell("CellB")
    job = _make_job("Job1", 0, deadline=100, capable_cells=["CellB", "CellA"])
    events, log = _log_collector()
    config = FakeConfig("FIFO")

    run_scheduling(config, [job], [cell_a, cell_b], 0, min_amr_speed=1.0,
                    request_queue=deque(), log=log, producer_by_product={}, store={})

    # [CELLS] file order is [CellA, CellB]; FIFO picks the first Idle cell in that
    # order regardless of the job's own capable_cells ordering.
    assert job.assigned_cell == "CellA"
    assert cell_a.state == "Setup"
    assert ("job_assigned", 0, {"job": "Job1", "cell": "CellA", "policy": "FIFO"}) in events


def test_fifo_skips_job_with_no_placeable_cell_this_tick():
    cell_a = _make_cell("CellA")
    cell_a.state = "Running"  # not Idle
    job = _make_job("Job1", 0, deadline=100, capable_cells=["CellA"])
    events, log = _log_collector()
    config = FakeConfig("FIFO")

    run_scheduling(config, [job], [cell_a], 0, min_amr_speed=1.0, request_queue=deque(), log=log, producer_by_product={}, store={})

    assert job.assigned_cell is None


def test_fifo_respects_job_file_order_for_a_single_cell():
    cell_a = _make_cell("CellA")
    job1 = _make_job("Job1", 0, deadline=100, capable_cells=["CellA"])
    job2 = _make_job("Job2", 1, deadline=50, capable_cells=["CellA"])  # earlier deadline, later in file
    events, log = _log_collector()
    config = FakeConfig("FIFO")

    run_scheduling(config, [job1, job2], [cell_a], 0, min_amr_speed=1.0, request_queue=deque(), log=log, producer_by_product={}, store={})

    # FIFO uses file order, not deadline order: Job1 (first in file) wins the only cell.
    assert job1.assigned_cell == "CellA"
    assert job2.assigned_cell is None


def test_edd_prefers_earlier_deadline_over_file_order():
    cell_a = _make_cell("CellA")
    job1 = _make_job("Job1", 0, deadline=100, capable_cells=["CellA"])
    job2 = _make_job("Job2", 1, deadline=50, capable_cells=["CellA"])
    events, log = _log_collector()
    config = FakeConfig("EDD")

    run_scheduling(config, [job1, job2], [cell_a], 0, min_amr_speed=1.0, request_queue=deque(), log=log, producer_by_product={}, store={})

    # Only one cell, so only one job can be assigned this tick; EDD orders
    # pending jobs by (deadline_tick, file_index) so Job2 (deadline 50) goes first.
    assert job2.assigned_cell == "CellA"
    assert job1.assigned_cell is None


def test_edd_picks_lower_estimated_completion_cell():
    # CellA is far (100m); CellB is close (10m) -- same speed_factor.
    cell_a = _make_cell("CellA", distance=100)
    cell_b = _make_cell("CellB", distance=10)
    job = _make_job("Job1", 0, deadline=1000, capable_cells=["CellA", "CellB"])
    events, log = _log_collector()
    config = FakeConfig("EDD")

    run_scheduling(config, [job], [cell_a, cell_b], 0, min_amr_speed=1.0, request_queue=deque(), log=log, producer_by_product={}, store={})

    assert job.assigned_cell == "CellB"
    assigned_events = [e for e in events if e[0] == "job_assigned"]
    assert assigned_events[0][2]["policy"] == "EDD"
    assert "estimated_completion" in assigned_events[0][2]


def test_assignment_configures_stations_and_enqueues_setup_requests():
    cell_a = _make_cell("CellA")
    job = _make_job("Job1", 0, deadline=100, capable_cells=["CellA"])
    events, log = _log_collector()
    config = FakeConfig("FIFO")
    queue = deque()

    run_scheduling(config, [job], [cell_a], 0, min_amr_speed=1.0, request_queue=queue, log=log, producer_by_product={}, store={})

    assert cell_a.stations[0].part_name == "X"
    assert cell_a.stations[0].parts_per_unit == 1
    assert cell_a.stations[0].pending_request is True
    assert len(queue) == 2  # one delivery request per step
    assert queue[0].station_name == "CellA1"
    assert queue[1].station_name == "CellA2"
