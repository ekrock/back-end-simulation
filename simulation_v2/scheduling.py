"""Scheduling policies: FIFO and EDD (Section 12.2)."""
import math

from simulation_v2.entities import TransportRequest


def _effective_ticks(raw_ticks: int, speed_factor: float) -> int:
    return math.ceil(raw_ticks * speed_factor)


def _dependencies_satisfied(job, producer_by_product: dict) -> bool:
    """P1-2: a job depending on another job's product (an intermediate part)
    is only schedulable once every producing job has delivered all its units."""
    for step in job.steps:
        producer = producer_by_product.get(step.part_name)
        if producer is not None and producer.completion_tick is None:
            return False
    return True


def _is_pending(job, tick, producer_by_product):
    return (job.assigned_cell is None and job.arrival_tick <= tick
            and _dependencies_satisfied(job, producer_by_product))


def _assign(job, cell, tick, request_queue, log, policy, estimated_completion=None):
    job.assigned_cell = cell.name
    job.assigned_tick = tick

    cell.job = job.name
    cell.state = "Setup"
    cell.assigned_tick = tick
    cell.next_unit_number = 0
    cell.units_completed_at_cell = 0
    cell.job_cycle_ticks = max(_effective_ticks(s.ticks, cell.speed_factor) for s in job.steps)

    for i, step in enumerate(job.steps):
        station = cell.stations[i]
        station.part_name = step.part_name
        station.parts_per_unit = step.parts_per_unit
        station.effective_ticks = _effective_ticks(step.ticks, cell.speed_factor)
        station.units_remaining = 0
        station.units_started_at_station = 0
        station.state = "Idle"
        station.unit_id = None
        station.entry_tick = None
        station.starving_since = None
        station.used = True

    attrs = {"policy": policy}
    if estimated_completion is not None:
        attrs["estimated_completion"] = estimated_completion
    log("job_assigned", tick, job=job.name, cell=cell.name, **attrs)

    for i, step in enumerate(job.steps):
        station = cell.stations[i]
        station.pending_request = True
        request_queue.append(TransportRequest(kind="delivery", cell_name=cell.name,
                                               station_name=station.name, part_name=step.part_name))
        log("part_request", tick, job=job.name, cell=cell.name, station=station.name,
            part=step.part_name, units_remaining=0, kind="setup")


def _schedule_fifo(jobs, cells, tick, request_queue, log, producer_by_product):
    for job in jobs:  # [JOBS] file order
        if not _is_pending(job, tick, producer_by_product):
            continue
        capable = set(job.capable_cells)
        for cell in cells:  # [CELLS] file order
            if cell.state == "Idle" and cell.name in capable:
                _assign(job, cell, tick, request_queue, log, policy="FIFO")
                break


def _schedule_edd(jobs, cells, tick, min_amr_speed, request_queue, log, producer_by_product):
    cells_by_name = {c.name: c for c in cells}
    cell_order = {c.name: i for i, c in enumerate(cells)}
    pending = [j for j in jobs if _is_pending(j, tick, producer_by_product)]
    pending.sort(key=lambda j: (j.deadline_tick, j.file_index))

    for job in pending:
        capable = sorted(
            (cells_by_name[c] for c in job.capable_cells if cells_by_name[c].state == "Idle"),
            key=lambda c: cell_order[c.name],
        )
        if not capable:
            continue
        best_cell, best_est = None, None
        for cell in capable:
            one_way = math.ceil(cell.distance_meters / min_amr_speed)
            setup_estimate = 2 * one_way
            pipeline_fill = sum(_effective_ticks(s.ticks, cell.speed_factor) for s in job.steps)
            cycle = max(_effective_ticks(s.ticks, cell.speed_factor) for s in job.steps)
            est = tick + setup_estimate + pipeline_fill + (job.units - 1) * cycle + 2 * one_way
            if best_est is None or est < best_est:
                best_cell, best_est = cell, est
        _assign(job, best_cell, tick, request_queue, log, policy="EDD", estimated_completion=best_est)


def run_scheduling(config, jobs, cells, tick, min_amr_speed, request_queue, log, producer_by_product):
    if not any(c.state == "Idle" for c in cells):
        return
    if not any(_is_pending(j, tick, producer_by_product) for j in jobs):
        return
    if config.simulation.scheduling_policy == "FIFO":
        _schedule_fifo(jobs, cells, tick, request_queue, log, producer_by_product)
    else:
        _schedule_edd(jobs, cells, tick, min_amr_speed, request_queue, log, producer_by_product)
