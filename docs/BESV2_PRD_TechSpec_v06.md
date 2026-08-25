# Factory Orchestration & Observability Simulation — V2 PRD / Tech Spec

**MVP for electronics back-end / FATP orchestration simulation**

*For electronics back-end assembly, box build, and Final Assembly, Test & Packaging (FATP)*

| Field | Value |
|---|---|
| Author | Eric Krock, Product Management |
| Product area | Line-level and factory-level orchestration and observability (ISA-95 Levels 3 to 4) |
| Hypothetical customer | Large electronics manufacturing services (EMS) provider |
| Status | Approved for implementation |
| Version | 0.6 |
| Deadline | Working V2 simulation deployed by EOD Wednesday, August 26, 2026 |
| GitHub repo | `ekrock/back-end-simulation` (public) — V2 lives alongside V1 |
| Live site | https://backendsim.com |
| Confidentiality | Illustrative example. Contains no proprietary or confidential information. |

---

## Build notes for Claude Code (read first)

- **Read the V1 code before writing any V2 code.** V2 reuses V1's patterns: section-based CSV parser, tick loop, JSONL event log, post-run analytics, Flask + Jinja templates, Basic Auth, `/data/runs/` storage. Where V1 already solved a problem, solve it the same way.
- **V1 is frozen.** Do not modify anything under `simulation/`. The only V1 change permitted is a route prefix (`/v1`) applied via a Flask Blueprint, plus the `url_for` updates in V1 templates that the prefix requires. No behavior changes.
- **Build in this order, and verify each stage before moving on:**
  1. `simulation_v2/` engine + CSV parser + headless CLI runner + unit tests
  2. P0 scenario files + `tests/test_p0_claims.py` passing (Section 16)
  3. Flask V2 routes and templates (Section 14)
  4. Landing page at `/`, V1 moved to `/v1`
  5. Deploy to EC2 (git pull + service restart); verify on https://backendsim.com
  6. P1 items, in the order listed in Section 10, only after P0 is deployed and the definition of done (Section 17) passes
- **Priority tags are inline.** P0 = must ship no later than 9 p.m. PT Wednesday. P1 = do after P0 is deployed. P2 = do not build; design so it can be added later. If time runs out mid-P1, stop at a clean commit; a working P0 beats a half-built P1.
- **Ambiguity policy (same as V1):** make a reasonable decision, implement it, leave a code comment starting `# DECISION:` and add one line to `docs/DECISIONS.md`. Do not stop to ask unless truly blocking.
- **Performance target:** the largest allowed configuration (Section 13 limits) must complete in under 60 seconds on the t3.small. Pure Python, no simulation libraries, no NumPy. Avoid per-tick allocation of large structures; keep the per-tick loop O(cells × stations + AMRs + pending requests).
- **Determinism:** given the same CSV, the simulation must produce byte-identical logs on every run. All tiebreaks are specified; no randomness.
- The simulation runs to completion server-side, then displays results. No WebSockets, no live streaming (that is V3).
- Suggested time-boxes: engine + tests done Tuesday night; web layer by Wednesday noon; deployed by Wednesday 3pm PT; P1 with remaining time.

---

## 1. Summary

The field of robotics automation has strong building blocks for coordinating robots *inside* a work cell (in-cell planners for multi-arm task and motion planning, an open-source robotic operating system as the middleware foundation, and platforms for building robot applications), but still needs to coordinate work *across* cells at the line and factory level, and provide unified visibility into how a whole line, area, and factory is running. Manufacturing customers already own the systems above this gap (ERP for orders and material planning, MES for execution of record) and are automating individual cells below it. What is missing is the connective layer between them.

This document defines an MVP simulation of that layer: a shared observability foundation across heterogeneous cells and stations, plus a bounded, high-return slice of orchestration — multi-cell job scheduling and predictive material replenishment that dispatches autonomous mobile robots (AMRs) before a station starves. It complements the in-cell planner below and MES and ERP beside.

The strategic thesis: back-end assembly, box build, and FATP are high-mix and structured as parallel, reconfigurable cells rather than a paced serial line. Turning those islands of automation into a coherent, observable, non-starving flow of product is the problem this simulation focuses on.

## 2. Background and strategic context

Front-end SMT is already well automated because it is the fixed-automation sweet spot: high volume, low variety, a fixed operation sequence. Electronics back-end (post-SMT insertion, box build, and FATP) resisted automation because it is high-mix and variable, dense with tasks that historically required human dexterity and judgment. That is where flexible robotic cells, and therefore orchestration, become necessary.

A robotic back-end line is not one machine; it is a set of cells (some robotic, some manual, plus test and packaging stations) fed by material logistics. Coordinating them is a scheduling and material-flow problem on top of a fleet of cells that do not naturally form a line. This is the practical meaning of connecting islands of automation, and it is where the four-layer orchestration ladder locates the opportunity.

**Where this simulation sits and what it integrates with**

| Layer | What it does | Owned by | This MVP's relationship |
|---|---|---|---|
| 1. Motion coordination | Collision-free multi-arm motion within a cell | In-cell planner, robot middleware | Consume cell status only |
| 2. Task sequencing (in-cell) | Task allocation and scheduling among arms in a cell | In-cell planner | Hand a cell a job; the in-cell planner plans how |
| 3. Line-level orchestration | Which jobs run where and in what order across cells; material flow | Gap (this simulation) | Core of the MVP |
| 4. Factory-level orchestration | Cross-line and logistics coordination, production planning link | Gap (this simulation) | Partially addressed; most deferred |
| Observability | Unified live state and history across all layers | Gap (this simulation) | Foundation delivered in the MVP |
| Business and execution systems | Orders, material planning, work orders, execution of record | Customer ERP and MES | Integrate and complement; simulation assumes MES can be commanded to execute a job on a cell and serves as system of record for work completed |
| Robot transport | AMR path planning and traffic management | Fleet-management framework | Dispatch transport tasks to it; it plans the paths |

## 3. Goals and non-goals

**Goals for the simulation (outcomes)**

- **Make the factory observable.** Give a single picture of every cell, station, line-side buffer, and AMR over the life of a run, with downtime attribution (starvation vs. output blocking vs. setup).
- **Reduce material-caused stops.** Prevent starvation by delivering material before line-side buffers deplete, rather than expediting after they empty. Compare threshold-based and predictive replenishment policies.
- **Dynamic multi-cell job scheduling.** Different cells can execute the same job with different performance; compare policies for which jobs run on which cells.
- **Demonstrate that responsive policies beat static ones.** Every claim in Section 10 is backed by a pair of scenario files and an automated test.

**Non-goals (explicitly out of scope for the MVP)**

- **Commanding robot motion.** The in-cell planner and the cell safety layer own motion; orchestration never issues motion commands.
- **Black-box / RL-driven dispatch.** The MVP uses transparent, inspectable rules. The FIFO and EDD heuristics defined here are the named baselines a learned policy would later have to beat.
- **Quality, yield, and predictive-maintenance analytics.** Enabled by the observability foundation, but a later phase.

**Constraints**

- **Use only public information so the simulation can be made public and open-sourced.** No references to any company or product by name. No proprietary or confidential information.
- **Deliver a working, deployed V2 simulation by EOD Wednesday, August 26, 2026.**

## 4. Personas relevant to simulation functionality

| Persona | Role and goals | Pain today | What the MVP gives them |
|---|---|---|---|
| Line / Production Manager (primary) | Owns line output, uptime, on-time delivery | Line stops are discovered late; causes are unclear | Attributed downtime per cell and station; lateness per job; policy comparison |
| Material / Logistics Coordinator (primary) | Keeps line-side material available; runs milk-runs | Reactive expediting after a buffer empties | Predictive replenishment; AMRs dispatched before depletion; trip counts to size the fleet |
| Operations / Plant Leadership (economic buyer) | OEE, cost, NPI speed, ROI | Hard to see or improve whole-line performance | Makespan, utilization, lateness, and fleet cost per configuration |

## 5. Assumptions

- **MES and ERP are not simulated.** Products, jobs, and deadlines are defined in a simple input CSV even though this information would come from MES and ERP in reality.
- One line-side buffer per station. Line-side buffers expose the number of units remaining.
- Cells and stations expose running / not-running state.
- An AMR fleet exists with a fleet-manager API. The fleet manager owns path planning and traffic; we dispatch transport tasks to it. Trip duration is distance ÷ speed; collisions and congestion are ignored.
- The MVP targets a single site with a configurable number of cells.

## 6. Problems to simulate

The MVP addresses three tightly coupled problems, in dependency order. You cannot orchestrate what you cannot observe, so the observability foundation comes first and delivers standalone value.

**P1. Unified visibility across stations, line-side buffers, cells, AMRs, and jobs.** Today the state of a back-end is scattered across cell controllers, manual-station scans, test logs, the MES, and the AMR fleet, with no single picture. Managers learn about stops after they happen and cannot attribute downtime. The simulation records every state change as an OpenTelemetry-shaped log record so it can be inspected as a log, aggregated into metrics, and (in a later version) viewed in OTel-compatible trace tools.

**P2. Stops due to material starvation.** By default, material is replenished reactively, after a buffer empties, so stations stop and humans expedite. The simulation models replenishment policies that project per-part depletion at each line-side buffer from live inventory and consumption rate and dispatch AMR transport tasks predictively, so material arrives before depletion.

**P3. Which job runs on which cell.** With several cells capable of the same job at different speeds and distances, the order and placement of jobs determines total lateness. The simulation compares FIFO placement with a deadline-aware heuristic.

## 7. Problems deferred to later phases

- **Learned optimization (RL-assisted dispatch and scheduling).** V2's FIFO/EDD and threshold/predictive policies are the heuristic baselines.
- **Predictive maintenance, quality, and yield analytics.**
- **Changeover time and changeover optimization**, including preemption: deciding when interrupting a running job is worth the sequence-dependent setup cost.
- **Job splitting** across multiple cells.
- **Live visualization** of the simulation as it runs (V3).
- **Real OTLP export** to a collector and trace viewer (V3).

## 8. Value proposition

For the manufacturing customer: fewer line stops, higher OEE, and less manual coordination on high-mix back-end and FATP lines, without ripping out MES or ERP and without re-programming cells. For the automation platform: the missing line-level and factory-level layer that turns a collection of in-cell-planner cells into a coordinated, observable production line, plus the shared data foundation that every later orchestration, optimization, and analytics capability depends on. We connect the islands of automation into a line that can see itself and does not starve.

## 9. Solution overview and architecture

The product is a layer at ISA-95 Levels 3 to 4 with two faces built on one data foundation:

- **The live cell model (observability core):** a normalized representation of cells, stations, line-side buffers, output buffers, AMRs, jobs, and the central parts store, with every state transition emitted as an event.
- **The orchestration engine (bounded):** reads the job list, assigns jobs to cells under a scheduling policy, decides when each station requests material under a replenishment policy, and dispatches AMR transport tasks to keep cells fed and to return finished product to the store.

## 10. Functional requirements and priorities

*Priorities follow MoSCoW: P0 must-have (V2 does not ship without it), P1 should-have (after P0 is deployed), P2 future (design for, do not build now).*

**P0 claims — each is demonstrated by a scenario pair and asserted by an automated test (Section 16):**

- **P0-A** Adding cells reduces makespan via parallelization.
- **P0-B** Adding AMRs reduces makespan by reducing station starvation.
- **P0-C** Predictive replenishment (`PredictedOut`) produces fewer starvation ticks and lower makespan than reactive threshold replenishment (`UnitsLeft,0`) when AMR lead time is long relative to consumption.
- **P0-D** Deadline-aware scheduling (`EDD`) produces lower total lateness than `FIFO` when job order in the file does not match deadline order.

**P0 features:**

- Multi-cell, multi-job engine with pipelined serial flow per cell (Section 12)
- External parts only (central store has infinite supply of every part in `[PARTS]`)
- AMR fleet with typed capacity, speed, and cost; one part type and one destination per trip
- Scheduling policies `FIFO` and `EDD`; replenishment policies `UnitsLeft`, `PercentLeft`, `PredictedOut`
- OpenTelemetry-shaped JSONL event log (Section 12.7)
- Per-run results page with metrics (Section 12.8) and event log
- Section-based CSV input, downloadable template, Help page
- Landing page at `/`; V1 at `/v1`; V2 at `/v2`
- Scenario files and P0 claim tests

**P1 (in this order):**

- **P1-1 Jobs-late count** metric and per-job late flag on the results page.
- **P1-2 Intermediate parts.** A job's product may be consumed as a part by other jobs. A job whose steps reference an intermediate part becomes schedulable only after every job producing that part has completed (all units delivered to the store). The store tracks a finite count of each intermediate part; external parts remain infinite.
- **P1-3 Cross-run comparison page** (`/v2/compare`): select any subset of completed runs with checkboxes, show a side-by-side table of the Section 12.8 summary metrics. Bar charts (Chart.js from CDN) only after the table works.
- **P1-4 AMR trip batching.** One trip may serve several pending requests for the same cell, up to capacity, if they are for the same part; then for different parts (multi-compartment) — only if P1-1 through P1-3 are done.

**P2 (do not build; keep the design open):**

- Preemption: interrupting a job in progress for a higher-priority job, including returning unused parts to the store. The `job_interrupted` event name is reserved.
- Job splitting across cells.
- Intermediate-part flow at unit granularity: a dependent job becomes schedulable as soon as one unit of the intermediate part is in the store; stations can starve on upstream supply.
- Per-station line-side buffer size overrides (P0 uses one size per cell).
- Changeover time between jobs on a cell.
- Real OTLP export to an OpenTelemetry collector and trace viewer (V3).
- Live tick-by-tick visualization (V3).

## 11. Term definitions

**Tick.** The atomic unit of simulation time. Tick 0 is the first. One tick = one second of simulated time regardless of wall-clock runtime. Each tick, every entity is evaluated once in the order given in Section 12.6.

**Central Parts Store (store).** The single location AMRs travel to and from. Holds infinite quantities of every external part. Receives finished product. In P1, also holds finite counts of intermediate parts.

**Part.** A named material consumed by a station. **External parts** are listed in `[PARTS]` and are infinitely available at the store. **Intermediate parts** (P1) are the products of other jobs.

**Product.** The named output of a job. One unit of product per unit of the job. All parts and products are the same physical size (one AMR slot each).

**Cell.** A group of `num_stations` stations in a fixed serial order, with one line-side buffer per station and one output buffer. A cell executes at most one job at a time. Cells differ by distance from the store, `speed_factor`, station count, and buffer sizes.

**Station.** Fixed automation within a cell, named `<cell_name><n>` with `n` from 1. A station performs one step of a job on one unit at a time. It consumes at most one part type; it may consume N units of that part per product unit. Stations not used by the current job stay Idle.

**Line-side buffer.** Per-station storage for that station's part. Capacity `lineside_buffer_size` (one value per cell in P0). AMRs deliver into it; the station consumes from it.

**Output buffer.** Per-cell storage for finished product. Capacity `output_buffer_size`. The last used station places completed units into it; AMRs pick up from it.

**Job.** A named request to produce `units` of a product, arriving at `arrival_tick`, due by `deadline_tick`, executable on one of `capable_cells`, with an ordered list of steps.

**Step.** One row of `[JOB_STEPS]`: at station `station_number`, consume `parts_per_unit` of `part_name`, taking `ticks` ticks per unit (before `speed_factor`).

**Effective ticks.** `ceil(step.ticks × cell.speed_factor)`. The time a step takes on a specific cell.

**Cell cycle ticks (bottleneck).** `max(effective ticks over the job's steps on that cell)`. In steady state the cell completes one unit every cycle.

**Unit.** One product unit moving through a cell's stations. Units are numbered from 1 within each job.

**AMR.** An autonomous mobile robot of a given AMR type, named `<type_name><n>`. Carries up to `units_carried` parts or products at `speed_m_per_s`. Since one tick is one second, `speed_m_per_s` is also meters per tick. Costs `cost_dollars`.

**Trip.** One AMR round trip: store → cell (one-way ticks) → store (one-way ticks). One-way ticks = `ceil(cell.distance_meters / amr.speed_m_per_s)`. A delivery trip carries one part type to one station. A pickup trip collects product from one cell's output buffer. Loading and unloading take zero ticks.

**Transport request.** A queued need for a trip: either `(station, part, delivery)` or `(cell, pickup)`. Requests wait in a FIFO queue until an AMR is idle.

**Lead time.** Round-trip ticks for the *slowest* AMR type in the fleet to the requesting cell: `2 × ceil(distance / min_speed)`. A conservative estimate used by `PredictedOut`; queueing for a free AMR is not included and is what `safety_margin` covers.

**Makespan.** The tick at which the simulation ends: all jobs complete and all product delivered and all AMRs idle, or `max_ticks`.

**Lateness.** Per job: `max(0, completion_tick − deadline_tick)`, where `completion_tick` is the tick the job's last unit is delivered to the store. A job unfinished at `max_ticks` has lateness `max(0, max_ticks − deadline_tick)` and is flagged `unfinished`. **Total lateness** = sum over jobs.

**Station states.** `Idle` (no unit present), `Working` (performing its step on a unit; counts down effective ticks), `Holding` (step done, unit waiting for the next station or output buffer), `Starving` (a unit is ready to start here but the line-side buffer has fewer than `parts_per_unit` parts).

**Cell states.** `Idle` (no job assigned), `Setup` (job assigned, waiting for every used station's buffer to hold at least `parts_per_unit`), `Running` (at least one station Working), `Blocked` (job assigned, not complete at the cell, zero stations Working; `reason` is `output_full` if the last used station is Holding and the output buffer is full, else `starved`), `Draining` (all units are in or past the output buffer; waiting for AMR pickups to empty it before the cell can take a new job).

**AMR states.** `Idle` (at the store, available), `Outbound` (traveling to a cell), `Inbound` (returning to the store).

## 12. Technical specification

### 12.1 Input file format (section-based CSV)

Same style as V1: a section header in column A, then data rows. Blank lines are ignored. Lines beginning with `#` are comments. Section order is fixed as shown. Field names in the header row of each section are required and are validated. The parser produces a `SimConfigV2` dataclass and rejects the file with a human-readable error message (section, line number, problem) on any violation.

```
[SIMULATION]
name,<string>
description,<string>
max_ticks,<integer>
scheduling_policy,<FIFO | EDD>
replenishment_policy,<UnitsLeft,<int> | PercentLeft,<int> | PredictedOut,<int>>

[AMR_TYPES]
type_name,units_carried,speed_m_per_s,cost_dollars
<string>,<integer>,<float>,<integer>
...one row per AMR type...

[AMRS]
type_name,count
<string>,<integer>
...one row per AMR type in use...

[CELLS]
cell_name,distance_meters,speed_factor,num_stations,lineside_buffer_size,output_buffer_size
<string>,<integer>,<float>,<integer>,<integer>,<integer>
...one row per cell...

[PARTS]
part_name
<string>
...one row per external part...

[JOBS]
job_name,product_name,units,arrival_tick,deadline_tick,capable_cells
<string>,<string>,<integer>,<integer>,<integer>,<cell_name|cell_name|...>
...one row per job, in file order (FIFO order)...

[JOB_STEPS]
job_name,station_number,part_name,parts_per_unit,ticks
<string>,<integer>,<string>,<integer>,<integer>
...one row per (job, station); rows for a job must be contiguous and in ascending station_number...
```

**Field notes**

- `replenishment_policy` is a single CSV row with two data fields: policy name and value. `UnitsLeft,2` requests when `units_remaining <= 2`. `PercentLeft,25` requests when `units_remaining <= floor(0.25 × lineside_buffer_size)`. `PredictedOut,10` uses the predictive rule (12.3) with `safety_margin = 10` ticks. `UnitsLeft,0` is the fully reactive baseline.
- `speed_m_per_s` is also meters per tick (one tick = one second).
- `speed_factor` ≥ 0.1. `1.0` means the cell runs steps at the ticks listed in `[JOB_STEPS]`; `1.4` means 40% slower.
- `capable_cells` uses `|` as the separator so the row stays valid CSV without quoting.
- `arrival_tick` defaults to `0` if blank. `deadline_tick` is required.
- `station_number` values for a job must be `1..k` contiguous with `k <= num_stations` of every capable cell. The job uses stations 1..k on whichever cell it runs; stations k+1..n stay Idle.
- Every `part_name` in `[JOB_STEPS]` must appear in `[PARTS]` (P0). In P1, it may instead be the `product_name` of another job.
- `product_name` must be unique across jobs, and must not collide with a `[PARTS]` name.
- `parts_per_unit <= lineside_buffer_size` for every capable cell, otherwise the step could never start.
- `target_ticks` from V1 is intentionally absent; V2 has no robot-to-station assignment.

### 12.2 Scheduling policies

Scheduling runs every tick (Step 4 of the tick loop) but only does work when there is at least one Idle cell and at least one pending job. A job is **pending** if `arrival_tick <= tick`, it is not assigned, and (P1) all its intermediate-part dependencies are satisfied. A job is **placeable** on a cell if the cell is Idle and is in the job's `capable_cells`.

**FIFO.** Iterate pending jobs in file order. For each, assign it to the first placeable cell in `[CELLS]` file order. A job with no placeable cell is skipped this tick (no head-of-line blocking) and reconsidered next tick.

**EDD (earliest deadline, earliest estimated completion).** Iterate pending jobs sorted by `(deadline_tick, file order)`. For each, choose among placeable cells the one with the lowest `estimated_completion`, tiebreak by `[CELLS]` file order:

```
one_way(cell)             = ceil(cell.distance / min AMR speed in fleet)
setup_estimate(cell)      = 2 * one_way(cell)                     # one delivery lead time
pipeline_fill(job, cell)  = sum(effective_ticks(step, cell) for step in job.steps)
cycle(job, cell)          = max(effective_ticks(step, cell) for step in job.steps)
estimated_completion      = tick + setup_estimate + pipeline_fill + (job.units - 1) * cycle + 2 * one_way(cell)
```

The trailing `2 × one_way` is the final product pickup. This is a transparent greedy heuristic, deliberately not optimal; P2 and the deferred RL work exist to beat it. Neither policy holds a job back to wait for a better cell.

On assignment (both policies): cell state = `Setup`; log `job_assigned`; create one delivery request per step for `(station, part)` and enqueue in ascending station order.

### 12.3 Replenishment policies

Evaluated every tick for every station that has an assigned job and is used by that job (Step 5). A station never has more than one request outstanding: if a request for this station is queued or an AMR is Outbound to it, skip. A station requests only if it still needs parts:

```
consumed_so_far    = units_started_at_station * parts_per_unit
still_needed       = job.units * parts_per_unit - consumed_so_far - units_remaining
if still_needed <= 0: do not request
```

Then apply the policy:

- **UnitsLeft,v:** request if `units_remaining <= v`.
- **PercentLeft,p:** request if `units_remaining <= floor(p / 100 × lineside_buffer_size)`.
- **PredictedOut,m:** request if `units_remaining <= ceil(parts_per_unit × lead_time / cycle) + m`, where `cycle = cell cycle ticks` for the current job on this cell and `lead_time = 2 × ceil(cell.distance / min AMR speed in fleet)`.

Initial setup requests (issued at assignment) are not subject to the policy; they are always issued.

### 12.4 AMR dispatch and trips

Pending transport requests sit in one global FIFO queue. Each tick (Step 7), while the queue is non-empty and an Idle AMR exists: pop the head request, select the Idle AMR that appears first in `[AMRS]` order, tiebreak by name (alphabetical then numeric suffix), and start a trip.

**Delivery trip** `(station, part)`: AMR loads `units_carried` of the part at the store (instant), state = `Outbound`, `remaining = one_way`. On arrival: deliver `min(units_carried, lineside_buffer_size − units_remaining)` into the buffer; log `parts_delivered`; state = `Inbound`, `remaining = one_way`. Any undelivered surplus is assumed returned to the store (no accounting needed for external parts). On return: state = `Idle`; log `amr_returned`.

**Pickup trip** `(cell)`: state = `Outbound`, `remaining = one_way`. On arrival: take `min(units_carried, output_buffer_count)` from the output buffer; log `product_picked_up`; `Inbound`. On return: add product to the store; log `product_delivered_to_store`; if this delivers the job's last unit: log `job_complete`, record `completion_tick`; state = `Idle`.

**Pickup request rule** (Step 6): a cell requests pickup when `output_buffer_count >= output_buffer_size` OR (the cell's last used station has produced the job's final unit into the output buffer AND `output_buffer_count > 0`). A cell never has more than one pickup request outstanding (queued or in flight). If the buffer still holds product after a pickup, the rule fires again next tick.

**Busy accounting:** an AMR is busy from dispatch until it returns to the store (`2 × one_way` ticks). The trip counts as one trip.

### 12.5 Cell processing (pipelined serial flow)

Within a cell running job J with steps 1..k, units flow station 1 → 2 → … → k → output buffer. Station i can work on unit u while station i+1 works on unit u−1. A unit occupies exactly one station at a time. Per tick, stations are evaluated **from k down to 1** so that a unit moves at most one station per tick and downstream space frees before upstream tries to move.

For each station s (from k to 1):

1. If `Working`: `remaining -= 1`. If `remaining == 0`: state = `Holding`.
2. If `Holding`:
   - If s == k: if `output_buffer_count < output_buffer_size`: move unit to output buffer, `output_buffer_count += 1`, log `unit_complete` with `cycle_ticks = tick − unit.entry_tick`, state = `Idle`. Else stay Holding (this is the `output_full` block).
   - If s < k: if station s+1 is `Idle`: hand the unit to s+1 and immediately apply rule 3 to s+1; this station's state = `Idle`.
3. **Start rule.** When a station receives a unit (from the previous station, or created at station 1), or is `Starving` and is being re-evaluated: if `units_remaining >= parts_per_unit`: consume `parts_per_unit`, `units_started_at_station += 1`, state = `Working`, `remaining = effective_ticks`. If the station was Starving, log `station_starving_end`. Otherwise: if not already Starving, state = `Starving`, log `station_starving`.
4. Station 1 only, when `Idle` and `units_started_at_station < job.units`: create the next unit (`unit_id`, `entry_tick = tick`) and apply rule 3.

Timing notes: a received unit starts its step on the same tick it arrives, and the countdown begins on the next tick, so a step of T effective ticks occupies the station for T ticks after arrival. Because s+1 was already evaluated earlier in this tick (it was Idle), applying rule 3 to it on hand-off does not double-process it; the unit cannot advance two stations in one tick because `ticks >= 1`. Consume parts at the start of a step, not the end.

**Cell state transitions** (evaluated once per tick after station processing):

- `Setup` → `Running` when every used station has `units_remaining >= parts_per_unit`. Log `job_begin`. Station 1 creates its first unit on the next tick's Step 8.
- `Running` → `Blocked` when zero stations are `Working` and the final unit has not yet entered the output buffer. Log `cell_blocked` with `reason`. (With the immediate-start rule, zero Working stations can only mean a station is Starving or the last station is Holding against a full output buffer, so `reason` is always well defined.)
- `Blocked` → `Running` when any station is `Working`. Log `cell_blocked_end`.
- `Running`/`Blocked` → `Draining` when the final unit has entered the output buffer. Log `job_complete_at_cell`. Any remaining line-side parts are discarded (P2 would return them to the store).
- `Draining` → `Idle` when `output_buffer_count == 0` (the last pickup has left). The cell is then schedulable in the next tick's Step 4. Draining exists so that two jobs' product never share an output buffer.

### 12.6 Tick loop

```
Initialize:
  tick = 0; store product counts = {}; request_queue = []
  all cells Idle, all stations Idle with units_remaining = 0, all AMRs Idle
  log simulation_start (config summary)

Each tick:
  STEP 1  Termination
          if all jobs have completion_tick set AND all AMRs Idle: log simulation_end(reason=all_jobs_complete); stop
          if tick >= max_ticks: log simulation_end(reason=max_ticks_reached); stop
  STEP 2  Advance AMRs (Section 12.4): decrement remaining; handle arrival and return events
  STEP 3  Job arrivals: for each job with arrival_tick == tick: log job_arrived
  STEP 4  Scheduling (Section 12.2): assign pending jobs to Idle cells; enqueue setup requests
  STEP 5  Replenishment (Section 12.3): for each used station, maybe enqueue a delivery request (log part_request)
  STEP 6  Pickup requests (Section 12.4 rule): maybe enqueue a pickup request (log pickup_request)
  STEP 7  Dispatch (Section 12.4): assign Idle AMRs to queued requests in FIFO order (log amr_dispatched)
  STEP 8  Cell processing (Section 12.5) for every cell in Running/Blocked (Setup and Draining cells have no unit movement)
  STEP 9  Cell state transitions (Section 12.5) and per-tick accounting (utilization counters; setup, starvation, blocked, draining tick counters)
  STEP 10 tick += 1
```

Order matters and is fixed. Iterate cells in `[CELLS]` order, AMRs in `[AMRS]` order, jobs in `[JOBS]` order.

### 12.7 Event log (OpenTelemetry-shaped JSONL)

All events are written to `/data/runs_v2/<run_id>/run_log.jsonl`, one JSON object per line. Each record follows the OpenTelemetry Logs data model field names so it can later be shipped through an OTLP file receiver without transformation. Real OTLP export is V3; V2 writes the file only.

```json
{"timestamp": "2026-08-26T18:00:42Z", "observed_timestamp": "2026-08-26T18:00:42Z",
 "severity_text": "INFO", "body": "station_starving",
 "trace_id": "5c1e9b0b6d1f4a1b9c3d2e1f0a9b8c7d", "span_id": "1a2b3c4d5e6f7081",
 "resource": {"service.name": "backend-sim-v2", "run.id": "20260826_180000_ab12cd"},
 "attributes": {"tick": 42, "event": "station_starving", "cell": "CellA", "station": "CellA3",
                "job": "Harness-100", "part": "connector", "units_remaining": 0, "unit_id": 7}}
```

- `timestamp` = run start time (UTC, from `meta.json`) + `tick` seconds. `tick` is always also present in `attributes`.
- `severity_text` is `INFO` for normal events, `WARN` for `station_starving`, `cell_blocked`, and `job_complete` when late, `ERROR` for `simulation_end` with `max_ticks_reached`.
- **Trace = job.** `trace_id` is the first 32 hex chars of `sha256(run_id + ":" + job_name)`. Simulation-level events use `sha256(run_id + ":simulation")`.
- **Spans.** `span_id` is the first 16 hex chars of `sha256(trace_id + ":" + span_name)`. Span names: `job:<job_name>` (arrival → completion), `cell:<job_name>@<cell_name>` (assignment → complete at cell), `trip:<amr_name>#<trip_number>` (dispatch → return; carries the trace_id of the job it serves). Every event carries the innermost span it belongs to. `span_start`/`span_end` are encoded by the events that open and close each span; no separate span file is needed in V2.
- `attributes.event` is the stable discriminator; analytics keys on it, never on `body`.

**Event catalog** (attributes beyond `tick` and `event`):

| event | attributes | when |
|---|---|---|
| `simulation_start` | `name`, `scheduling_policy`, `replenishment_policy`, `cells`, `amrs`, `jobs` (counts) | tick 0 |
| `job_arrived` | `job`, `deadline_tick`, `units` | arrival_tick |
| `job_assigned` | `job`, `cell`, `policy`, `estimated_completion` (EDD only) | scheduling |
| `part_request` | `job`, `cell`, `station`, `part`, `units_remaining`, `kind` (`setup`/`policy`) | replenishment or setup |
| `pickup_request` | `job`, `cell`, `output_buffer_count` | pickup rule |
| `amr_dispatched` | `amr`, `amr_type`, `trip_kind` (`delivery`/`pickup`), `cell`, `station`?, `part`?, `qty`, `one_way_ticks` | dispatch |
| `parts_delivered` | `amr`, `cell`, `station`, `part`, `qty_delivered`, `units_remaining` (after) | arrival |
| `product_picked_up` | `amr`, `cell`, `qty`, `output_buffer_count` (after) | arrival |
| `amr_returned` | `amr`, `trip_kind` | return (delivery) |
| `product_delivered_to_store` | `amr`, `job`, `product`, `qty`, `store_count` | return (pickup) |
| `job_begin` | `job`, `cell`, `setup_ticks` | Setup → Running |
| `station_starving` | `job`, `cell`, `station`, `part`, `units_remaining`, `unit_id` | station enters Starving |
| `station_starving_end` | same + `starved_ticks` | station leaves Starving |
| `cell_blocked` | `job`, `cell`, `reason` | Running → Blocked |
| `cell_blocked_end` | `job`, `cell`, `reason`, `blocked_ticks` | Blocked → Running |
| `unit_complete` | `job`, `cell`, `unit_id`, `cycle_ticks` | unit enters output buffer |
| `job_complete_at_cell` | `job`, `cell`, `units`, `cell_ticks` (assignment → now) | final unit into output buffer |
| `job_complete` | `job`, `completion_tick`, `deadline_tick`, `lateness` | last product unit reaches store |
| `job_interrupted` | reserved (P2) | never emitted in V2 |
| `simulation_end` | `reason`, `makespan`, `total_lateness`, `unfinished_jobs` | termination |

### 12.8 Metrics

Computed from the log after the run and written to `results.json`; the headline values are also copied into `meta.json` so the home page and the P1 comparison page never re-parse logs.

**Run summary**

- **Makespan** (ticks): tick of `simulation_end`.
- **Total lateness** (ticks): Σ over jobs of lateness (Section 11). Jobs unfinished at `max_ticks` are included and flagged.
- **Total starvation ticks:** Σ over stations of ticks spent in `Starving`.
- **Total blocked ticks:** Σ over cells of ticks spent in `Blocked`, split by `reason` (`starved`, `output_full`).
- **Total setup ticks:** Σ over cells of ticks spent in `Setup`.
- **Total draining ticks:** Σ over cells of ticks spent in `Draining`.
- **AMR trips:** count of `amr_dispatched`, split by `delivery` / `pickup`.
- **Fleet cost** (dollars): Σ over AMRs of `cost_dollars`.
- **Jobs late** (P1): count of jobs with lateness > 0; **jobs unfinished:** count flagged.

**Per job:** cell, arrival, assigned, begin, complete-at-cell, completion tick, deadline, lateness, average unit cycle ticks, flags.

**Utilization** (all over makespan):

- **Station utilization:** `working_ticks / makespan × 100` for each station used by any job; **average** across used stations.
- **Cell utilization:** `running_ticks / makespan × 100` for each cell that ran a job (ticks in `Running`); **average** across cells that ran a job.
- **AMR utilization:** `busy_ticks / makespan × 100` for each AMR; **average** across all AMRs.

Display all as clean HTML tables. Per-job and per-station tables are sorted in file order.

## 13. Simulation limits

These protect the server from runaway simulations. The CSV parser rejects configurations that exceed them with a message naming the limit.

| Limit | Value |
|---|---|
| CSV file size | 50 KB |
| `max_ticks` | 50,000 |
| Cells | 10 |
| Stations per cell | 10 |
| AMR types | 10 |
| AMRs per type | 20 |
| Jobs | 20 |
| Units per job | 1,000 |
| Steps per job | 10 (bounded by stations per cell) |
| Simulation runs (demo account) | 5 per hour; 50 stored V2 runs across all demo users combined |

If V1 already enforces run-rate and storage limits, reuse that code. If not, implement simply: count `meta.json` files under `/data/runs_v2/` for the storage cap, and count runs started in the last 3600 seconds by the demo user for the rate cap; reject the upload with a clear message.

## 14. Web application

### 14.1 Authentication and roles

Unchanged from V1: HTTP Basic Auth on all routes, credentials from `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `DEMO_USERNAME`, `DEMO_PASSWORD`. Admin is the only role that sees the delete icon. V2 reuses the V1 auth decorator.

### 14.2 Routes

```
GET  /                              Landing page: links to V1 and V2 (V2 link shown only when V2_PUBLIC=true)

GET  /v1/...                        All existing V1 routes, unchanged except for the /v1 prefix (Flask Blueprint)

GET  /v2/                           V2 home: past V2 runs list + upload form + links to template, help, scenarios
GET  /v2/help                       Help page: CSV format, policies, metrics, how to run
GET  /v2/download/template/csv      Download sample_config_v2.csv
GET  /v2/download/scenario/<name>   Download a bundled scenario CSV (names from Section 16)
POST /v2/run/new                    Upload CSV, validate, run, redirect to results
GET  /v2/run/<run_id>               Results page
GET  /v2/run/<run_id>/log           Download run_log.jsonl
GET  /v2/run/<run_id>/config        Download the CSV used for this run
DELETE /v2/run/<run_id>             Admin only
GET  /v2/compare?runs=<id>,<id>,... P1: cross-run comparison
```

`V2_PUBLIC` is an environment variable (default `false`). Until it is `true`, `/v2/` is reachable by URL for developer testing but not linked from `/`. Flip it once the definition of done passes.

Existing bookmarks to `/` (V1 home) will now land on the landing page; that is acceptable.

### 14.3 Landing page (`/`)

- Title: "Back-End Assembly Line Simulator"
- Two cards: **V1 — Single Line, Robot Assignment** (one paragraph, "Open V1" link to `/v1/`) and **V2 — Multi-Cell Orchestration & Replenishment** (one paragraph, "Open V2" link to `/v2/`, hidden unless `V2_PUBLIC=true`).
- One line noting the GitHub repository.

### 14.4 V2 home page (`/v2/`)

- Section "New Simulation Run": file input + "Run Simulation" button.
- Links: "Download CSV Template", "Help", and a list of the bundled scenario files with one-line descriptions and download links.
- Table of past V2 runs: Run Name + Description | Start Time | Policies (scheduling / replenishment) | Makespan | Total Lateness | Status. Sorted by start time descending; name bold, description truncated to ~120 characters. Admin sees the delete icon.

### 14.5 Results page (`/v2/run/<run_id>`)

Sections in order:

1. Run name, full description, timestamp, status badge (`complete` / `max_ticks_reached` / `error`)
2. Configuration: policies; AMR types table (type, capacity, speed, cost, count); cells table (name, distance, speed factor, stations, buffer sizes); jobs table (name, product, units, arrival, deadline, capable cells)
3. Run summary (Section 12.8 run summary as a two-column table)
4. Per-job table
5. Cell utilization table (with setup, blocked-by-reason, and draining ticks per cell)
6. Station utilization table (with starvation ticks per station)
7. AMR utilization table (with trips per AMR)
8. Event log: scrollable table — Tick | Event | Job | Cell | Station | AMR | Part | Qty | Detail — rendered from `attributes`. Cap the rendered rows at 5,000 with a note and the download link if longer.
9. Links: Download Event Log, Download CSV, Back to V2 home

No visualization in V2. (V1's static end-state diagram does not carry over; a live visualization is V3.)

### 14.6 Help page (`/v2/help`)

One page, plain HTML: the CSV schema from Section 12.1 with field notes, the three replenishment policies and two scheduling policies in one paragraph each, the metric definitions from Section 12.8, the limits table, and the scenario list with what each pair demonstrates.

### 14.7 Run storage

```
/data/runs_v2/<run_id>/     (run_id = YYYYMMDD_HHMMSS_<6-char random>, same scheme as V1)
  config.csv
  run_log.jsonl
  results.json           (all Section 12.8 metrics)
  meta.json              (name, description, start_time, status, scheduling_policy,
                          replenishment_policy, makespan, total_lateness,
                          total_starvation_ticks, total_blocked_ticks, amr_trips, fleet_cost)
```

V2 runs never appear in the V1 list and vice versa.

## 15. File structure

```
back-end-simulation/
  app.py                        # Creates the Flask app; registers v1 and v2 blueprints; landing route
  simulation/                   # V1 engine — FROZEN, do not modify
  simulation_v2/
    __init__.py
    __main__.py                 # CLI: python -m simulation_v2 <config.csv> --out <dir>  (prints summary)
    config.py                   # SimConfigV2 dataclasses
    csv_parser.py               # Section-based parser + validation + limits
    entities.py                 # Cell, Station, AMR, Job, Unit, TransportRequest
    scheduling.py               # FIFO, EDD
    replenishment.py            # UnitsLeft, PercentLeft, PredictedOut
    engine.py                   # Tick loop (Section 12.6)
    otel_logger.py              # OTel-shaped JSONL writer, trace/span id derivation
    analytics.py                # results.json from run_log.jsonl
  web/
    v1.py                       # Blueprint wrapping the existing V1 routes (url_prefix="/v1")
    v2.py                       # Blueprint for V2 routes (url_prefix="/v2")
    auth.py                     # Shared Basic Auth (moved from app.py if needed; behavior unchanged)
  templates/
    landing.html
    v1/...                      # existing V1 templates, moved; url_for updated for the blueprint
    v2/base.html, index.html, results.html, help.html, compare.html (P1)
  static/
    style.css                   # shared
    v2/sample_config_v2.csv
    v2/scenarios/               # Section 16 files
  tests/
    test_csv_parser_v2.py
    test_replenishment.py       # policy rules against hand-computed cases
    test_scheduling.py          # FIFO and EDD placement against hand-computed cases
    test_engine_smoke.py        # sample config runs to completion; log is deterministic across two runs
    test_p0_claims.py           # Section 16 assertions
  docs/
    DECISIONS.md                # one line per DECISION: comment
    PRD_V2.md                   # this document
  data/runs/                    # V1 runs (gitignored)
  data/runs_v2/                 # V2 runs (gitignored)
  deploy/                       # unchanged; add update.sh (Section 18)
  requirements.txt              # flask gunicorn python-dotenv pytest
```

If V1's routes are currently defined directly on `app` in `app.py`, moving them into a Blueprint is the one permitted refactor. Do it mechanically; do not touch the simulation logic they call.

## 16. Sample configuration and scenario files

All scenario files live in `static/v2/scenarios/`. Each tick = 1 second. Claude Code chooses concrete numbers so that every P0 assertion below holds with a clear margin (at least 10% for makespan and starvation claims; strictly lower for lateness), then records the actual measured values in `README.md` and in each file's `description`. The scenarios are also the interview demo, so descriptions should say what question each file answers.

### 16.1 `sample_config_v2.csv` (template; also "hello world")

Two cells (`CellA`, `CellB`), three stations each, one AMR type, two AMRs, three external parts, two jobs each with three steps, `FIFO`, `UnitsLeft,2`. Small enough to read the whole log (a few hundred ticks).

### 16.2 P0 claim pairs

| File | Demonstrates | Differs from its pair only by |
|---|---|---|
| `a1_one_cell.csv` / `a2_two_cells.csv` | **P0-A** adding a cell reduces makespan | second cell added; jobs list `CellA\|CellB` |
| `b1_one_amr.csv` / `b2_two_amrs.csv` | **P0-B** adding an AMR reduces starvation and makespan | `[AMRS]` count 1 → 2 |
| `c1_reactive.csv` / `c2_predictive.csv` | **P0-C** predictive replenishment beats reactive | `UnitsLeft,0` → `PredictedOut,5` |
| `d1_fifo.csv` / `d2_edd.csv` | **P0-D** EDD beats FIFO on total lateness | `FIFO` → `EDD` |

Design notes for Claude Code:

- **A:** three or four jobs of similar length, all capable on both cells; enough AMRs that starvation is not the bottleneck.
- **B:** one cell, five stations, long distance (e.g. 150 m at 1 m/s), small line-side buffers, so a single AMR cannot keep five stations fed. Two AMRs should roughly halve starvation.
- **C:** same as B with two AMRs, buffers sized so reactive replenishment always starves for one lead time per refill while predictive arrives just in time. Expect predictive to use the same or slightly more trips; report trips in both descriptions to show the tradeoff.
- **D:** two cells with different `speed_factor` and distance; four jobs listed in an order where the first job in the file has the latest deadline and is long, and a short job with a tight deadline appears last. FIFO should miss the tight deadline; EDD should not.

### 16.3 `tests/test_p0_claims.py`

Runs each pair headlessly through the engine and asserts:

```
A: makespan(a2) < makespan(a1)
B: total_starvation_ticks(b2) < total_starvation_ticks(b1) and makespan(b2) < makespan(b1)
C: total_starvation_ticks(c2) < total_starvation_ticks(c1) and makespan(c2) < makespan(c1)
D: total_lateness(d2) < total_lateness(d1)
```

These tests are the acceptance criteria for the engine. They must pass before any web work starts.

## 17. Definition of done for Wednesday

- [ ] `python -m simulation_v2 static/v2/sample_config_v2.csv --out /tmp/x` runs to completion and prints makespan, total lateness, starvation ticks, blocked ticks, trips
- [ ] `pytest` passes: parser, replenishment, scheduling, engine smoke (including determinism), and all four P0 claims
- [ ] Largest-allowed configuration finishes in under 60 seconds
- [ ] `/v2/` home page: upload sample config, run, results page shows all Section 14.5 sections with non-zero, plausible numbers
- [ ] Per-job lateness and total lateness are numerically consistent with the log
- [ ] Every event in Section 12.7 appears in the sample run's log with the listed attributes, and every record has `timestamp`, `trace_id`, `span_id`, `resource`, `attributes.tick`, `attributes.event`
- [ ] Help page and CSV template download work; all eight scenario files download and run from the UI
- [ ] Landing page at `/`; V1 fully working at `/v1/` (upload, run, results, delete) with no engine changes
- [ ] Demo credentials work; admin sees delete on both V1 and V2 runs
- [ ] Deployed on EC2 at https://backendsim.com with HTTPS; `V2_PUBLIC=true` set after the above pass
- [ ] `README.md` updated: V2 overview, CSV format, policies, scenario table with measured results, how to run tests, deploy/update steps
- [ ] `docs/DECISIONS.md` lists every `# DECISION:` made during the build

## 18. Deployment notes

Same EC2 instance, same nginx and systemd unit, same domain. V2 is new routes in the same gunicorn process. Add `deploy/update.sh`:

```
cd /home/ubuntu/back-end-simulation
git pull origin main
source venv/bin/activate && pip install -r requirements.txt
mkdir -p data/runs_v2
sudo systemctl restart back-end-simulation
```

Add `V2_PUBLIC=false` to `.env.example` and to the server's `.env`; set it to `true` after the definition of done passes. No nginx or DNS changes are required.

## 19. V3 (only if time remains after V2 is deployed and P1 is done)

V3 is V2 plus a live visualization: the simulation streams state per tick (WebSocket or server-sent events) to a page showing cells, stations, buffers, and AMRs moving between the store and cells. Also in V3: export the JSONL log through an OpenTelemetry collector file receiver to a trace viewer so the job → cell → trip span hierarchy can be browsed. Do not start V3 until Section 17 is fully checked and P1-1 through P1-3 are deployed.

---

## Appendix A. Changes from draft v0.4

- Deadline corrected to Wednesday, August 26, 2026; version set to 0.5; title and footer aligned.
- "Workspan" → "makespan"; "border-of-line" → "line-side"; "Open Telemetry" → "OpenTelemetry"; wording fixes.
- Cell processing defined as pipelined serial flow (as V1); stations are fixed automation with fixed ticks; no robot-to-station assignment; "Robot Types" → "AMR Types"; `target_ticks` dropped.
- Per-cell `speed_factor` added so cells differ in performance.
- `MinimizeTotalLateness` replaced by a defined heuristic, `EDD` (earliest deadline, earliest estimated completion).
- `PredictedOut` given a concrete formula with `safety_margin`; anti-duplicate request rule added.
- AMR dispatch, trip, delivery quantity, pickup trigger, and busy accounting defined.
- Intermediate parts moved to P1 with a completion-dependency rule; unit-granularity flow is P2. P0 is external parts only.
- Cell `Setup`/`Running`/`Blocked`/`Draining` states and blocked `reason` defined; station `Starving`/`Holding` states defined.
- Preemption (`job_interrupted`, part return) marked P2.
- Lateness and completion defined; unfinished jobs flagged.
- Metrics given formulas; added total starvation ticks, total blocked ticks, setup ticks, AMR trips, AMR utilization, fleet cost (P0) and jobs-late count (P1).
- Full section-based CSV schema added; one line-side buffer size per cell (per-station override is P2).
- OTel-shaped JSONL defined with trace = job and span = job / cell execution / AMR trip; real OTLP export deferred to V3.
- V1 moved to `/v1`, landing page at `/`, V2 at `/v2` behind `V2_PUBLIC`.
- Scenario pairs tied to the four P0 claims with an automated test; build order, time-boxes, file structure, definition of done, and deploy script added.
