"""Scheduling policies: FIFO and EDD (Section 12.2), plus optional preemption."""
import math

from simulation_v2.entities import Job, TransportRequest


def _effective_ticks(raw_ticks: int, speed_factor: float) -> int:
    return math.ceil(raw_ticks * speed_factor)


def _dependencies_satisfied(job, producer_by_product: dict, store: dict) -> bool:
    """P1-2: a job depending on another job's product (an intermediate part) is
    schedulable once the store holds at least step.min_available units of that
    part, if set; otherwise (legacy default) only once the producing job has
    delivered all of its units."""
    for step in job.steps:
        producer = producer_by_product.get(step.part_name)
        if producer is None:
            continue
        if step.min_available is not None:
            if store.get(step.part_name, 0) < step.min_available:
                return False
        elif producer.completion_tick is None:
            return False
    return True


def _is_pending(job, tick, producer_by_product, store):
    return (job.assigned_cell is None and not job.is_split and job.arrival_tick <= tick
            and _dependencies_satisfied(job, producer_by_product, store))


def _estimated_completion(job, cell, start_tick, min_amr_speed, units=None):
    """EDD-style projection (Section 12.2): setup lead time, pipeline fill,
    per-unit cycle time, and a final product pickup trip, starting from
    start_tick. Reused as-is by preemption's and job-splitting's own
    feasibility checks. `units` overrides job.units, for sizing a hypothetical
    shard before it exists as its own Job."""
    if units is None:
        units = job.units
    one_way = math.ceil(cell.distance_meters / min_amr_speed)
    setup_estimate = 2 * one_way
    pipeline_fill = sum(_effective_ticks(s.ticks, cell.speed_factor) for s in job.steps)
    cycle = max(_effective_ticks(s.ticks, cell.speed_factor) for s in job.steps)
    return start_tick + setup_estimate + pipeline_fill + (units - 1) * cycle + 2 * one_way


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


def _schedule_fifo(jobs, cells, tick, request_queue, log, producer_by_product, store):
    for job in jobs:  # [JOBS] file order
        if not _is_pending(job, tick, producer_by_product, store):
            continue
        capable = set(job.capable_cells)
        for cell in cells:  # [CELLS] file order
            if cell.state == "Idle" and cell.name in capable:
                _assign(job, cell, tick, request_queue, log, policy="FIFO")
                break


def _schedule_edd(jobs, cells, tick, min_amr_speed, request_queue, log, producer_by_product, store):
    cells_by_name = {c.name: c for c in cells}
    cell_order = {c.name: i for i, c in enumerate(cells)}
    pending = [j for j in jobs if _is_pending(j, tick, producer_by_product, store)]
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
            est = _estimated_completion(job, cell, tick, min_amr_speed)
            if best_est is None or est < best_est:
                best_cell, best_est = cell, est
        _assign(job, best_cell, tick, request_queue, log, policy="EDD", estimated_completion=best_est)


# ── Preemption (optional) ────────────────────────────────────────────────────

def _victim_projected_free_tick(victim, cell, tick, min_amr_speed):
    """Project when `cell` will free up if `victim` is left to run to
    completion, from observed throughput to date (average ticks/unit), or the
    cell's nominal per-unit cycle time if no unit has completed yet."""
    units_done = cell.units_completed_at_cell
    remaining_units = max(0, victim.units - units_done)
    if victim.begin_tick is not None and units_done > 0:
        rate = (tick - victim.begin_tick) / units_done
    else:
        rate = cell.job_cycle_ticks
    one_way = math.ceil(cell.distance_meters / min_amr_speed)
    return tick + rate * remaining_units + 2 * one_way  # + final product pickup/return trip


def _preempt(job, cell, victim, tick, request_queue, log, estimated_completion):
    """Hand `cell` to `job` immediately: scrap the victim's undelivered
    line-side buffer (an AMR carries it back to the warehouse as a background
    trip, not gating the handover), and return the victim to the pending pool
    with all of its already-delivered progress intact."""
    station = cell.stations[0]  # preemption only supports single-step ("simple") jobs
    leftover = station.units_remaining
    log("job_preempted", tick, job=victim.name, cell=cell.name, preempted_by=job.name,
        units_completed=cell.units_completed_at_cell, units_returned=leftover)
    if leftover > 0:
        request_queue.append(TransportRequest(kind="return", cell_name=cell.name,
                                               station_name=station.name, part_name=station.part_name,
                                               qty=leftover, job_name=victim.name))

    victim.assigned_cell = None
    victim.assigned_tick = None
    victim.begin_tick = None
    victim.times_preempted += 1

    _assign(job, cell, tick, request_queue, log, policy="PREEMPT",
            estimated_completion=estimated_completion)


def run_preemption(jobs, cells, tick, min_amr_speed, request_queue, log, producer_by_product, store):
    cells_by_name = {c.name: c for c in cells}
    jobs_by_name = {j.name: j for j in jobs}

    candidates = [
        j for j in jobs  # [JOBS] file order
        if not j.preemption_evaluated and len(j.steps) == 1
        and _is_pending(j, tick, producer_by_product, store)
    ]

    for job in candidates:
        job.preemption_evaluated = True

        capable_busy = []
        for cell_name in job.capable_cells:
            cell = cells_by_name.get(cell_name)
            if cell is None or cell.job is None or cell.state not in ("Setup", "Running", "Blocked"):
                continue
            victim = jobs_by_name.get(cell.job)
            if victim is None or len(victim.steps) != 1:
                continue  # only "simple" (single-step) jobs are preemptable
            capable_busy.append((cell, victim))
        if not capable_busy:
            continue  # nothing eligible to preempt; job just waits for normal scheduling

        best_wait_est = min(
            _estimated_completion(job, cell, _victim_projected_free_tick(victim, cell, tick, min_amr_speed),
                                   min_amr_speed)
            for cell, victim in capable_busy
        )
        if best_wait_est <= job.deadline_tick:
            continue  # waiting it out already meets the deadline; no need to preempt

        best_cell, best_victim, best_preempt_est = None, None, None
        for cell, victim in capable_busy:
            est = _estimated_completion(job, cell, tick, min_amr_speed)
            if best_preempt_est is None or est < best_preempt_est:
                best_cell, best_victim, best_preempt_est = cell, victim, est
        if best_preempt_est > job.deadline_tick:
            continue  # preempting the best option still wouldn't make the deadline

        _preempt(job, best_cell, best_victim, tick, request_queue, log, best_preempt_est)


# ── Job splitting (optional) ─────────────────────────────────────────────────

def _split_job(job, chosen_cells, tick, min_amr_speed, request_queue, log, jobs, jobs_by_name):
    """Hand `job`'s units to `chosen_cells` as hidden, single-cell shard jobs --
    the parent is never itself assigned to anything. Reuses the normal
    single-job-single-cell machinery unchanged; splitting is purely a
    scheduling-time decision, invisible to everything downstream."""
    n = len(chosen_cells)
    base, remainder = divmod(job.units, n)
    job.is_split = True

    log("job_split", tick, job=job.name, shard_count=n, cells=[c.name for c in chosen_cells])

    for i, cell in enumerate(chosen_cells):
        shard_units = base + (1 if i < remainder else 0)
        shard = Job(name=f"{job.name}#{i + 1}", product_name=job.product_name,
                    units=shard_units, arrival_tick=job.arrival_tick,
                    deadline_tick=job.deadline_tick, capable_cells=[cell.name],
                    steps=job.steps, file_index=job.file_index)
        jobs.append(shard)
        jobs_by_name[shard.name] = shard
        job.shard_names.append(shard.name)
        est = _estimated_completion(job, cell, tick, min_amr_speed, units=shard_units)
        _assign(shard, cell, tick, request_queue, log, policy="SPLIT", estimated_completion=est)


def run_job_splitting(jobs, jobs_by_name, cells, tick, min_amr_speed, request_queue, log,
                       producer_by_product, store):
    cells_by_name = {c.name: c for c in cells}
    cell_order = {c.name: i for i, c in enumerate(cells)}

    candidates = [
        j for j in jobs  # [JOBS] file order
        if not j.split_evaluated and len(j.steps) == 1
        and _is_pending(j, tick, producer_by_product, store)
    ]

    for job in candidates:
        idle_capable = sorted(
            (cells_by_name[c] for c in job.capable_cells
             if cells_by_name.get(c) is not None and cells_by_name[c].state == "Idle"),
            key=lambda c: cell_order[c.name],
        )
        if not idle_capable:
            continue  # nothing available to evaluate against yet; try again once a cell frees
        job.split_evaluated = True

        best_single = min(_estimated_completion(job, c, tick, min_amr_speed) for c in idle_capable)
        if best_single <= job.deadline_tick:
            continue  # one cell is enough; let normal scheduling place it there

        chosen_n = None
        for n in range(2, len(idle_capable) + 1):
            shard_units = math.ceil(job.units / n)
            worst = max(_estimated_completion(job, c, tick, min_amr_speed, units=shard_units)
                        for c in idle_capable[:n])
            if worst <= job.deadline_tick:
                chosen_n = n
                break
        if chosen_n is None:
            chosen_n = len(idle_capable)  # best effort: use everything available

        _split_job(job, idle_capable[:chosen_n], tick, min_amr_speed, request_queue, log,
                   jobs, jobs_by_name)


def run_scheduling(config, jobs, jobs_by_name, cells, tick, min_amr_speed, request_queue, log,
                    producer_by_product, store):
    if config.simulation.job_splitting_enabled:
        # Must be the engine's own jobs_by_name (not a locally rebuilt copy):
        # new shard jobs get added here and need to stay visible to the
        # engine's cell-processing loop, which looks jobs up by name.
        run_job_splitting(jobs, jobs_by_name, cells, tick, min_amr_speed, request_queue, log,
                           producer_by_product, store)

    if any(c.state == "Idle" for c in cells) and any(
            _is_pending(j, tick, producer_by_product, store) for j in jobs):
        if config.simulation.scheduling_policy == "FIFO":
            _schedule_fifo(jobs, cells, tick, request_queue, log, producer_by_product, store)
        else:
            _schedule_edd(jobs, cells, tick, min_amr_speed, request_queue, log, producer_by_product, store)

    if config.simulation.preemption_enabled:
        run_preemption(jobs, cells, tick, min_amr_speed, request_queue, log, producer_by_product, store)
