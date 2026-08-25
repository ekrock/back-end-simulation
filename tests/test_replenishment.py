"""Tests for replenishment policies (Section 12.3) against hand-computed cases."""
from collections import deque

from simulation_v2.config import JobStepDef
from simulation_v2.entities import Cell, Job, Station
from simulation_v2.replenishment import run_pickup_requests, run_replenishment


class FakeSimulationConfig:
    def __init__(self, policy, value):
        self.replenishment_policy = policy
        self.replenishment_value = value


class FakeConfig:
    def __init__(self, policy, value):
        self.simulation = FakeSimulationConfig(policy, value)


def _cell_with_station(units_remaining, units_started_at_station, parts_per_unit=1,
                        lineside_buffer_size=10, distance=20, job_cycle_ticks=10, pending=False):
    station = Station(name="CellA1", number=1, part_name="X", parts_per_unit=parts_per_unit,
                       units_remaining=units_remaining, units_started_at_station=units_started_at_station,
                       pending_request=pending)
    cell = Cell(name="CellA", distance_meters=distance, speed_factor=1.0, num_stations=1,
                lineside_buffer_size=lineside_buffer_size, output_buffer_size=5,
                stations=[station], job="Job1", state="Running", job_cycle_ticks=job_cycle_ticks)
    return cell, station


def _job(units=10, parts_per_unit=1):
    steps = [JobStepDef(station_number=1, part_name="X", parts_per_unit=parts_per_unit, ticks=10)]
    return Job(name="Job1", product_name="P", units=units, arrival_tick=0, deadline_tick=100,
               capable_cells=["CellA"], steps=steps, file_index=0)


def _log_collector():
    events = []

    def log(event, tick, **attrs):
        events.append((event, tick, attrs))
    return events, log


def test_units_left_requests_at_or_below_threshold():
    cell, station = _cell_with_station(units_remaining=2, units_started_at_station=0)
    job = _job()
    config = FakeConfig("UnitsLeft", 2)
    queue = deque()
    events, log = _log_collector()

    run_replenishment(config, [cell], {"Job1": job}, tick=5, min_amr_speed=1.0,
                       request_queue=queue, log=log)

    assert len(queue) == 1
    assert station.pending_request is True


def test_units_left_does_not_request_above_threshold():
    cell, station = _cell_with_station(units_remaining=3, units_started_at_station=0)
    job = _job()
    config = FakeConfig("UnitsLeft", 2)
    queue = deque()
    events, log = _log_collector()

    run_replenishment(config, [cell], {"Job1": job}, tick=5, min_amr_speed=1.0,
                       request_queue=queue, log=log)

    assert len(queue) == 0
    assert station.pending_request is False


def test_percent_left_uses_floor_of_buffer_size():
    # 25% of buffer size 10 = floor(2.5) = 2 -> request when units_remaining <= 2
    cell, station = _cell_with_station(units_remaining=2, units_started_at_station=0,
                                        lineside_buffer_size=10)
    job = _job()
    config = FakeConfig("PercentLeft", 25)
    queue = deque()
    events, log = _log_collector()

    run_replenishment(config, [cell], {"Job1": job}, tick=5, min_amr_speed=1.0,
                       request_queue=queue, log=log)

    assert len(queue) == 1


def test_percent_left_does_not_request_above_threshold():
    cell, station = _cell_with_station(units_remaining=3, units_started_at_station=0,
                                        lineside_buffer_size=10)
    job = _job()
    config = FakeConfig("PercentLeft", 25)
    queue = deque()
    events, log = _log_collector()

    run_replenishment(config, [cell], {"Job1": job}, tick=5, min_amr_speed=1.0,
                       request_queue=queue, log=log)

    assert len(queue) == 0


def test_predicted_out_requests_before_reactive_threshold_would():
    # distance=100, min_amr_speed=1.0 -> lead_time = 2*ceil(100/1)=200
    # job_cycle_ticks=10, parts_per_unit=1 -> threshold = ceil(1*200/10) + margin(5) = 20+5=25
    cell, station = _cell_with_station(units_remaining=25, units_started_at_station=0,
                                        lineside_buffer_size=50, distance=100, job_cycle_ticks=10)
    job = _job(units=100)  # large enough that still_needed > 0 at units_remaining=25
    config = FakeConfig("PredictedOut", 5)
    queue = deque()
    events, log = _log_collector()

    run_replenishment(config, [cell], {"Job1": job}, tick=5, min_amr_speed=1.0,
                       request_queue=queue, log=log)

    assert len(queue) == 1  # would NOT have fired yet under UnitsLeft,5 at units_remaining=25


def test_predicted_out_does_not_request_above_threshold():
    cell, station = _cell_with_station(units_remaining=26, units_started_at_station=0,
                                        lineside_buffer_size=50, distance=100, job_cycle_ticks=10)
    job = _job(units=100)
    config = FakeConfig("PredictedOut", 5)
    queue = deque()
    events, log = _log_collector()

    run_replenishment(config, [cell], {"Job1": job}, tick=5, min_amr_speed=1.0,
                       request_queue=queue, log=log)

    assert len(queue) == 0


def test_no_request_when_already_pending():
    cell, station = _cell_with_station(units_remaining=0, units_started_at_station=0, pending=True)
    job = _job()
    config = FakeConfig("UnitsLeft", 5)
    queue = deque()
    events, log = _log_collector()

    run_replenishment(config, [cell], {"Job1": job}, tick=5, min_amr_speed=1.0,
                       request_queue=queue, log=log)

    assert len(queue) == 0


def test_no_request_when_station_has_no_more_need():
    # job.units=5, parts_per_unit=1 -> total need = 5. Already started 5, none remaining.
    cell, station = _cell_with_station(units_remaining=0, units_started_at_station=5)
    job = _job(units=5)
    config = FakeConfig("UnitsLeft", 5)
    queue = deque()
    events, log = _log_collector()

    run_replenishment(config, [cell], {"Job1": job}, tick=5, min_amr_speed=1.0,
                       request_queue=queue, log=log)

    assert len(queue) == 0


def test_pickup_requested_when_buffer_full():
    cell = Cell(name="CellA", distance_meters=20, speed_factor=1.0, num_stations=1,
                lineside_buffer_size=10, output_buffer_size=3, stations=[Station(name="CellA1", number=1)],
                job="Job1", state="Running", output_buffer_count=3)
    job = _job()
    queue = deque()
    events, log = _log_collector()

    run_pickup_requests([cell], {"Job1": job}, tick=5, request_queue=queue, log=log)

    assert len(queue) == 1
    assert cell.pending_pickup is True


def test_pickup_not_requested_twice():
    cell = Cell(name="CellA", distance_meters=20, speed_factor=1.0, num_stations=1,
                lineside_buffer_size=10, output_buffer_size=3, stations=[Station(name="CellA1", number=1)],
                job="Job1", state="Running", output_buffer_count=3, pending_pickup=True)
    job = _job()
    queue = deque()
    events, log = _log_collector()

    run_pickup_requests([cell], {"Job1": job}, tick=5, request_queue=queue, log=log)

    assert len(queue) == 0


def test_pickup_requested_on_final_unit_even_if_buffer_not_full():
    cell = Cell(name="CellA", distance_meters=20, speed_factor=1.0, num_stations=1,
                lineside_buffer_size=10, output_buffer_size=10, stations=[Station(name="CellA1", number=1)],
                job="Job1", state="Draining", output_buffer_count=1, units_completed_at_cell=5)
    job = _job(units=5)
    queue = deque()
    events, log = _log_collector()

    run_pickup_requests([cell], {"Job1": job}, tick=5, request_queue=queue, log=log)

    assert len(queue) == 1
