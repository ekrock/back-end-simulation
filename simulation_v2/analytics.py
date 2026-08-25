"""Compute results.json (Section 12.8) from a V2 simulation result."""
import json


def compute(log_path: str, sim_result: dict) -> dict:
    makespan = sim_result["makespan"]
    jobs = sim_result["jobs"]
    cells = sim_result["cells"]
    stations = [s for s in sim_result["stations"] if s["used"]]
    amrs = sim_result["amrs"]

    total_lateness = sum(j["lateness"] for j in jobs)
    total_starvation_ticks = sum(s["starving_ticks"] for s in stations)
    total_blocked_ticks_starved = sum(c["blocked_ticks_starved"] for c in cells)
    total_blocked_ticks_output_full = sum(c["blocked_ticks_output_full"] for c in cells)
    total_setup_ticks = sum(c["setup_ticks"] for c in cells)
    total_draining_ticks = sum(c["draining_ticks"] for c in cells)

    trip_counts = _count_trips(log_path)
    fleet_cost = sum(a["cost_dollars"] for a in amrs)
    jobs_late = sum(1 for j in jobs if j["lateness"] > 0)
    jobs_unfinished = sum(1 for j in jobs if j["unfinished"])

    ran_cells = [c for c in cells if c["running_ticks"] > 0]
    cell_utilization = {c["name"]: _pct(c["running_ticks"], makespan) for c in cells}
    avg_cell_utilization = (
        round(sum(cell_utilization[c["name"]] for c in ran_cells) / len(ran_cells), 1)
        if ran_cells else 0.0
    )

    station_utilization = {s["name"]: _pct(s["working_ticks"], makespan) for s in stations}
    avg_station_utilization = (
        round(sum(station_utilization.values()) / len(station_utilization), 1)
        if station_utilization else 0.0
    )

    amr_utilization = {a["name"]: _pct(a["busy_ticks"], makespan) for a in amrs}
    avg_amr_utilization = (
        round(sum(amr_utilization.values()) / len(amr_utilization), 1) if amr_utilization else 0.0
    )

    return {
        "makespan": makespan,
        "termination_reason": sim_result["termination_reason"],
        "total_lateness": total_lateness,
        "total_starvation_ticks": total_starvation_ticks,
        "total_blocked_ticks": total_blocked_ticks_starved + total_blocked_ticks_output_full,
        "total_blocked_ticks_starved": total_blocked_ticks_starved,
        "total_blocked_ticks_output_full": total_blocked_ticks_output_full,
        "total_setup_ticks": total_setup_ticks,
        "total_draining_ticks": total_draining_ticks,
        "amr_trips_delivery": trip_counts["delivery"],
        "amr_trips_pickup": trip_counts["pickup"],
        "amr_trips_total": trip_counts["delivery"] + trip_counts["pickup"],
        "fleet_cost": fleet_cost,
        "jobs_late": jobs_late,
        "jobs_unfinished": jobs_unfinished,
        "jobs": jobs,
        "cells": cells,
        "cell_utilization": cell_utilization,
        "avg_cell_utilization": avg_cell_utilization,
        "stations": stations,
        "station_utilization": station_utilization,
        "avg_station_utilization": avg_station_utilization,
        "amrs": amrs,
        "amr_utilization": amr_utilization,
        "avg_amr_utilization": avg_amr_utilization,
    }


def _pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _count_trips(log_path: str) -> dict:
    counts = {"delivery": 0, "pickup": 0}
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            attrs = rec["attributes"]
            if attrs.get("event") == "amr_dispatched":
                kind = attrs.get("trip_kind")
                if kind in counts:
                    counts[kind] += 1
    return counts
