"""Parse the V2 section-based CSV config format into a SimConfigV2."""
import csv

from simulation_v2.config import (AMRCountDef, AMRTypeDef, CellDef, JobDef,
                                   JobStepDef, SimConfigV2, SimulationConfigV2)

SCHEDULING_POLICIES = {"FIFO", "EDD"}
REPLENISHMENT_POLICIES = {"UnitsLeft", "PercentLeft", "PredictedOut"}

# Hard limits (Section 13) to prevent runaway simulations
_MAX_TICKS = 50_000
_MAX_CELLS = 10
_MAX_STATIONS_PER_CELL = 10
_MAX_AMR_TYPES = 10
_MAX_AMRS_PER_TYPE = 20
_MAX_JOBS = 20
_MAX_UNITS_PER_JOB = 1_000
_MAX_STEPS_PER_JOB = 10


class ParseError(ValueError):
    pass


def parse_csv(text: str) -> SimConfigV2:
    """Parse CSV text into SimConfigV2. Raises ParseError on invalid input."""
    lines = text.splitlines()

    sections: dict[str, list[list[str]]] = {}
    current = None
    for line_no, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
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

    # ── [SIMULATION] ──────────────────────────────────────────────────────
    sim_rows = need("SIMULATION")
    sim_map = {}
    repl_row = None
    for row in sim_rows:
        if not row:
            continue
        key = row[0]
        if key == "replenishment_policy":
            repl_row = row
        elif len(row) >= 2:
            sim_map[key] = row[1]

    name = _require(sim_map, "name", "SIMULATION")
    description = sim_map.get("description", "")
    max_ticks = _int(sim_map, "max_ticks", "SIMULATION")
    scheduling_policy = _require(sim_map, "scheduling_policy", "SIMULATION")
    if scheduling_policy not in SCHEDULING_POLICIES:
        raise ParseError(f"[SIMULATION] scheduling_policy must be one of {sorted(SCHEDULING_POLICIES)}, "
                          f"got '{scheduling_policy}'")
    if repl_row is None or len(repl_row) < 3:
        raise ParseError("[SIMULATION] missing or malformed replenishment_policy row "
                          "(expected replenishment_policy,<PolicyName>,<value>)")
    replenishment_policy = repl_row[1]
    if replenishment_policy not in REPLENISHMENT_POLICIES:
        raise ParseError(f"[SIMULATION] replenishment_policy must be one of "
                          f"{sorted(REPLENISHMENT_POLICIES)}, got '{replenishment_policy}'")
    try:
        replenishment_value = int(repl_row[2])
    except ValueError:
        raise ParseError(f"[SIMULATION] replenishment_policy value must be an integer, got '{repl_row[2]}'")

    if max_ticks > _MAX_TICKS:
        raise ParseError(f"max_ticks exceeds limit of {_MAX_TICKS:,}")

    preemption_enabled = False
    if "preemption_enabled" in sim_map:
        raw_val = sim_map["preemption_enabled"].strip().lower()
        if raw_val not in ("true", "false"):
            raise ParseError(f"[SIMULATION] preemption_enabled must be 'true' or 'false', got '{raw_val}'")
        preemption_enabled = raw_val == "true"

    simulation = SimulationConfigV2(
        name=name, description=description, max_ticks=max_ticks,
        scheduling_policy=scheduling_policy,
        replenishment_policy=replenishment_policy,
        replenishment_value=replenishment_value,
        preemption_enabled=preemption_enabled,
    )

    # ── [AMR_TYPES] ───────────────────────────────────────────────────────
    amr_types = []
    for row in need("AMR_TYPES"):
        if len(row) < 4 or row[0] == "type_name":
            continue
        try:
            units_carried = int(row[1])
            speed = float(row[2])
            cost = int(row[3])
        except ValueError:
            raise ParseError(f"[AMR_TYPES] row for '{row[0]}' has non-numeric units_carried/speed/cost")
        amr_types.append(AMRTypeDef(type_name=row[0], units_carried=units_carried,
                                     speed_m_per_s=speed, cost_dollars=cost))
    if not amr_types:
        raise ParseError("[AMR_TYPES] must define at least one AMR type")
    if len(amr_types) > _MAX_AMR_TYPES:
        raise ParseError(f"Number of AMR types exceeds limit of {_MAX_AMR_TYPES}")
    amr_type_names = {t.type_name for t in amr_types}

    # ── [AMRS] ────────────────────────────────────────────────────────────
    amr_counts = []
    for row in need("AMRS"):
        if len(row) < 2 or row[0] == "type_name":
            continue
        if row[0] not in amr_type_names:
            raise ParseError(f"[AMRS] unknown AMR type '{row[0]}'")
        count = _to_int(row[1], f"[AMRS] count for '{row[0]}'")
        if count > _MAX_AMRS_PER_TYPE:
            raise ParseError(f"AMR count for '{row[0]}' exceeds limit of {_MAX_AMRS_PER_TYPE}")
        amr_counts.append(AMRCountDef(type_name=row[0], count=count))
    if not amr_counts or sum(c.count for c in amr_counts) == 0:
        raise ParseError("[AMRS] must list at least one AMR with count > 0")

    # ── [CELLS] ───────────────────────────────────────────────────────────
    cells = []
    for row in need("CELLS"):
        if len(row) < 6 or row[0] == "cell_name":
            continue
        try:
            distance = int(row[1])
            speed_factor = float(row[2])
            num_stations = int(row[3])
            lineside_buffer_size = int(row[4])
            output_buffer_size = int(row[5])
        except ValueError:
            raise ParseError(f"[CELLS] row for '{row[0]}' has a non-numeric field")
        if speed_factor < 0.1:
            raise ParseError(f"[CELLS] speed_factor for '{row[0]}' must be >= 0.1")
        if num_stations > _MAX_STATIONS_PER_CELL:
            raise ParseError(f"[CELLS] '{row[0]}' has more than {_MAX_STATIONS_PER_CELL} stations")
        cells.append(CellDef(cell_name=row[0], distance_meters=distance, speed_factor=speed_factor,
                              num_stations=num_stations, lineside_buffer_size=lineside_buffer_size,
                              output_buffer_size=output_buffer_size))
    if not cells:
        raise ParseError("[CELLS] must define at least one cell")
    if len(cells) > _MAX_CELLS:
        raise ParseError(f"Number of cells exceeds limit of {_MAX_CELLS}")
    cell_names = {c.cell_name for c in cells}
    cells_by_name = {c.cell_name: c for c in cells}

    # ── [PARTS] ───────────────────────────────────────────────────────────
    parts = []
    for row in need("PARTS"):
        if not row or row[0] == "part_name":
            continue
        parts.append(row[0])
    if not parts:
        raise ParseError("[PARTS] must define at least one external part")
    part_names = set(parts)

    # ── [JOBS] ────────────────────────────────────────────────────────────
    job_rows = need("JOBS")
    jobs = []
    job_names = set()
    product_names = set()
    for row in job_rows:
        if len(row) < 6 or row[0] == "job_name":
            continue
        job_name, product_name, units_s, arrival_s, deadline_s, capable_s = row[:6]
        if job_name in job_names:
            raise ParseError(f"[JOBS] duplicate job_name '{job_name}'")
        job_names.add(job_name)
        if product_name in product_names:
            raise ParseError(f"[JOBS] duplicate product_name '{product_name}'")
        if product_name in part_names:
            raise ParseError(f"[JOBS] product_name '{product_name}' collides with a [PARTS] name")
        product_names.add(product_name)
        units = _to_int(units_s, f"[JOBS] units for '{job_name}'")
        if units > _MAX_UNITS_PER_JOB:
            raise ParseError(f"[JOBS] units for '{job_name}' exceeds limit of {_MAX_UNITS_PER_JOB}")
        arrival_tick = _to_int(arrival_s, f"[JOBS] arrival_tick for '{job_name}'") if arrival_s else 0
        if not deadline_s:
            raise ParseError(f"[JOBS] deadline_tick is required for '{job_name}'")
        deadline_tick = _to_int(deadline_s, f"[JOBS] deadline_tick for '{job_name}'")
        capable_cells = [c for c in capable_s.split("|") if c]
        if not capable_cells:
            raise ParseError(f"[JOBS] capable_cells is required for '{job_name}'")
        for c in capable_cells:
            if c not in cell_names:
                raise ParseError(f"[JOBS] '{job_name}' references unknown cell '{c}' in capable_cells")
        jobs.append(JobDef(job_name=job_name, product_name=product_name, units=units,
                            arrival_tick=arrival_tick, deadline_tick=deadline_tick,
                            capable_cells=capable_cells))
    if not jobs:
        raise ParseError("[JOBS] must define at least one job")
    if len(jobs) > _MAX_JOBS:
        raise ParseError(f"Number of jobs exceeds limit of {_MAX_JOBS}")
    jobs_by_name = {j.job_name: j for j in jobs}

    # ── [JOB_STEPS] ───────────────────────────────────────────────────────
    for row in need("JOB_STEPS"):
        if len(row) < 5 or row[0] == "job_name":
            continue
        job_name, station_s, part_name, ppu_s, ticks_s = row[:5]
        if job_name not in jobs_by_name:
            raise ParseError(f"[JOB_STEPS] references unknown job '{job_name}'")
        station_number = _to_int(station_s, f"[JOB_STEPS] station_number for '{job_name}'")
        parts_per_unit = _to_int(ppu_s, f"[JOB_STEPS] parts_per_unit for '{job_name}'")
        ticks = _to_int(ticks_s, f"[JOB_STEPS] ticks for '{job_name}'")
        # P1-2: a step's part may be an external part (infinite, [PARTS]) or an
        # intermediate part -- another job's product_name (finite, store-tracked).
        if part_name not in part_names and part_name not in product_names:
            raise ParseError(f"[JOB_STEPS] '{job_name}' step references part '{part_name}' "
                              f"not listed in [PARTS] and not any job's product_name")
        if part_name == jobs_by_name[job_name].product_name:
            raise ParseError(f"[JOB_STEPS] '{job_name}' cannot consume its own product "
                              f"'{part_name}' as a part")

        # Optional 6th column: schedule once the store holds at least this many
        # units of an intermediate part, instead of waiting for full producer
        # completion. Only meaningful for intermediate parts (finite, store-tracked).
        min_available = None
        if len(row) >= 6 and row[5] != "":
            if part_name not in product_names:
                raise ParseError(f"[JOB_STEPS] '{job_name}' step sets min_available on "
                                  f"'{part_name}', but that is an external part (always "
                                  f"available) -- min_available only applies to intermediate parts")
            min_available = _to_int(row[5], f"[JOB_STEPS] min_available for '{job_name}'")
            if min_available < 0:
                raise ParseError(f"[JOB_STEPS] min_available for '{job_name}' must be >= 0")

        jobs_by_name[job_name].steps.append(
            JobStepDef(station_number=station_number, part_name=part_name,
                       parts_per_unit=parts_per_unit, ticks=ticks, min_available=min_available)
        )

    for job in jobs:
        if not job.steps:
            raise ParseError(f"[JOB_STEPS] no steps defined for job '{job.job_name}'")
        if len(job.steps) > _MAX_STEPS_PER_JOB:
            raise ParseError(f"[JOB_STEPS] '{job.job_name}' has more than {_MAX_STEPS_PER_JOB} steps")
        numbers = [s.station_number for s in job.steps]
        expected = list(range(1, len(job.steps) + 1))
        if numbers != expected:
            raise ParseError(f"[JOB_STEPS] '{job.job_name}' station_number values must be "
                              f"contiguous 1..{len(job.steps)} in ascending order, got {numbers}")
        k = len(job.steps)
        for cell_name in job.capable_cells:
            cell = cells_by_name[cell_name]
            if k > cell.num_stations:
                raise ParseError(f"[JOB_STEPS] '{job.job_name}' uses {k} stations but capable "
                                  f"cell '{cell_name}' only has {cell.num_stations}")
            for step in job.steps:
                if step.parts_per_unit > cell.lineside_buffer_size:
                    raise ParseError(
                        f"[JOB_STEPS] '{job.job_name}' step at station {step.station_number} needs "
                        f"parts_per_unit={step.parts_per_unit} but capable cell '{cell_name}' has "
                        f"lineside_buffer_size={cell.lineside_buffer_size}"
                    )

    return SimConfigV2(simulation=simulation, amr_types=amr_types, amr_counts=amr_counts,
                        cells=cells, parts=parts, jobs=jobs)


def _require(d: dict, key: str, section: str) -> str:
    if key not in d or not d[key]:
        raise ParseError(f"[{section}] missing required field '{key}'")
    return d[key]


def _int(d: dict, key: str, section: str) -> int:
    val = _require(d, key, section)
    return _to_int(val, f"[{section}] field '{key}'")


def _to_int(val: str, what: str) -> int:
    try:
        return int(val)
    except ValueError:
        raise ParseError(f"{what} must be an integer, got '{val}'")
