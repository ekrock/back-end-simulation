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

---

## Docs

**HTML doc generator**
`scripts/maintenance/generate_doc_html.py` — ported from solar-agent. Run manually after editing any `docs/*.md`. Generates `docs/html/*.html` and `docs/html/index.html`. GROUPS list must be kept in sync with README's doc index.

**PRD sharing**
Shared via GitHub Markdown render (not GitHub Pages). URL: `https://github.com/ekrock/back-end-simulation/blob/main/docs/PRD.md`.

**Backlog**
`docs/backlog.md` — future enhancements not yet scheduled. Currently: Redis rate-limiter backend, Honeycomb.io OpenTelemetry instrumentation (plugin installed but skill invocation not yet working — needs investigation).

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
