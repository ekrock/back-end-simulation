"""Compute analytics from the simulation log."""
import json


def compute(log_path: str, sim_result: dict) -> dict:
    """Read run_log.jsonl and return analytics dict for results.json."""
    total_ticks = sim_result["total_ticks"]
    parts_completed = sim_result["parts_completed"]

    # Load log events
    events = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    # ── Robot utilization ────────────────────────────────────────────────────
    # working_ticks is tracked directly on each robot during the simulation.
    robot_util = {}
    for r in sim_result["robots"]:
        wt = r["working_ticks"]
        pct = round(wt / total_ticks * 100, 1) if total_ticks > 0 else 0.0
        robot_util[r["name"]] = {
            "working_ticks": wt,
            "utilization_pct": pct,
            "type_name": r["type_name"],
            "cost_dollars": r["cost_dollars"],
        }

    avg_robot_util = (
        round(sum(v["utilization_pct"] for v in robot_util.values()) / len(robot_util), 1)
        if robot_util else 0.0
    )

    # ── Station utilization ──────────────────────────────────────────────────
    # Derive from start_action / finish_action pairs in the log.
    # For in-flight actions at simulation end, use total_ticks as end tick.
    station_start: dict[str, int] = {}   # station -> latest start tick
    station_working: dict[str, int] = {} # station -> accumulated working ticks
    assembly_station_names = {s["name"] for s in sim_result["stations"]}

    for e in events:
        name = e.get("station")
        if name not in assembly_station_names:
            continue
        if e["event"] == "start_action":
            station_start[name] = e["tick"]
        elif e["event"] == "finish_action" and name in station_start:
            station_working[name] = station_working.get(name, 0) + (e["tick"] - station_start.pop(name))

    # Handle in-flight stations at simulation end
    for name, start_tick in station_start.items():
        station_working[name] = station_working.get(name, 0) + (total_ticks - start_tick)

    station_util = {}
    for s in sim_result["stations"]:
        wt = station_working.get(s["name"], 0)
        pct = round(wt / total_ticks * 100, 1) if total_ticks > 0 else 0.0
        station_util[s["name"]] = {
            "action_name": s["action_name"],
            "working_ticks": wt,
            "utilization_pct": pct,
        }

    avg_station_util = (
        round(sum(v["utilization_pct"] for v in station_util.values()) / len(station_util), 1)
        if station_util else 0.0
    )

    # ── Cycle time metrics ───────────────────────────────────────────────────
    cycle_times = [e["cycle_time_ticks"] for e in events if e["event"] == "part_complete"]

    avg_part_cycle_time = (
        round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else None
    )

    # Line Cycle Time = APCT + avg fetch duration + avg deliver duration.
    # This is the true end-to-end time per part (Central Store → line → Central Store)
    # and is always >= APCT.
    fetch_durations = []
    deliver_durations = []
    fetch_start: dict[str, int] = {}
    deliver_start: dict[str, int] = {}
    for e in events:
        if e.get("action") == "fetch parts":
            if e["event"] == "start_action":
                fetch_start[e.get("robot", "")] = e["tick"]
            elif e["event"] == "finish_action":
                robot = e.get("robot", "")
                if robot in fetch_start:
                    fetch_durations.append(e["tick"] - fetch_start.pop(robot))
        elif e.get("action") == "deliver parts":
            if e["event"] == "start_action":
                deliver_start[e.get("robot", "")] = e["tick"]
            elif e["event"] == "finish_action":
                robot = e.get("robot", "")
                if robot in deliver_start:
                    deliver_durations.append(e["tick"] - deliver_start.pop(robot))

    avg_fetch = sum(fetch_durations) / len(fetch_durations) if fetch_durations else 0.0
    avg_deliver = sum(deliver_durations) / len(deliver_durations) if deliver_durations else 0.0

    avg_full_cycle_time = (
        round(avg_part_cycle_time + avg_fetch + avg_deliver, 1)
        if avg_part_cycle_time is not None else None
    )
    avg_non_value_added_time = (
        round(avg_full_cycle_time - avg_part_cycle_time, 1)
        if avg_part_cycle_time is not None and avg_full_cycle_time is not None
        else None
    )

    return {
        "total_ticks": total_ticks,
        "parts_completed": parts_completed,
        "termination_reason": sim_result["termination_reason"],
        "avg_part_cycle_time": avg_part_cycle_time,
        "avg_full_cycle_time": avg_full_cycle_time,
        "avg_non_value_added_time": avg_non_value_added_time,
        "robot_utilization": robot_util,
        "avg_robot_utilization": avg_robot_util,
        "station_utilization": station_util,
        "avg_station_utilization": avg_station_util,
        "visualization": {
            "stations": sim_result["stations"],
            "robots": sim_result["robots"],
            "input_buffer_count": sim_result["input_buffer_count"],
            "input_buffer_size": sim_result["input_buffer_size"],
            "output_buffer_count": sim_result["output_buffer_count"],
            "output_buffer_size": sim_result["output_buffer_size"],
        },
    }
