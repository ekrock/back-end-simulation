"""Tick loop for the V2 multi-cell orchestration engine (Sections 12.2-12.6)."""
import math
from collections import deque
from datetime import datetime, timezone

from simulation_v2 import scheduling
from simulation_v2.entities import AMR, Cell, Job, Station
from simulation_v2.otel_logger import OtelLogger
from simulation_v2.replenishment import run_pickup_requests, run_replenishment


def run_simulation(config, log_path: str, run_id: str, start_time=None) -> dict:
    start_time = start_time or datetime.now(timezone.utc)
    logger = OtelLogger(log_path, run_id, start_time)
    log = logger.log

    # ── Build entities ────────────────────────────────────────────────────
    cells = []
    for cd in config.cells:
        stations = [Station(name=f"{cd.cell_name}{n}", number=n) for n in range(1, cd.num_stations + 1)]
        cells.append(Cell(name=cd.cell_name, distance_meters=cd.distance_meters,
                           speed_factor=cd.speed_factor, num_stations=cd.num_stations,
                           lineside_buffer_size=cd.lineside_buffer_size,
                           output_buffer_size=cd.output_buffer_size, stations=stations))
    cells_by_name = {c.name: c for c in cells}

    amr_types_by_name = {t.type_name: t for t in config.amr_types}
    amrs = []
    for ac in config.amr_counts:
        t = amr_types_by_name[ac.type_name]
        for i in range(1, ac.count + 1):
            amrs.append(AMR(name=f"{ac.type_name}{i}", type_name=t.type_name,
                             units_carried=t.units_carried, speed_m_per_s=t.speed_m_per_s,
                             cost_dollars=t.cost_dollars))
    min_amr_speed = min(a.speed_m_per_s for a in amrs)

    jobs = [
        Job(name=jd.job_name, product_name=jd.product_name, units=jd.units,
            arrival_tick=jd.arrival_tick, deadline_tick=jd.deadline_tick,
            capable_cells=jd.capable_cells, steps=jd.steps, file_index=i)
        for i, jd in enumerate(config.jobs)
    ]
    jobs_by_name = {j.name: j for j in jobs}
    producer_by_product = {j.product_name: j for j in jobs}  # P1-2: intermediate-part producers

    store: dict = {}
    request_queue: deque = deque()

    log("simulation_start", 0, name=config.simulation.name,
        scheduling_policy=config.simulation.scheduling_policy,
        replenishment_policy=f"{config.simulation.replenishment_policy},{config.simulation.replenishment_value}",
        cells=len(cells), amrs=len(amrs), jobs=len(jobs))

    tick = 0
    termination_reason = None

    while True:
        # ── STEP 1 Termination ──────────────────────────────────────────
        all_complete = all(j.completion_tick is not None for j in jobs)
        all_amrs_idle = all(a.state == "Idle" for a in amrs)
        if all_complete and all_amrs_idle:
            termination_reason = "all_jobs_complete"
            _log_simulation_end(log, tick, termination_reason, jobs)
            break
        if tick >= config.simulation.max_ticks:
            termination_reason = "max_ticks_reached"
            _log_simulation_end(log, tick, termination_reason, jobs)
            break

        # ── STEP 2 Advance AMRs ──────────────────────────────────────────
        _advance_amrs(amrs, cells_by_name, jobs_by_name, store, tick, log, producer_by_product)

        # ── STEP 3 Job arrivals ──────────────────────────────────────────
        for job in jobs:
            if job.arrival_tick == tick:
                log("job_arrived", tick, job=job.name, deadline_tick=job.deadline_tick, units=job.units)

        # ── STEP 4 Scheduling ─────────────────────────────────────────────
        scheduling.run_scheduling(config, jobs, cells, tick, min_amr_speed, request_queue, log,
                                   producer_by_product)

        # ── STEP 5 Replenishment ──────────────────────────────────────────
        run_replenishment(config, cells, jobs_by_name, tick, min_amr_speed, request_queue, log)

        # ── STEP 6 Pickup requests ────────────────────────────────────────
        run_pickup_requests(cells, jobs_by_name, tick, request_queue, log)

        # ── STEP 7 Dispatch ───────────────────────────────────────────────
        _run_dispatch(amrs, cells_by_name, request_queue, tick, log, store, producer_by_product)

        # ── STEP 8 + 9 Cell processing and state transitions ──────────────
        for cell in cells:
            if cell.job is None:
                continue
            job = jobs_by_name[cell.job]
            state_before = cell.state
            if state_before in ("Running", "Blocked"):
                _process_cell(cell, job, tick, log)

            # DECISION: cell/station/AMR tick counters are tracked live on the
            # entities during the run (matching V1's robot.working_ticks
            # precedent), not derived purely from the log after the fact.
            # Draining -> Idle has no logged end-event, so a pure log-replay
            # can't recover draining_ticks; live counters sidestep that.
            if state_before == "Setup":
                cell.setup_ticks += 1
            elif state_before == "Running":
                cell.running_ticks += 1
            elif state_before == "Blocked":
                if cell.blocked_reason == "starved":
                    cell.blocked_ticks_starved += 1
                else:
                    cell.blocked_ticks_output_full += 1
            elif state_before == "Draining":
                cell.draining_ticks += 1

            _transition_cell(cell, job, tick, log)

        # ── STEP 10 ────────────────────────────────────────────────────────
        tick += 1

    logger.close()
    return _build_result(tick, termination_reason, cells, jobs, amrs, store)


# ── Step 1 helper ──────────────────────────────────────────────────────────

def _total_lateness(jobs, tick):
    return sum(max(0, (j.completion_tick if j.completion_tick is not None else tick) - j.deadline_tick)
               for j in jobs)


def _log_simulation_end(log, tick, reason, jobs):
    unfinished = sum(1 for j in jobs if j.completion_tick is None)
    log("simulation_end", tick, reason=reason, makespan=tick,
        total_lateness=_total_lateness(jobs, tick), unfinished_jobs=unfinished)


# ── Step 2: AMR advance / arrival / return ─────────────────────────────────

def _advance_amrs(amrs, cells_by_name, jobs_by_name, store, tick, log, producer_by_product):
    for amr in amrs:
        if amr.state == "Idle":
            continue
        amr.busy_ticks += 1
        amr.remaining -= 1
        if amr.remaining > 0:
            continue
        if amr.state == "Outbound":
            _handle_arrival(amr, cells_by_name, jobs_by_name, tick, log, store, producer_by_product)
        else:
            _handle_return(amr, jobs_by_name, store, tick, log)


def _handle_arrival(amr, cells_by_name, jobs_by_name, tick, log, store, producer_by_product):
    cell = cells_by_name[amr.cell_name]
    job_name = cell.job
    one_way = math.ceil(cell.distance_meters / amr.speed_m_per_s)

    if amr.trip_kind == "delivery":
        station = next(s for s in cell.stations if s.name == amr.station_name)
        qty = min(amr.loaded_qty, cell.lineside_buffer_size - station.units_remaining)
        station.units_remaining += qty
        station.pending_request = False
        # P1-2: a finite intermediate part that was loaded but couldn't fit in
        # the buffer goes back to the store (external parts have no accounting).
        leftover = amr.loaded_qty - qty
        if leftover > 0 and amr.part_name in producer_by_product:
            store[amr.part_name] = store.get(amr.part_name, 0) + leftover
        log("parts_delivered", tick, job=job_name, cell=cell.name, amr=amr.name,
            station=station.name, part=amr.part_name, qty_delivered=qty,
            units_remaining=station.units_remaining)
    else:  # pickup
        qty = min(amr.units_carried, cell.output_buffer_count)
        cell.output_buffer_count -= qty
        amr.qty = qty
        amr.job_name_for_trip = job_name
        cell.pending_pickup = False
        log("product_picked_up", tick, job=job_name, cell=cell.name, amr=amr.name,
            qty=qty, output_buffer_count=cell.output_buffer_count)

    amr.state = "Inbound"
    amr.remaining = one_way


def _handle_return(amr, jobs_by_name, store, tick, log):
    if amr.trip_kind == "delivery":
        log("amr_returned", tick, amr=amr.name, trip_kind="delivery")
    else:
        job = jobs_by_name[amr.job_name_for_trip]
        store[job.product_name] = store.get(job.product_name, 0) + amr.qty
        job.units_delivered_to_store += amr.qty
        log("product_delivered_to_store", tick, job=job.name, amr=amr.name,
            product=job.product_name, qty=amr.qty, store_count=store[job.product_name])
        if job.units_delivered_to_store >= job.units and job.completion_tick is None:
            job.completion_tick = tick
            lateness = max(0, tick - job.deadline_tick)
            log("job_complete", tick, job=job.name, completion_tick=tick,
                deadline_tick=job.deadline_tick, lateness=lateness)

    amr.state = "Idle"
    amr.trip_kind = None
    amr.cell_name = None
    amr.station_name = None
    amr.part_name = None
    amr.qty = 0
    amr.loaded_qty = 0
    amr.job_name_for_trip = None


# ── Step 7: dispatch ────────────────────────────────────────────────────────

def _run_dispatch(amrs, cells_by_name, request_queue, tick, log, store, producer_by_product):
    while request_queue and any(a.state == "Idle" for a in amrs):
        req = request_queue.popleft()
        amr = next(a for a in amrs if a.state == "Idle")
        cell = cells_by_name[req.cell_name]
        one_way = math.ceil(cell.distance_meters / amr.speed_m_per_s)

        amr.state = "Outbound"
        amr.remaining = one_way
        amr.trip_kind = req.kind
        amr.cell_name = req.cell_name
        amr.station_name = req.station_name
        amr.part_name = req.part_name
        amr.trips += 1

        # P1-2: an intermediate part's store count is finite; external parts
        # are loaded at full AMR capacity (the store's infinite supply of them
        # is never decremented).
        if req.kind == "delivery" and req.part_name in producer_by_product:
            amr.loaded_qty = min(amr.units_carried, store.get(req.part_name, 0))
            store[req.part_name] = store.get(req.part_name, 0) - amr.loaded_qty
        else:
            amr.loaded_qty = amr.units_carried

        log("amr_dispatched", tick, job=cell.job, cell=req.cell_name, amr=amr.name,
            amr_type=amr.type_name, trip_kind=req.kind, station=req.station_name,
            part=req.part_name, qty=amr.loaded_qty, one_way_ticks=one_way)


# ── Step 8: cell pipeline processing (Section 12.5) ─────────────────────────

def _start_rule(station, tick, job, cell, log):
    if station.units_remaining >= station.parts_per_unit:
        station.units_remaining -= station.parts_per_unit
        station.units_started_at_station += 1
        was_starving = station.state == "Starving"
        station.state = "Working"
        station.remaining = station.effective_ticks
        if was_starving:
            starved_ticks = tick - station.starving_since
            log("station_starving_end", tick, job=job.name, cell=cell.name, station=station.name,
                part=station.part_name, units_remaining=station.units_remaining,
                unit_id=station.unit_id, starved_ticks=starved_ticks)
            station.starving_since = None
    else:
        if station.state != "Starving":
            station.state = "Starving"
            station.starving_since = tick
            log("station_starving", tick, job=job.name, cell=cell.name, station=station.name,
                part=station.part_name, units_remaining=station.units_remaining,
                unit_id=station.unit_id)


def _process_cell(cell, job, tick, log):
    k = len(job.steps)
    for idx in range(k - 1, -1, -1):
        st = cell.stations[idx]
        s = idx + 1

        if st.state == "Working":
            st.remaining -= 1
            st.working_ticks += 1
            if st.remaining <= 0:
                st.state = "Holding"

        if st.state == "Holding":
            if s == k:
                if cell.output_buffer_count < cell.output_buffer_size:
                    cycle_ticks = tick - st.entry_tick
                    cell.output_buffer_count += 1
                    cell.units_completed_at_cell += 1
                    log("unit_complete", tick, job=job.name, cell=cell.name,
                        unit_id=st.unit_id, cycle_ticks=cycle_ticks)
                    job.cycle_ticks_list.append(cycle_ticks)
                    st.state = "Idle"
                    st.unit_id = None
                    st.entry_tick = None
                # else: output_full — stays Holding, surfaces via cell_blocked reason
            else:
                nxt = cell.stations[idx + 1]
                if nxt.state == "Idle":
                    nxt.unit_id = st.unit_id
                    nxt.entry_tick = st.entry_tick
                    st.state = "Idle"
                    st.unit_id = None
                    st.entry_tick = None
                    _start_rule(nxt, tick, job, cell, log)

        if st.state == "Starving":
            _start_rule(st, tick, job, cell, log)

        if idx == 0 and st.state == "Idle" and st.units_started_at_station < job.units:
            cell.next_unit_number += 1
            st.unit_id = cell.next_unit_number
            st.entry_tick = tick
            _start_rule(st, tick, job, cell, log)

    for st in cell.stations[:k]:
        if st.state == "Starving":
            st.starving_ticks += 1


# ── Step 9: cell state transitions (Section 12.5) ───────────────────────────

def _transition_cell(cell, job, tick, log):
    k = len(job.steps)
    used = cell.stations[:k]

    if cell.state == "Setup":
        if all(st.units_remaining >= st.parts_per_unit for st in used):
            cell.state = "Running"
            setup_ticks = tick - cell.assigned_tick
            job.begin_tick = tick
            log("job_begin", tick, job=job.name, cell=cell.name, setup_ticks=setup_ticks)
        return

    if cell.state in ("Running", "Blocked"):
        if cell.units_completed_at_cell >= job.units:
            cell.state = "Draining"
            cell_ticks = tick - cell.assigned_tick
            job.complete_at_cell_tick = tick
            log("job_complete_at_cell", tick, job=job.name, cell=cell.name,
                units=job.units, cell_ticks=cell_ticks)
            for st in used:
                st.units_remaining = 0  # P2 would return unused parts to the store
            return

        any_working = any(st.state == "Working" for st in used)
        if cell.state == "Running" and not any_working:
            last = used[-1]
            reason = "output_full" if (last.state == "Holding"
                                        and cell.output_buffer_count >= cell.output_buffer_size) else "starved"
            cell.state = "Blocked"
            cell.blocked_since = tick
            cell.blocked_reason = reason
            log("cell_blocked", tick, job=job.name, cell=cell.name, reason=reason)
        elif cell.state == "Blocked" and any_working:
            blocked_ticks = tick - cell.blocked_since
            log("cell_blocked_end", tick, job=job.name, cell=cell.name,
                reason=cell.blocked_reason, blocked_ticks=blocked_ticks)
            cell.state = "Running"
            cell.blocked_reason = None
        return

    if cell.state == "Draining" and cell.output_buffer_count == 0:
        cell.state = "Idle"
        cell.job = None


# ── Result assembly ──────────────────────────────────────────────────────────

def _build_result(makespan, termination_reason, cells, jobs, amrs, store):
    return {
        "makespan": makespan,
        "termination_reason": termination_reason,
        "cells": [
            {
                "name": c.name,
                "setup_ticks": c.setup_ticks,
                "running_ticks": c.running_ticks,
                "blocked_ticks_starved": c.blocked_ticks_starved,
                "blocked_ticks_output_full": c.blocked_ticks_output_full,
                "draining_ticks": c.draining_ticks,
            }
            for c in cells
        ],
        "stations": [
            {"name": s.name, "working_ticks": s.working_ticks,
             "starving_ticks": s.starving_ticks, "used": s.used}
            for c in cells for s in c.stations
        ],
        "jobs": [
            {
                "name": j.name, "cell": j.assigned_cell, "arrival_tick": j.arrival_tick,
                "assigned_tick": j.assigned_tick, "begin_tick": j.begin_tick,
                "complete_at_cell_tick": j.complete_at_cell_tick,
                "completion_tick": j.completion_tick, "deadline_tick": j.deadline_tick,
                "units": j.units,
                "lateness": max(0, (j.completion_tick if j.completion_tick is not None else makespan)
                                 - j.deadline_tick),
                "unfinished": j.completion_tick is None,
                "avg_unit_cycle_ticks": (round(sum(j.cycle_ticks_list) / len(j.cycle_ticks_list), 1)
                                          if j.cycle_ticks_list else None),
            }
            for j in jobs
        ],
        "amrs": [
            {"name": a.name, "type_name": a.type_name, "busy_ticks": a.busy_ticks,
             "trips": a.trips, "cost_dollars": a.cost_dollars}
            for a in amrs
        ],
        "store": dict(store),
    }
