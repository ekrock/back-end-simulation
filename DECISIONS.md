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

**P1-2 intermediate parts: no cycle detection beyond direct self-reference** (2026-08-25)
`csv_parser.py` rejects a job step that references its own `product_name`, but does not detect longer dependency cycles (Job A needs B's product, B needs A's product). A cycle like that just leaves both jobs permanently unschedulable (graceful `max_ticks_reached` degradation, not a crash) rather than being caught at parse time. Acceptable given the P1 time budget; full cycle detection would need a proper graph walk over `[JOB_STEPS]`.

**AMR loads intermediate parts from the finite store at dispatch, not arrival** (2026-08-25)
Matches Section 12.4's "AMR loads ... at the store (instant)" happening in the dispatch step. Any loaded-but-undelivered surplus (buffer had less headroom than was loaded) is returned to the store's count; external parts need no such accounting since the store's supply of them is infinite.

**`sample_config_v2.csv` given one AMR, not two** (2026-08-25)
Section 17's definition of done requires every Section 12.7 event type to appear in the sample run's log. With two AMRs the sample never starved or blocked a cell, so `station_starving`/`station_starving_end`/`cell_blocked`/`cell_blocked_end` never fired. Dropping to one shared AMR induces a brief starve-and-recover cycle (still ~350 ticks, still readable end to end) so all 18 event types are exercised.

**P1-3 compare page: self-contained run picker instead of a separate index-page form** (2026-08-25)
`/v2/compare` shows the full run list with checkboxes and the comparison table/charts on the same page (checking boxes and resubmitting a GET to itself), rather than putting checkboxes on `/v2/` and a separate results-only page at `/v2/compare`. One page instead of coordinating two forms across routes; matches the PRD's own `?runs=<id>,<id>,...` URL shape.

---

## Post-deadline enhancements (2026-08-26): preemption, splitting, intermediate-part staging

User requested three further V2 features with a same-day 3pm deadline: (1) job preemption, (2) job splitting across cells, (3) an intermediate-part quantity threshold. Given the 4-hour window, agreed priority order was 3 → 1 → 2, since splitting breaks the one-job-one-cell invariant used throughout scheduling/engine/analytics today and is the highest-risk of the three; preemption's feasibility math reuses EDD's existing `estimated_completion` formula but needs new "interrupt and return parts" mechanics; the intermediate-part threshold builds directly on already-shipped P1-2 machinery.

**Feature 3 shipped: `[JOB_STEPS]` gets an optional 6th column, `min_available`** (2026-08-26)
When set, replaces the P1-2 default ("schedulable only once every producing job has delivered all its units") with a quantity gate: schedulable once the store holds `min_available` units of that intermediate part, even while the producer is still running. Omitting the column preserves the exact legacy behavior -- no regression to the P1-2 tests/scenarios already shipped. `min_available` is rejected at parse time if set on a step whose part is external (only meaningful for intermediate parts). `store` is now threaded through `scheduling.run_scheduling` / `_schedule_fifo` / `_schedule_edd` / `_is_pending` / `_dependencies_satisfied` to make this check.

**E1/E2 demo pair, take 1 (superseded): differentiator was JobC's `capable_cells`, not the threshold value** (2026-08-26)
First attempt varied `min_available` between the two files (1 vs. 8) with JobC arriving at tick 0 in both, capable of a *different* cell in each file. That didn't isolate the threshold: with JobC arriving simultaneously and having no dependency, it always won the race for whichever cell it was capable of, in both files, regardless of the threshold value -- so the threshold was never the actual differentiator, just an incidental detail. Superseded by the take 2 entry below, which was the user's suggested redesign.

**E1/E2 demo pair, take 2 (current): differentiator is `min_available` itself, via JobC's arrival timing** (2026-08-26)
User's redesign: give JobA and JobB the same arrival_tick (0), give JobC arrival_tick 1 (one tick later), and make JobC capable of the *same* cell as JobB in both files (identical job definitions otherwise). Then the threshold alone decides the outcome:
- `e1_unstaged.csv` (`min_available=0`): JobB's dependency is trivially satisfied at tick 0 (store 0 >= threshold 0), so it grabs the cell immediately, before JobC even arrives. JobC arrives at tick 1 to find the cell already taken and has to wait. JobB starves repeatedly since it started with zero buffer.
- `e2_staged.csv` (`min_available=3`): JobB fails its dependency check at tick 0 (store 0 < 3), so it isn't a candidate at all. JobC arrives at tick 1, finds the cell still open (JobB still ineligible), and takes it -- giving the producer a full run's worth of head start. By the time JobC finishes and frees the cell, JobB's threshold has long since cleared and it never starves.

This is a strictly better demonstration of the feature: the two files are now identical except for one number (`min_available`, 0 vs 3), directly showing what that field controls, rather than differing by an unrelated job's cell eligibility. Measured result: starvation 42 -> 0 ticks, makespan 232 -> 152 ticks, Line2 utilization 57% -> 87%.

**Feature 1 shipped: optional job preemption** (2026-08-26)
`[SIMULATION]` gets an optional `preemption_enabled` field (default `false`). Only single-step ("simple") jobs are ever preemption candidates or victims, per the agreed scope. A pending simple job with no idle capable cell is evaluated exactly once (`Job.preemption_evaluated`): for each capable cell running an eligible in-progress job, project when that cell would free (from observed ticks/unit so far, `Job.begin_tick`-relative, falling back to the cell's nominal `job_cycle_ticks` if no unit has completed yet), then reuse EDD's `_estimated_completion` formula (factored out of `_schedule_edd` for this) to estimate the new job's completion if it waited for that cell vs. if it took over immediately. Preempt only if waiting would miss the deadline and preempting would not; otherwise do nothing (matches the spec's "if no option helps, don't preempt" rule). Runs as a pass after normal FIFO/EDD assignment in `run_scheduling`, guarded by the early-exit optimization only covering the FIFO/EDD portion (preemption must still run even when no cell is idle, which is exactly when it's needed).

**New AMR "return" trip kind, mirroring "delivery" in reverse** (2026-08-26)
Preempting a cell clears the victim's line-side buffer instantly (the cell is handed to the new job right away, not gated on the return trip) and queues a `TransportRequest(kind="return", qty=..., job_name=...)`. `qty` and `job_name` are captured at preemption time because they can't be recovered later: the buffer is already zeroed, and by the time the trip is dispatched or arrives, `cell.job` has already changed to the new job. `entities.py`, `engine.py` (`_run_dispatch`/`_handle_arrival`/`_handle_return`), and `otel_logger.py` (`job_preempted`, `parts_returned` events) were updated accordingly. External-parts-only scope (per the agreed "simple job" assumption) means no store crediting is needed on return -- it's a background AMR-time/cost formality, not a state mutation.

**`Job.times_preempted` and `total_preemptions`/`amr_trips_return` added to results, beyond what was strictly asked** (2026-08-26)
Cheap, one-counter-each additions that make the feature's effect directly visible in results.json/the results page/the CSV export, consistent with this project's existing observability bar (every other trip kind and per-job stat is already surfaced). Not a new mechanism, just wiring existing counters through.

**Feature 2 shipped: job splitting, via hidden single-cell "shard" jobs** (2026-08-26)
`[SIMULATION]` gets an optional `job_splitting_enabled` field (default `false`). The scoping review's original worry -- that splitting breaks the one-job-one-cell assumption baked through scheduling/engine/analytics -- turned out avoidable: a split job is represented as N ordinary single-cell shard `Job` objects (`BigJob#1`, `BigJob#2`, ...), created and `_assign()`-ed directly at split time, sharing the parent's `product_name`/deadline/steps. The parent itself (`Job.is_split=True`) is never assigned to anything. This meant **zero changes** to `_schedule_fifo`/`_schedule_edd`/`run_preemption`/replenishment/dispatch/cell-processing -- they operate on shards exactly like any other simple job, with no awareness that splitting exists.

**Splitting decision reuses EDD/preemption's `_estimated_completion`, now with an optional `units` override** (2026-08-26)
The first tick a simple job is pending with at least one idle capable cell, evaluated once (`Job.split_evaluated`, mirroring `preemption_evaluated`): try the single best idle cell first; if that misses the deadline, try N=2,3,... idle cells (evenly split, `math.ceil(units/N)` per shard) and stop at the smallest N whose worst-case shard completion meets the deadline; if none do, use all available idle cells anyway (best effort, same spirit as preemption's "no option helps" case, except here more cells is never actively harmful so it always uses what it has).

**Aggregating shards back into one results.json/results-page row required touching the termination check and total-lateness math, not just `_build_result`** (2026-08-26)
A naive `all(j.completion_tick is not None for j in jobs)` would never be true once a job is split, since the parent itself never completes -- and naively summing lateness per-job would double-count a split job once per shard, all sharing the same deadline. Added `_logical_job_completions()` in `engine.py`: yields one `(deadline, completion)` pair per *logical* job, aggregating a split parent's shards (`max` completion once all are done) and skipping the shards themselves. `_all_jobs_complete`, `_total_lateness`, and `_log_simulation_end`'s unfinished count all go through it now. `_build_result`'s per-job row construction (`_job_row`) does the analogous aggregation for the results.json display: shards are filtered out of the "jobs" list entirely and never shown on their own, only the parent's rolled-up row (min assigned/begin tick, max complete-at-cell/completion tick, summed cycle-time samples, cell names joined).

**`jobs_by_name` must be the engine's own dict, not a copy rebuilt in scheduling.py** (2026-08-26)
`run_scheduling`'s signature grew a `jobs_by_name` parameter specifically for this: new shards get `jobs_by_name[shard.name] = shard` at creation time, and that has to be the exact same dict `engine.py`'s cell-processing loop looks jobs up in (`jobs_by_name[cell.job]`) -- a freshly rebuilt local dict inside `run_job_splitting` would silently diverge and cause a `KeyError` the next tick a shard's cell is processed. `jobs` (the list) doesn't have this problem since `list.append` mutates the same object engine.py holds; dicts needed the same treatment made explicit.

**`Job.shard_count` and `total_job_splits` added to results, matching the preemption feature's observability precedent** (2026-08-26)
Same rationale as `times_preempted`/`total_preemptions`: cheap, wires existing state through to results.json/the results page/the CSV export rather than leaving the feature's effect only visible in the raw event log.
