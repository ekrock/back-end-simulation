"""Parse the section-based CSV config format into a SimConfig dataclass."""
import csv
import io
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SimulationConfig:
    name: str
    description: str
    max_ticks: int


@dataclass
class JobConfig:
    name: str
    parts_to_build: int
    target_ticks: int


@dataclass
class LineConfig:
    input_buffer_size: int
    output_buffer_size: int
    central_store_distance_meters: int
    fetch_trigger_threshold: int
    deliver_trigger_threshold: int


@dataclass
class StationDef:
    station_name: str
    action_name: str


@dataclass
class RobotTypeDef:
    type_name: str
    speed_meters_per_tick: Optional[int]  # None for non-moving robots
    cost_dollars: int
    actions: dict = field(default_factory=dict)  # action_name -> ticks (0 for fetch/deliver)


@dataclass
class RobotCountDef:
    type_name: str
    count: int


@dataclass
class SimConfig:
    simulation: SimulationConfig
    job: JobConfig
    line: LineConfig
    stations: list
    robot_types: list
    robot_counts: list


class ParseError(ValueError):
    pass


def parse_csv(text: str) -> SimConfig:
    """Parse CSV text into SimConfig. Raises ParseError on invalid input."""
    lines = text.splitlines()

    # Split into sections
    sections: dict[str, list[list[str]]] = {}
    current = None
    for raw in lines:
        row = next(csv.reader([raw]))
        if not row or all(c.strip() == "" for c in row):
            continue
        cell = row[0].strip()
        if cell.startswith("[") and cell.endswith("]"):
            current = cell[1:-1]
            sections[current] = []
        elif current is not None:
            sections[current].append([c.strip() for c in row])

    def need(section):
        if section not in sections:
            raise ParseError(f"Missing section [{section}]")
        return sections[section]

    # [SIMULATION]
    sim_rows = {r[0]: r[1] for r in need("SIMULATION") if len(r) >= 2}
    simulation = SimulationConfig(
        name=_require(sim_rows, "name", "SIMULATION"),
        description=sim_rows.get("description", ""),
        max_ticks=_int(sim_rows, "max_ticks", "SIMULATION"),
    )

    # [JOB]
    job_rows = {r[0]: r[1] for r in need("JOB") if len(r) >= 2}
    job = JobConfig(
        name=_require(job_rows, "name", "JOB"),
        parts_to_build=_int(job_rows, "parts_to_build", "JOB"),
        target_ticks=_int(job_rows, "target_ticks", "JOB"),
    )

    # [LINE]
    line_rows = {r[0]: r[1] for r in need("LINE") if len(r) >= 2}
    line = LineConfig(
        input_buffer_size=_int(line_rows, "input_buffer_size", "LINE"),
        output_buffer_size=_int(line_rows, "output_buffer_size", "LINE"),
        central_store_distance_meters=_int(line_rows, "central_store_distance_meters", "LINE"),
        fetch_trigger_threshold=_int(line_rows, "fetch_trigger_threshold", "LINE"),
        deliver_trigger_threshold=_int(line_rows, "deliver_trigger_threshold", "LINE"),
    )

    # [STATIONS] — skip the header row "station_name,action_name"
    station_rows = need("STATIONS")
    stations = []
    for row in station_rows:
        if len(row) < 2 or row[0] == "station_name":
            continue
        stations.append(StationDef(station_name=row[0], action_name=row[1]))
    if not stations:
        raise ParseError("[STATIONS] must define at least one assembly station")

    # [ROBOT_TYPES] — two-line blocks: line1=type_name,speed,cost; line2=action,ticks pairs
    rt_rows = need("ROBOT_TYPES")
    robot_types = []
    i = 0
    while i < len(rt_rows):
        row1 = rt_rows[i]
        if len(row1) < 3:
            raise ParseError(f"[ROBOT_TYPES] line {i+1}: expected type_name,speed,cost")
        type_name = row1[0]
        speed = int(row1[1]) if row1[1] else None
        cost = int(row1[2])

        i += 1
        if i >= len(rt_rows):
            raise ParseError(f"[ROBOT_TYPES] missing action line for type '{type_name}'")
        row2 = rt_rows[i]
        if len(row2) % 2 != 0:
            raise ParseError(
                f"[ROBOT_TYPES] action line for '{type_name}' must have even number of values "
                f"(action_name,ticks pairs)"
            )
        actions = {}
        for j in range(0, len(row2), 2):
            action_name = row2[j]
            ticks = int(row2[j + 1])
            actions[action_name] = ticks  # ticks for fetch/deliver are ignored by engine

        robot_types.append(RobotTypeDef(
            type_name=type_name,
            speed_meters_per_tick=speed,
            cost_dollars=cost,
            actions=actions,
        ))
        i += 1

    if not robot_types:
        raise ParseError("[ROBOT_TYPES] must define at least one robot type")

    # [ROBOTS] — skip header row "type_name,count"
    robot_count_rows = need("ROBOTS")
    robot_counts = []
    rt_names = {rt.type_name for rt in robot_types}
    for row in robot_count_rows:
        if len(row) < 2 or row[0] == "type_name":
            continue
        if row[0] not in rt_names:
            raise ParseError(f"[ROBOTS] unknown type '{row[0]}'")
        robot_counts.append(RobotCountDef(type_name=row[0], count=int(row[1])))

    if not robot_counts:
        raise ParseError("[ROBOTS] must list at least one robot type with a count")

    return SimConfig(
        simulation=simulation,
        job=job,
        line=line,
        stations=stations,
        robot_types=robot_types,
        robot_counts=robot_counts,
    )


def _require(d: dict, key: str, section: str) -> str:
    if key not in d or not d[key]:
        raise ParseError(f"[{section}] missing required field '{key}'")
    return d[key]


def _int(d: dict, key: str, section: str) -> int:
    val = _require(d, key, section)
    try:
        return int(val)
    except ValueError:
        raise ParseError(f"[{section}] field '{key}' must be an integer, got '{val}'")
