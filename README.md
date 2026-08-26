# Back-End Assembly Line Simulator

A tick-based discrete-event simulator for back-end assembly lines. Upload a CSV configuration, run the simulation, and explore OEE metrics, robot utilization, station throughput, and a full event log.

Open-source portfolio and reference implementation of a robot-orchestrated back-end assembly line simulator.

## Local Development

```
cp .env.example .env      # fill in ADMIN/DEMO credentials
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 and upload `static/sample_config.csv` to run the example.

## Deployment (AWS EC2 — Ubuntu 22.04)

1. Point `backendsim.com` DNS A record to the EC2 public IP.
2. SSH into the server and clone the repo, or pull if already cloned.
3. `bash deploy/setup.sh` — installs dependencies, configures nginx (HTTP) and systemd.
4. Edit `/home/ubuntu/back-end-simulation/.env` with real credentials.
5. `bash deploy/setup-https.sh` — obtains Let's Encrypt cert and enables HTTPS.

## CSV Format

See `static/sample_config.csv` for a working example. Sections:

- `[SIMULATION]` — name, description, max_ticks
- `[JOB]` — name, parts_to_build, target_ticks
- `[LINE]` — buffer sizes, central store distance, fetch/deliver thresholds
- `[STATIONS]` — ordered list of station name + action pairs
- `[ROBOT_TYPES]` — two lines per type: `type_name,speed,cost` then `action:ticks,...`
- `[ROBOTS]` — `type_name,count`

## Project Documentation

- [PRD.md](docs/PRD.md) — product requirements and build notes
- [Cases_2-5_Analysis.md](docs/Cases_2-5_Analysis.md) — cable assembly performance analysis across the five scenario cases
- [BESV2_PRD_TechSpec_v06.md](docs/BESV2_PRD_TechSpec_v06.md) — V2 product requirements and technical spec

## V2 — Multi-Cell Orchestration & Predictive Replenishment

V2 lives alongside V1 at `/v2` (V1 is untouched, still at `/`). It simulates line-level orchestration across multiple cells: job scheduling (FIFO vs. deadline-aware EDD), material replenishment (reactive vs. predictive), and AMR (autonomous mobile robot) dispatch, with a full OpenTelemetry-shaped event log.

### Run it

```
python -m simulation_v2 static/v2/sample_config_v2.csv --out /tmp/run1
```

Prints makespan, total lateness, starvation/blocked ticks, and AMR trips. Or upload a CSV through the web UI at `/v2/`.

### CSV Format

Section-based, like V1, with `#`-comment lines and blank-line skipping:

- `[SIMULATION]` — name, description, max_ticks, scheduling_policy (`FIFO`/`EDD`), replenishment_policy (`UnitsLeft,v` / `PercentLeft,p` / `PredictedOut,m`), optional preemption_enabled and job_splitting_enabled (`true`/`false`, both default `false`)
- `[AMR_TYPES]` — type_name, units_carried, speed_m_per_s, cost_dollars
- `[AMRS]` — type_name, count
- `[CELLS]` — cell_name, distance_meters, speed_factor, num_stations, lineside_buffer_size, output_buffer_size
- `[PARTS]` — external part names (infinite supply)
- `[JOBS]` — job_name, product_name, units, arrival_tick, deadline_tick, capable_cells (`|`-separated)
- `[JOB_STEPS]` — job_name, station_number, part_name, parts_per_unit, ticks, optional min_available. `part_name` may be an external part or another job's `product_name` (an intermediate part). By default that job becomes schedulable only once every job producing it has delivered all its units; the optional `min_available` column replaces that with a quantity threshold -- schedulable once the store holds at least that many units, even while the producer is still running.

Full field reference, policy definitions, and metric formulas: `/v2/help`.

### Scenario files and measured results

Each pair in `static/v2/scenarios/` demonstrates one claim, most asserted by `tests/test_p0_claims.py` (the four P0 claims) or a dedicated test file (e.g. `tests/test_e_claim.py`):

| Pair | Claim | Measured result |
|---|---|---|
| `a1_one_cell.csv` / `a2_two_cells.csv` | Adding a cell reduces makespan via parallelization | 430 → 216 ticks |
| `b1_one_amr.csv` / `b2_two_amrs.csv` | Adding an AMR reduces starvation and makespan | starvation 8,489 → 4,141 ticks; makespan 9,001 → 4,672 ticks |
| `b3`/`b4`/`b5` (three/four/five AMRs) | Marginal-returns extension of the b1/b2 series | makespan 3,472 / 2,872 / 2,401 ticks |
| `c1_reactive.csv` / `c2_predictive.csv` | Predictive replenishment beats reactive when AMR lead time is long relative to consumption | starvation 284 → 0 ticks; makespan 2,167 → 1,883 ticks (costs one extra AMR trip, 10 → 11) |
| `d1_fifo.csv` / `d2_edd.csv` | Deadline-aware (EDD) scheduling beats FIFO on total lateness | total lateness 119 → 0 ticks |
| `e1_unstaged.csv` / `e2_staged.csv` | A `min_available` of 0 lets a job compete for its cell with zero buffer; a threshold of 3 keeps it out of the race until an unrelated job takes the cell first, giving the producer time to build a real buffer | starvation 42 → 0 ticks; makespan 232 → 152 ticks; Line2 utilization 57% → 87% |
| `f1_no_preemption.csv` / `f2_preemption.csv` | Preemption saves a late-arriving, tight-deadline job without costing the displaced job its own (more relaxed) deadline | `preemption_enabled`: false → true; JobShort's lateness 151 → 0 ticks; JobLong (displaced once) still finishes with 0 lateness in both files |
| `g1_no_split.csv` / `g2_split.csv` | A job that can't finish on one cell by its deadline hits it once split across enough (not necessarily all) idle capable cells | `job_splitting_enabled`: false → true; lateness 160 → 0 ticks; ran on 1 cell vs. all 3 |

### Tests

```
pytest tests/
```

69 tests: CSV parser validation, FIFO/EDD placement, replenishment policies, hand-computed cell-pipeline mechanics (the Starving/Holding/hand-off state machine), intermediate-part dependencies (including the min_available threshold), preemption decision logic and mechanics, job-splitting decision logic and shard aggregation, engine determinism, the four P0 claims, and the E, F, and G claims above.

### Deploy / update

```
ssh back-end-sim-ec2
cd ~/back-end-simulation
bash deploy/update.sh
```

`deploy/update.sh` pulls `main`, installs any new dependencies, creates `data/runs_v2/` if missing, and restarts the systemd service.

## Architecture

```
simulation/
  csv_parser.py   — section-based CSV → SimConfig dataclasses
  engine.py       — 8-step tick loop, robot assignment, event logging
  analytics.py    — post-run OEE metrics from run_log.jsonl
  robot.py        — RobotType + Robot dataclasses
  station.py      — Station dataclass
  line.py         — LineState dataclass
  logger.py       — JSONL event writer

simulation_v2/
  csv_parser.py   — V2 section-based CSV → SimConfigV2 dataclasses
  engine.py       — 10-step tick loop (Sections 12.2-12.6), pipelined cell processing
  scheduling.py   — FIFO / EDD placement policies
  replenishment.py — UnitsLeft / PercentLeft / PredictedOut policies
  entities.py     — Cell, Station, Job, AMR, TransportRequest dataclasses
  otel_logger.py  — OpenTelemetry-shaped JSONL event log
  analytics.py    — post-run metrics from run_log.jsonl
  __main__.py     — CLI runner (python -m simulation_v2 <config.csv> --out <dir>)

web/
  auth.py         — shared Basic Auth (used by both V1's app.py and V2's routes)
  v2.py           — V2 Flask Blueprint, mounted at /v2

app.py            — Flask app; V1 routes (unchanged) + registers the V2 blueprint
templates/        — base.html, index.html, results.html, chart.html, help.html (V1)
templates/v2/     — base.html, index.html, results.html, help.html, compare.html (V2)
static/           — style.css (shared), sample_config.csv (V1)
static/v2/        — sample_config_v2.csv, scenarios/ (V2 scenario CSV pairs)
data/runs/        — one directory per V1 run (gitignored)
data/runs_v2/     — one directory per V2 run (gitignored)
tests/            — V2 pytest suite
deploy/           — systemd service, nginx configs, setup scripts, update.sh
```
