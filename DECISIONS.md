# Decisions Log

Architectural and design decisions for the Back-End Assembly Line Simulator.

---

## Simulation

**Part Cycle Time definition** (2026-06-21)
Entry tick = when a robot is assigned to the cable at Station 1 (same tick the cable is removed from the Input Buffer). Exit tick = when the cable moves from the last assembly station into the Output Buffer. Includes all inter-station waiting time. This means Part CT can exceed the sum of operation times when cables block between stations.

**Robot assignment rule**
Cheapest robot whose ticks_per_action < target_ticks gets assigned. Fallback: cheapest eligible robot regardless of target. Arm routes to Route and Clip automatically in Cases 3–5 because it's the only type meeting the 20-tick target there.

**Cable assembly use case for sample scenarios**
Stations: Insert Cable into Port A / Route and Clip Cable / Insert Cable into Port B.
Times: Assembler 8/28/8, Arm 5/16/5, target_ticks=20.
Chosen because operation times create interesting bottleneck dynamics (see Cases_2-5_Analysis.md).

**Simulation parameter limits** (2026-07-03)
Enforced in `simulation/csv_parser.py` to prevent runaway simulations:
- max_ticks: 50,000
- parts_to_build: 1,000
- Stations: 20
- Robot types: 10
- Robots per type: 20
- CSV file size: 50 KB (enforced in app.py)

---

## Web / Flask

**Auth**
HTTP Basic Auth via Flask decorator. Two users: `eric` (admin/privileged) and `demo` (limited). Credentials in `.env` on EC2 (not committed).

**Single-click login URL** (2026-07-03)
`/login?u=<username>&p=<password>` sets a Flask session cookie and redirects to `/`. Requires `SECRET_KEY` in `.env` on EC2 so sessions survive gunicorn restarts across 2 workers. Demo URL: `https://backendsim.com/login?u=demo&p=CF*.iD!8.rFBruzD8W-R`

**Run storage**
One directory per run under `data/runs/` (gitignored). Each run dir contains `meta.json`, `results.json`, `run_log.jsonl`, and the uploaded `config.csv`. `meta.json` now includes `username` field for demo run tracking.

**Demo run cap** (2026-07-03)
Max 50 demo runs stored on disk. When a demo user submits a new run and the cap is reached, the oldest demo run is deleted. Admin runs (and runs with no `username` field, i.e. runs created before 2026-07-03) are never deleted automatically.

**Rate limiting** (2026-07-03)
Flask-Limiter: 5 uploads/hour per IP for non-admin users. Admin is exempt. Currently uses in-memory storage — with 2 gunicorn workers the effective limit is up to 10/hour. Redis backend is in backlog to make this precise.

**Chart data endpoint**
`/api/chart-data` computes fleet cost at query time by joining robot_types × robot_counts from `meta.json`. Does not cache — re-reads all runs on each request.

**Help page** (2026-07-03)
`/help` — documents CSV format (all sections and fields) and simulation limits. Linked from the header on all pages.

**OpenTelemetry tracing** (2026-07-03)
Flask auto-instrumentation via `FlaskInstrumentor` covers all routes. Custom spans in `new_run()`:
- `csv.parse` — wraps `parse_csv()`; attribute: `csv.size_bytes`; auto-records `ParseError` exceptions
- `simulation.run` — parent span; attributes: `sim.username`, `sim.run_id`, `sim.parts_to_build`, `sim.target_ticks`, `sim.num_stations`, `sim.num_robot_types`, `sim.parts_completed`, `sim.total_ticks`, `sim.termination_reason`
- `simulation.engine` — child of `simulation.run`; wraps `run_simulation()`
- `analytics.compute` — child of `simulation.run`; wraps `compute()`

OTel env vars in EC2 `.env`: `OTEL_SERVICE_NAME=back-end-simulation`, `OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io`, `OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<key>`.
Packages: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-flask`.

**Honeycomb MCP server** (2026-07-03)
Added to Claude Code via: `claude mcp add honeycomb --transport http https://mcp.honeycomb.io/mcp` (US region, OAuth). Takes effect on next session start. Free plan includes MCP access — "Honeycomb Intelligence" is not a separate prerequisite on the Free plan.

---

## Docs

**HTML doc generator**
`scripts/maintenance/generate_doc_html.py` — ported from solar-agent. Run manually after editing any `docs/*.md`. Generates `docs/html/*.html` and `docs/html/index.html`. GROUPS list must be kept in sync with README's doc index.

**PRD sharing**
Shared via GitHub Markdown render (not GitHub Pages). URL: `https://github.com/ekrock/back-end-simulation/blob/main/docs/PRD.md`.

**Backlog**
`docs/backlog.md` — future enhancements not yet scheduled. Currently: Redis rate-limiter backend.

---

## Deployment

**Service name on EC2**: `back-end-simulation.service` (not `backendsim`)
**SSH alias**: `back-end-sim-ec2`
**EC2 layout**: git repo root AND running app at `~/back-end-simulation/`. Venv at `~/back-end-simulation/venv/`. The `deploy/` subdirectory contains nginx/systemd configs only — it is NOT a separate git clone.
**`.env` location**: `~/back-end-simulation/.env` (one level above `deploy/`)
**No outer sudo** when running deploy scripts as the deploy user.

---

## Claude Code / Dev Environment

**Project settings** (`.claude/settings.json`)
Full SSH permission set for `back-end-sim-ec2`, git, brew, curl, scp, python, aws. Matches solar-agent project settings pattern. SessionStart hook loads BRIEF.md + DECISIONS.md via `--rawfile`. PreCompact hook reminds to save session insights to docs.

**Global settings** (`~/.claude/settings.json`)
Allows Edit/Write for `**/*.json` and `**/.claude/**` across all projects.

---

## V2 (multi-cell orchestration & replenishment) — build decisions

**No V1 blueprint move / no landing page** (2026-08-25)
User approved keeping V1 exactly at `/`, unchanged, and mounting V2 at `/v2` with no landing page and no `web/v1.py` blueprint refactor — the highest-risk item in the original PRD (BESV2_PRD_TechSpec_v06.md), since it would have touched the only live, deployed, resume-linked artifact during a two-day crunch. `web/auth.py` was still extracted from `app.py` (a much smaller, safe refactor the PRD itself pre-approved) so V2 routes can share the auth decorator without a circular import.

**requirements.txt is additive, not a replacement list** (2026-08-25)
The PRD's Section 15 `requirements.txt` block omitted `flask-limiter` and the OpenTelemetry packages that V1 already depends on and that stay in place unchanged. Added `pytest` on top of the existing file rather than replacing it.

**No separate `Unit` entity class** (2026-08-25)
`simulation_v2/entities.py` tracks unit identity via `Station.unit_id`/`entry_tick` plus a per-cell `next_unit_number` counter, matching V1's pattern (no separate `Part` object either). A standalone `Unit` class would carry no state nothing else needs.

**V2 metrics tracked live on entities, not purely log-derived** (2026-08-25)
See inline `# DECISION:` in `simulation_v2/engine.py`. Cell/station/AMR tick counters (setup/running/blocked/draining/starving/working/busy ticks) are incremented live during the tick loop, mirroring V1's `robot.working_ticks` precedent, since the Draining→Idle transition has no logged event and can't be recovered by replaying the log alone.

**otel_logger attaches job/cell/amr to any event where they're passed for routing** (2026-08-25)
See inline `# DECISION:` in `simulation_v2/otel_logger.py`. A few trip-span events (e.g. `amr_dispatched`) end up with a `job` or `cell` attribute beyond what Section 12.7's table lists for that specific event. All attributes the table does require are always present; the extras are harmless and useful for debugging.

**`tests/test_cell_pipeline.py` added beyond the PRD's five listed test files** (2026-08-25)
Hand-computed, tick-by-tick tests of the Starving/Holding/hand-off state machine (Section 12.5) — the most bug-prone part of the engine and the one piece none of the PRD's own test files (parser, scheduling, replenishment, engine smoke, P0 claims) exercise in isolation. User-approved addition.

**No `V2_PUBLIC` flag** (2026-08-25)
The PRD's `V2_PUBLIC` toggle existed only to hide the V2 card on the landing page until ready. Since the landing page was dropped, there's nothing left for the flag to gate — V2 routes go live as soon as they're deployed, the same as every V1 route.

**V2 demo rate limit is a separate quota from V1's** (2026-08-25)
`/v2/run/new` was NOT wired to share a combined per-IP counter with V1's `/run/new` limiter. Both independently allow 5 uploads/hour for non-admin users, so a demo user's practical ceiling across V1+V2 combined is up to 10/hour. Section 13's separate "50 stored V2 runs" storage cap is its own independent cap on `data/runs_v2/`, per the spec.

**P1 build order reprioritized per explicit user instruction** (2026-08-25)
PRD Section 10 lists P1-1 (jobs-late), P1-2 (intermediate parts), P1-3 (compare/charts), P1-4 (AMR trip batching) in that order. User confirmed that exact order for P1-1 → P1-2 → P1-3, and explicitly dropped P1-4 (AMR trip batching) from scope entirely rather than deprioritizing it.
