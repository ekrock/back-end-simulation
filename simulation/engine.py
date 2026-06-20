"""Tick-based assembly line simulation engine."""
import math
from typing import Optional

from simulation.csv_parser import SimConfig
from simulation.line import LineState
from simulation.logger import SimLogger
from simulation.robot import Robot, RobotType
from simulation.station import Station

FETCH_ACTION = "fetch parts"
DELIVER_ACTION = "deliver parts"


def run_simulation(config: SimConfig, log_path: str) -> dict:
    """Execute the simulation and return final state for analytics and visualization."""

    logger = SimLogger(log_path)

    # Build robot type map
    rt_map: dict[str, RobotType] = {}
    for rt_def in config.robot_types:
        rt = RobotType(
            type_name=rt_def.type_name,
            speed_meters_per_tick=rt_def.speed_meters_per_tick,
            cost_dollars=rt_def.cost_dollars,
            actions=dict(rt_def.actions),
        )
        rt_map[rt_def.type_name] = rt

    # Instantiate robots
    robots: list[Robot] = []
    for rc in config.robot_counts:
        rt = rt_map[rc.type_name]
        for i in range(1, rc.count + 1):
            robots.append(Robot(name=f"{rc.type_name}{i}", robot_type=rt))

    # Instantiate stations
    stations: list[Station] = [
        Station(name=s.station_name, action_name=s.action_name)
        for s in config.stations
    ]

    # Initialize line state
    line = LineState(
        input_buffer_size=config.line.input_buffer_size,
        output_buffer_size=config.line.output_buffer_size,
        central_store_distance_meters=config.line.central_store_distance_meters,
        fetch_trigger_threshold=config.line.fetch_trigger_threshold,
        deliver_trigger_threshold=config.line.deliver_trigger_threshold,
    )

    dist = config.line.central_store_distance_meters
    target_ticks = config.job.target_ticks

    logger.log({
        "event": "start_simulation",
        "tick": 0,
        "config": {
            "simulation_name": config.simulation.name,
            "job_name": config.job.name,
            "parts_to_build": config.job.parts_to_build,
            "target_ticks": target_ticks,
            "max_ticks": config.simulation.max_ticks,
        },
    })

    tick = 0
    termination_reason = "max_ticks_reached"

    while True:

        # ── STEP 1 — Check termination ──────────────────────────────────────
        deliver_working = _any_working(robots, DELIVER_ACTION)
        if (line.parts_completed >= config.job.parts_to_build
                and line.output_buffer_count == 0
                and not deliver_working):
            termination_reason = "job_complete"
            logger.log({"event": "end_simulation", "tick": tick, "reason": termination_reason})
            break

        if tick >= config.simulation.max_ticks:
            termination_reason = "max_ticks_reached"
            logger.log({"event": "end_simulation", "tick": tick, "reason": termination_reason})
            break

        # ── STEP 2 — Decrement working robots ───────────────────────────────
        for robot in robots:
            if robot.state != "Working":
                continue
            robot.working_ticks += 1
            robot.remaining_ticks -= 1

            if robot.remaining_ticks > 0:
                continue

            # Action finished
            if robot.current_action == FETCH_ACTION:
                line.input_buffer_count = line.input_buffer_size
                logger.log({
                    "event": "finish_action", "tick": tick, "line": 1,
                    "station": "Central Store", "robot": robot.name, "action": FETCH_ACTION,
                })
                _idle_robot(robot)

            elif robot.current_action == DELIVER_ACTION:
                # Output Buffer was already cleared in Step 3 when robot was assigned.
                # Do NOT reset it here — a subsequent job may have already deposited parts.
                logger.log({
                    "event": "finish_action", "tick": tick, "line": 1,
                    "station": "Central Store", "robot": robot.name, "action": DELIVER_ACTION,
                })
                _idle_robot(robot)

            else:
                # Assembly action finished — part stays at station, available next tick
                station = _station_by_name(stations, robot.current_station)
                station.state = "Idle"
                station.locked = False
                station.current_robot = None
                logger.log({
                    "event": "finish_action", "tick": tick, "line": 1,
                    "station": station.name, "robot": robot.name,
                    "action": robot.current_action, "part_id": robot.current_part_id,
                })
                _idle_robot(robot)

        # ── STEP 3 — Deliver check ───────────────────────────────────────────
        end_of_job = (line.parts_completed >= config.job.parts_to_build
                      and line.output_buffer_count > 0)
        if (line.output_buffer_count >= line.deliver_trigger_threshold or end_of_job):
            if not _any_working(robots, DELIVER_ACTION):
                robot = _select_robot(robots, DELIVER_ACTION, target_ticks)
                if robot:
                    computed_ticks = math.ceil(dist / robot.speed)
                    _log_assign(logger, tick, "Central Store", robot, DELIVER_ACTION,
                                computed_ticks)
                    robot.state = "Working"
                    robot.current_action = DELIVER_ACTION
                    robot.current_station = "Central Store"
                    robot.remaining_ticks = computed_ticks
                    line.output_buffer_count = 0  # robot has taken all parts
                    logger.log({
                        "event": "start_action", "tick": tick, "line": 1,
                        "station": "Central Store", "robot": robot.name, "action": DELIVER_ACTION,
                    })

        # ── STEP 4 — Fetch check ─────────────────────────────────────────────
        if (line.input_buffer_count <= line.fetch_trigger_threshold
                and not _any_working(robots, FETCH_ACTION)):
            robot = _select_robot(robots, FETCH_ACTION, target_ticks)
            if robot:
                computed_ticks = math.ceil(dist / robot.speed)
                _log_assign(logger, tick, "Central Store", robot, FETCH_ACTION, computed_ticks)
                robot.state = "Working"
                robot.current_action = FETCH_ACTION
                robot.current_station = "Central Store"
                robot.remaining_ticks = computed_ticks
                logger.log({
                    "event": "start_action", "tick": tick, "line": 1,
                    "station": "Central Store", "robot": robot.name, "action": FETCH_ACTION,
                })

        # ── STEP 5 — Move completed part to Output Buffer ────────────────────
        if stations:
            last = stations[-1]
            if (last.state == "Idle" and last.part_present and not last.locked
                    and line.output_buffer_count < line.output_buffer_size):
                part_id = last.current_part_id
                cycle_time = tick - line.entry_tick[part_id]
                line.output_buffer_count += 1
                logger.log({
                    "event": "part_complete", "tick": tick, "line": 1,
                    "part_id": part_id, "cycle_time_ticks": cycle_time,
                })
                last.part_present = False
                last.current_part_id = None
                line.parts_completed += 1
                if line.parts_completed == config.job.parts_to_build:
                    logger.log({
                        "event": "finish_job", "tick": tick, "line": 1,
                        "job_name": config.job.name,
                        "parts_completed": line.parts_completed,
                    })

        # ── STEP 6 — Assign robots: last station down to second ───────────────
        for idx in range(len(stations) - 1, 0, -1):
            st = stations[idx]
            prev = stations[idx - 1]
            if (st.state == "Idle" and not st.current_robot
                    and prev.part_present and not prev.locked and prev.state == "Idle"):
                robot = _select_robot(robots, st.action_name, target_ticks)
                if robot:
                    part_id = prev.current_part_id
                    prev.part_present = False
                    prev.current_part_id = None
                    st.part_present = True
                    st.locked = True
                    st.state = "Working"
                    st.current_part_id = part_id
                    st.current_robot = robot.name
                    robot.state = "Working"
                    robot.current_action = st.action_name
                    robot.current_station = st.name
                    robot.current_part_id = part_id
                    robot.remaining_ticks = robot.ticks_for(st.action_name)
                    _log_assign(logger, tick, st.name, robot, st.action_name,
                                robot.remaining_ticks, part_id)
                    logger.log({
                        "event": "start_action", "tick": tick, "line": 1,
                        "station": st.name, "robot": robot.name,
                        "action": st.action_name, "part_id": part_id,
                    })

        # ── STEP 7 — Take part from Input Buffer into first station ───────────
        if stations:
            first = stations[0]
            if (first.state == "Idle" and not first.current_robot
                    and line.input_buffer_count >= 1
                    and line.parts_started < config.job.parts_to_build):
                robot = _select_robot(robots, first.action_name, target_ticks)
                if robot:
                    line.input_buffer_count -= 1
                    line.parts_started += 1
                    part_id = line.next_part_id
                    line.next_part_id += 1
                    line.entry_tick[part_id] = tick
                    first.part_present = True
                    first.locked = True
                    first.state = "Working"
                    first.current_part_id = part_id
                    first.current_robot = robot.name
                    robot.state = "Working"
                    robot.current_action = first.action_name
                    robot.current_station = first.name
                    robot.current_part_id = part_id
                    robot.remaining_ticks = robot.ticks_for(first.action_name)
                    if not line.job_started:
                        logger.log({
                            "event": "start_job", "tick": tick, "line": 1,
                            "job_name": config.job.name,
                        })
                        line.job_started = True
                    _log_assign(logger, tick, first.name, robot, first.action_name,
                                robot.remaining_ticks, part_id)
                    logger.log({
                        "event": "start_action", "tick": tick, "line": 1,
                        "station": first.name, "robot": robot.name,
                        "action": first.action_name, "part_id": part_id,
                    })

        # ── STEP 8 — Increment tick ───────────────────────────────────────────
        tick += 1

    logger.close()

    return {
        "total_ticks": tick,
        "termination_reason": termination_reason,
        "parts_completed": line.parts_completed,
        "input_buffer_count": line.input_buffer_count,
        "input_buffer_size": line.input_buffer_size,
        "output_buffer_count": line.output_buffer_count,
        "output_buffer_size": line.output_buffer_size,
        "stations": [
            {
                "name": s.name,
                "action_name": s.action_name,
                "state": s.state,
                "part_present": s.part_present,
                "current_robot": s.current_robot,
            }
            for s in stations
        ],
        "robots": [
            {
                "name": r.name,
                "type_name": r.robot_type.type_name,
                "state": r.state,
                "current_action": r.current_action,
                "current_station": r.current_station,
                "working_ticks": r.working_ticks,
                "cost_dollars": r.cost_dollars,
            }
            for r in robots
        ],
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _any_working(robots: list[Robot], action: str) -> bool:
    return any(r.state == "Working" and r.current_action == action for r in robots)


def _station_by_name(stations: list[Station], name: Optional[str]) -> Station:
    return next(s for s in stations if s.name == name)


def _idle_robot(robot: Robot) -> None:
    robot.state = "Idle"
    robot.current_action = None
    robot.current_station = None
    robot.current_part_id = None
    robot.remaining_ticks = 0


def _select_robot(robots: list[Robot], action: str, target_ticks: int) -> Optional[Robot]:
    """Return the best robot for the given action per the assignment rule, or None."""
    eligible = [r for r in robots if r.state == "Idle" and r.can_do(action)]
    if not eligible:
        return None

    # For fetch/deliver, ticks_for() returns the CSV placeholder value (ignored by engine).
    # The comparison against target_ticks is skipped for those actions since the
    # actual duration is distance-dependent, not a fixed robot capability.
    is_movement = action in (FETCH_ACTION, DELIVER_ACTION)
    if is_movement:
        candidates = eligible
    else:
        under = [r for r in eligible if r.ticks_for(action) < target_ticks]
        candidates = under if under else eligible

    candidates = sorted(candidates, key=lambda r: (r.cost_dollars, r.ticks_for(action) if not is_movement else 0, r.name))
    return candidates[0]


def _log_assign(logger: SimLogger, tick: int, station: str, robot: Robot,
                action: str, ticks_for_action: int, part_id: Optional[int] = None) -> None:
    event = {
        "event": "assign_robot",
        "tick": tick,
        "line": 1,
        "station": station,
        "robot": robot.name,
        "action": action,
        "cost_dollars": robot.cost_dollars,
        "ticks_for_action": ticks_for_action,
    }
    if part_id is not None:
        event["part_id"] = part_id
    logger.log(event)
