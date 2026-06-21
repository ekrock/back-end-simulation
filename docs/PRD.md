# PRD: Back-End Assembly Line Simulator (v1-Simple — Weekend Build)

**Last Updated:** 2026-06-20 10:30 PM PT  
**Status:** Implemented — live at https://backendsim.com  
**GitHub repo:** `ekrock/back-end-simulation` (public)  
**Deadline:** EOD Saturday  
**Author:** Eric Krock  
**Purpose:** Open-source portfolio and reference implementation demonstrating robot
orchestration, tick-based discrete-event simulation, structured logging, and analytics
for a back-end electronics assembly line.

---

## Build Notes

- Build and verify locally first. Do not touch EC2 until the app runs end-to-end on localhost.
- Build in this order: (1) simulation engine, (2) Flask web layer, (3) EC2 deployment.
- Use Python 3.11+. Use Flask for the web layer. No external simulation libraries needed.
- Keep everything in one repo. Minimize dependencies.
- After each stage, confirm it works before moving to the next.
- If something is ambiguous, make a reasonable decision, implement it, leave a comment,
  and keep going. Do not stop to ask unless it is truly blocking.
- The simulation runs to completion server-side, then displays results. No WebSockets,
  no live tick-by-tick streaming.
- Phase 2 features are listed at the bottom. Do not implement them now.

---

## 1. Overview

A single-page web application that lets a user upload a CSV configuration file, run a
tick-based assembly line simulation, and view the results: a structured log, robot and
station utilization analytics, and a static visualization of the line's final state.

**The simulation demonstrates:**
- Tick-based discrete-event simulation of a robot-staffed back-end assembly line
- Simple threshold-based rules governing fetch and deliver robot behavior
- Robot assignment based on cost and Target Takt Time
- Structured activity logging
- Utilization analytics derived from log data

**Stack:**
- Backend: Python 3.11, Flask
- Simulation engine: pure Python, no external simulation libraries needed
- Frontend: single HTML template with inline CSS and vanilla JS (no frameworks)
- Storage: local filesystem (simulation runs stored as folders under `/data/runs/`)
- Auth: HTTP Basic Auth via environment variables
- Deployment: AWS EC2, Ubuntu 24.04, gunicorn behind nginx, HTTPS via Let's Encrypt
- Domain: **backendsim.com**

---

## 2. Term definitions

**Tick:** The atomic unit of simulation time. Tick 0 is the first. Each tick, every
station and robot is evaluated once in order.

**Job:** A named task with a specified number of parts to build on a given line. A job
is complete when all its parts have passed through all stations, reached the Output
Buffer, and been delivered back to Central Store.

**Part:** One unit of work. Each part flows left-to-right through all stations on the
line, from Input Buffer through assembly stations to Output Buffer.

**Line:** The assembly line. One line per simulation run in v1.

**Station:** A named step on the line. Every line has a fixed Input Buffer (first) and
Output Buffer (last), plus 1-N assembly stations in between.

**Action:** The task performed at a station (e.g., "insert cable into slot A"). Each
assembly station has exactly one required action.

**Robot:** An agent that performs actions at stations. Each robot has a type, a name, a
set of supported actions, ticks required per action, and a cost.

**Robot Type:** A class of robots sharing capabilities and costs. Individual robots are
named TypeName + integer starting at 1 (e.g., "Assembler1", "Assembler2").

**Idle state:** Robot is available for assignment.
**Working state:** Robot is assigned to a station or performing fetch/deliver and is
unavailable until required ticks have elapsed.

**Target Ticks (per Job):** The company's goal for how many ticks each part should take
to build. Analogous to Target Takt Time on an SMT line. Used to filter robot candidates
during assignment: a robot whose ticks_per_action exceeds this goal is deprioritized.

**Max Ticks (per Simulation):** The hard ceiling on simulation runtime. If the job is
not complete by this tick, the simulation stops with reason `max_ticks_reached`.

---

## 3. Simulation run configuration (CSV)

The user downloads a CSV template, fills it in, and uploads it. The CSV uses a
section-based format: a section header row in column A, followed by data rows.

**Claude Code: generate `static/sample_config.csv` pre-filled with a working example
the user can upload immediately to see a simulation run.**

### CSV sections and fields

```
[SIMULATION]
name,<string>
description,<string>
max_ticks,<integer>

[JOB]
name,<string>
parts_to_build,<integer>
target_ticks,<integer>

[LINE]
input_buffer_size,<integer>
output_buffer_size,<integer>
central_store_distance_meters,<integer>
fetch_trigger_threshold,<integer>
deliver_trigger_threshold,<integer>

[STATIONS]
station_name,action_name
<string>,<string>
...one row per assembly station, not including Input Buffer or Output Buffer...

[ROBOT_TYPES]
<type_name>,<speed_meters_per_tick>,<cost_dollars>
<action_name>,<ticks_per_action>[,<action_name>,<ticks_per_action>...]
...repeat the two-line block for each robot type...

[ROBOTS]
type_name,count
<string>,<integer>
...
```

### Field notes

**name (Simulation):** A short, concise identifier for this simulation run
(e.g. "Cable Harness Sim Run 1").

**description (Simulation):** A paragraph-length explanation of the run's purpose —
what configuration is being tested, what question it answers, or what scenario it
represents. Displayed alongside the name throughout the web app.

**max_ticks:** Hard ceiling on simulation runtime. The simulation stops at this tick if
the job is not yet complete.

**target_ticks (Job):** The company's goal for part cycle time in ticks. Used during
robot assignment (see Section 4). Does not stop the simulation.

**fetch_trigger_threshold:** The engine requests a fetch-capable robot for this line
whenever `input_buffer_count <= fetch_trigger_threshold`. For example, if set to 1,
fetch is requested whenever the input buffer has 1 or fewer parts remaining.

**deliver_trigger_threshold:** The engine requests a deliver-capable robot for this line
whenever `output_buffer_count >= deliver_trigger_threshold`. For example, if set to
output_buffer_size, deliver is requested only when the buffer is completely full.

**[ROBOT_TYPES] two-line format per robot type:**
- Line 1: `type_name,speed_meters_per_tick,cost_dollars`
  — `speed_meters_per_tick` is blank for robots that do not move (assemblers).
  — `cost_dollars` is an integer.
- Line 2: sequential action/ticks pairs — `action_name,ticks_per_action` repeated
  for every action this type supports, all on one comma-separated line.

**fetch parts / deliver parts:** Reserved action names. Robots listing them must have a
`speed_meters_per_tick` value on line 1. Duration is calculated as
`ceil(central_store_distance_meters / speed_meters_per_tick)`. Any `ticks_per_action`
value listed in the CSV for these two actions is ignored.

---

## 4. Robot assignment rule

When a station needs a robot the engine selects using this priority order:

1. Robot must be in Idle state.
2. Robot must support the required action.
3. Among eligible robots, select the cheapest (lowest `cost_dollars`) whose
   `ticks_per_action` for the station's action is strictly less than `target_ticks`
   for the Job.
   If no eligible robot meets the `target_ticks` constraint, fall back to the cheapest
   eligible robot regardless of `ticks_per_action` (log a `target_ticks_fallback` warning
   event at that tick).
4. Tiebreak: fewest ticks required for this action.
5. Second tiebreak: alphabetical by robot name.

---

## 5. Simulation execution

```
Initialize:
  All robots: state = Idle, remaining_ticks = 0, current_action = None
  All stations: state = Idle, part_present = False, locked = False
  Input Buffer: count = 0
  Output Buffer: count = 0
  parts_completed = 0
  tick = 0
  job_started = False
  next_part_id = 1
  entry_tick = {}  (dict mapping part_id -> tick when it entered first assembly station)

Each tick:

  STEP 1 — Check termination
    If parts_completed >= parts_to_build
       AND output_buffer_count == 0
       AND no deliver robot currently in Working state:
      log end_simulation(reason=job_complete), stop.
    If tick >= max_ticks: log end_simulation(reason=max_ticks_reached), stop.

  STEP 2 — Decrement working robots
    For each robot in Working state:
      remaining_ticks -= 1
      If remaining_ticks == 0:
        If current_action == "fetch parts":
          Input Buffer count = input_buffer_size  (fill to max)
          Robot state = Idle
          Log finish_action
        Else if current_action == "deliver parts":
          Robot state = Idle
          Log finish_action
          (Output Buffer was already set to 0 in Step 3 when the robot was assigned.
           Do NOT reset it here — in a multi-job scenario, a subsequent job may have
           already deposited parts into the Output Buffer during the delivery trip.)
        Else:  (assembly action)
          Station where robot was working: state = Idle, locked = False
          (part remains at station, available to move next tick)
          Robot state = Idle
          Log finish_action (include part_id)

  STEP 3 — Deliver check
    If output_buffer_count >= deliver_trigger_threshold
       OR (parts_completed >= parts_to_build AND output_buffer_count > 0):
      (The OR clause is an end-of-job override: when all parts are built but the final
       batch is smaller than deliver_trigger_threshold, dispatch immediately so the
       simulation can reach its job_complete termination condition.)
      If no deliver robot currently working for this line:
        Find available deliver-capable robot (assignment rule).
        If found:
          Log assign_robot
          Assign robot, state = Working, current_action = "deliver parts"
          remaining_ticks = ceil(central_store_distance / speed)
          Output Buffer count = 0  (robot has taken the parts)
          Log start_action

  STEP 4 — Fetch check
    If input_buffer_count <= fetch_trigger_threshold:
      If no fetch robot currently working for this line:
        Find available fetch-capable robot (assignment rule).
        If found:
          Log assign_robot
          Assign robot, state = Working, current_action = "fetch parts"
          remaining_ticks = ceil(central_store_distance / speed)
          Log start_action

  STEP 5 — Move completed parts to Output Buffer
    Last assembly station: if state = Idle and part_present = True and locked = False
    and output_buffer_count < output_buffer_size:
      output_buffer_count += 1
      cycle_time = tick - entry_tick[current_part_id]
      Log part_complete (include part_id, cycle_time_ticks = cycle_time)
      part_present = False
      parts_completed += 1
      If parts_completed == parts_to_build: log finish_job

  STEP 6 — Assign robots to assembly stations (reverse order, last to second)
    For each assembly station from last to second (station-to-station moves only;
    the first assembly station pulling from the Input Buffer is handled exclusively
    in Step 7):
      If state = Idle and no robot assigned:
        Check if the PREVIOUS assembly station has a completed part available
        (part_present = True, locked = False, state = Idle).
        If yes:
          Find available robot for this station's action (assignment rule).
          If found:
            Move part from previous station (part_present = False there,
              carry forward its part_id).
            Log assign_robot (include part_id)
            This station: part_present = True, locked = True, state = Working,
              current_part_id = carried part_id.
            Robot: state = Working, current_action = station action,
              remaining_ticks = robot's ticks for this action.
            Log start_action (include part_id)

  STEP 7 — Take part from Input Buffer into first assembly station
    First assembly station only: if state = Idle and no robot assigned
    and input_buffer_count >= 1:
      Find available robot for first station's action (assignment rule).
      If found:
        input_buffer_count -= 1
        part_id = next_part_id; next_part_id += 1
        entry_tick[part_id] = tick
        Log assign_robot (include part_id)
        First station: part_present = True, locked = True, state = Working,
          current_part_id = part_id.
        Robot: state = Working, current_action = first station's action,
          remaining_ticks = robot's ticks for this action.
        If not job_started: log start_job, job_started = True
        Log start_action (include part_id)

  STEP 8 — Increment tick
    tick += 1
```

---

## 6. Logging

All events written to `/data/runs/<run_id>/run_log.jsonl`. One JSON object per line.

**Part tracking:** each part that enters the first assembly station is assigned an
auto-incrementing `part_id` (integer, starting at 1 per job). All log events that
involve a specific part include the `part_id` field. The engine records each part's
`entry_tick` (the tick it entered the first assembly station) to enable per-part
cycle time calculation.

```json
{"event": "start_simulation", "tick": 0, "config": {}}
{"event": "start_job", "tick": 0, "line": 1, "job_name": "Cable Harness Assembly"}
{"event": "assign_robot", "tick": 0, "line": 1, "station": "Central Store",
  "robot": "FetchBot1", "action": "fetch parts", "cost_dollars": 50, "ticks_for_action": 5}
{"event": "start_action", "tick": 0, "line": 1, "station": "Central Store",
  "robot": "FetchBot1", "action": "fetch parts"}
{"event": "finish_action", "tick": 5, "line": 1, "station": "Central Store",
  "robot": "FetchBot1", "action": "fetch parts"}
{"event": "assign_robot", "tick": 6, "line": 1, "station": "Insert Cable Slot A",
  "robot": "Assembler1", "action": "insert_cable_slot_a", "cost_dollars": 30,
  "ticks_for_action": 5, "part_id": 1}
{"event": "start_action", "tick": 6, "line": 1, "station": "Insert Cable Slot A",
  "robot": "Assembler1", "action": "insert_cable_slot_a", "part_id": 1}
{"event": "finish_action", "tick": 11, "line": 1, "station": "Insert Cable Slot A",
  "robot": "Assembler1", "action": "insert_cable_slot_a", "part_id": 1}
{"event": "part_complete", "tick": 25, "line": 1, "part_id": 1,
  "cycle_time_ticks": 19}
{"event": "finish_job", "tick": 98, "line": 1, "job_name": "Cable Harness Assembly",
  "parts_completed": 10}
{"event": "end_simulation", "tick": 98, "reason": "job_complete"}
```

**Optional warning event (logged when no robot meets target_ticks):**
```json
{"event": "target_ticks_fallback", "tick": 6, "line": 1,
  "station": "Insert Cable Slot A", "action": "insert_cable_slot_a",
  "target_ticks": 13, "selected_robot": "Assembler1", "ticks_for_action": 15}
```

**Notes:**
- `assign_robot` is logged immediately before `start_action` whenever a robot is
  selected for any station or fetch/deliver task. It captures the assignment decision:
  which robot was chosen, its cost, and its ticks for the action.
- `part_complete` is logged when a part moves from the last assembly station into the
  Output Buffer. `cycle_time_ticks` = current tick minus the tick at which this part
  entered the first assembly station.
- Fetch/deliver actions do not carry a `part_id` since they are not associated with a
  specific part.
- The `Central Store` label is used in log events for fetch/deliver station references
  (replaces "Warehouse").

---

## 7. Analytics

Computed from the log after simulation ends. Displayed on the results page.

**Robot Utilization**
For each robot: `working_ticks / total_ticks * 100`
`working_ticks` = number of ticks the robot spent in Working state.

**Average Robot Utilization**
Mean of Robot Utilization across all robots in the simulation. Summarizes overall
robot fleet productivity in a single number.

**Station Utilization**
For each station: `working_ticks / total_ticks * 100`
`working_ticks` = number of ticks a robot was actively working at that station.

**Average Station Utilization**
Mean of Station Utilization across all assembly stations (excluding Input Buffer and
Output Buffer, which are storage, not processing stations). Summarizes overall line
throughput efficiency in a single number.

**Job Summary**

- **Parts Completed:** total parts that reached the Output Buffer.

- **Average Part Cycle Time (ticks):** Mean of `cycle_time_ticks` across all
  `part_complete` events. Measures only the time a part is actively in the production
  flow — from first touch at Station 1 to exit into the Output Buffer. Excludes any
  waiting time before a part enters the line.

- **Average Full Cycle Time (ticks):** `Average Part Cycle Time + avg fetch duration +
  avg deliver duration`, computed from actual log event timestamps. Represents the
  true end-to-end time per part including transport — the number a plant manager
  compares against a customer lead-time commitment.

- **Average Non-Value-Added Time (ticks):** `Average Full Cycle Time − Average Part
  Cycle Time`. The per-part transport and waiting time that consumed clock time without
  adding value. A key component of OEE Availability loss.

- **Target Ticks:** The job's configured goal, shown for reference alongside the
  measured averages.

- **Total Ticks Elapsed:** The tick at which the simulation ended.

Display all as clean HTML tables.

---

## 8. Visualization (static, shown after simulation completes)

```
[ CENTRAL STORE ]
       |
[ Input Buffer ] -- [ Station 1 ] -- [ Station 2 ] -- [ ... ] -- [ Output Buffer ]

Robots not at a station shown below the line in a row.
```

**Buffer colors:**
- Input Buffer: red if empty, yellow if 1-2 parts, green if >= 3 parts
- Output Buffer: red if full, yellow if 1-2 spaces remaining, green if >= 3 spaces remaining

**Robot boxes:**
- Each robot type has a distinct CSS border style (solid / dashed / dotted / double —
  one style per type, up to four types supported)
- Green if robot was in Working state at end of simulation; red if Idle
- Labeled with robot name

**Station boxes:**
- Green if a robot was working there at simulation end; red otherwise
- Show robot name inside box if one was assigned at end

**Parts:**
- Each station shows a small cable symbol (Unicode: ⊟ or similar) if a part is present
  at that station at end of simulation

---

## 9. Web application

### 9.1 Authentication

HTTP Basic Auth on all routes. Read credentials from environment variables:

```
ADMIN_USERNAME
ADMIN_PASSWORD
DEMO_USERNAME
DEMO_PASSWORD
```

Store in `.env` locally. Load with python-dotenv. The admin role is identified when the
authenticated username matches `ADMIN_USERNAME`.

**In v1, admin and demo users have identical capabilities except one: only the admin
user sees the 🗑 delete icon next to past runs.** All other features (upload, run,
view results, download CSV, download event log) are available to both roles. This
separation exists to support future permission differentiation without a code change.

### 9.2 Routes

```
GET  /                         Home page: past runs list + upload form
GET  /download/template/csv    Download sample_config.csv
POST /run/new                  Upload CSV, validate, run simulation, redirect to results
GET  /run/<run_id>             Results: visualization + analytics + log
GET  /run/<run_id>/log         Download run_log.jsonl for this run
DELETE /run/<run_id>           Admin only: delete run folder, called via JS fetch
```

### 9.3 Home page

- Title: "Back-End Assembly Line Simulator"
- Section: "New Simulation Run" with a single file input for CSV upload and a
  "Run Simulation" button
- Link: "Download CSV Template"
- Table of past runs: Run Name + Description | Start Time | Parts Completed | Total Ticks | Status
  Sorted by start time descending. Each row shows the run name in bold on the first
  line and the description in smaller text on the second line (truncated to ~120
  characters with ellipsis if longer; full text is shown on the results page).
- Admin users only: each run row includes a 🗑 icon on the right. Clicking it calls
  DELETE /run/<run_id> via fetch and removes that row from the DOM on success.
  The icon is not rendered at all for demo users.

### 9.4 Results page

Sections in order:
1. Run name, full description, timestamp, status badge
2. Configuration: Distance from Central Store, Robot Type Specifications table
   (type, cost/unit, speed, operations), Robot Fleet table (type, count)
3. Job summary (parts completed, avg part cycle time, avg full cycle time,
   avg non-value-added time, target ticks, total ticks)
4. Visualization grid
5. Robot utilization table
6. Station utilization table
7. Event log (scrollable table: Tick | Event | Station | Robot | Action | Part ID)
8. Link: Download Event Log (downloads run_log.jsonl)
9. Link: Download CSV used for this run
10. Link: Back to home

### 9.5 Run storage

```
/data/runs/<run_id>/     (run_id = YYYYMMDD_HHMMSS_<6-char random>)
  config.csv
  run_log.jsonl
  results.json           (pre-computed analytics)
  meta.json              (run name, description, start time, status, parts_completed, total_ticks)
```

---

## 10. Project Setup (Do This Before Claude Code Starts Building)

These are the one-time steps to create the GitHub repository and local project
directory. Claude Code will handle creating all project files once these are in place.

### 10.1 Create the GitHub repository

1. Go to **https://github.com/new**
2. Fill in:
   - Owner: `ekrock`
   - Repository name: `back-end-simulation`
   - Visibility: **Public**
   - Do NOT check "Add a README file", "Add .gitignore", or "Choose a license"
3. Click **Create repository**
4. GitHub will show you the empty repo page. Leave it open — you'll need the SSH URL.

### 10.2 Create the local project directory

On your Mac terminal (each command on its own line):

```
mkdir ~/back-end-simulation
cd ~/back-end-simulation
git init
git remote add origin git@github.com:ekrock/back-end-simulation.git
```

Verify SSH access to GitHub:
```
ssh -T git@github.com
```
Expected response: `Hi ekrock! You've successfully authenticated...`
If this fails, your SSH key is not added to GitHub — go to GitHub → Settings →
SSH and GPG keys → New SSH key and add `~/.ssh/id_rsa.pub` (or `id_ed25519.pub`).

### 10.3 What Claude Code will set up automatically

Once you give the go-ahead to build, Claude Code will:

- Create the full project file structure (see Section 12)
- Create `.claude/settings.json` with a read-only command allowlist to reduce permission prompts
- Create `~/.claude/projects/-Users-eric-back-end-simulation/memory/` and seed it
  with project-relevant memory entries (EC2 deploy mechanics, doc conventions, etc.)
- Create `.gitignore` covering `__pycache__/`, `*.pyc`, `.env`, `data/runs/`
- Make an initial commit and push to `ekrock/back-end-simulation`

---

## 11. AWS EC2 Deployment (Do These Steps While Claude Code Builds)

**Do the steps in this section in parallel while Claude Code is building the app.**
All of these require your manual action in the AWS Console and your domain registrar.
The domain `backendsim.com` is already registered — skip any "register domain" step.

### 11.1 Launch the EC2 instance

1. Sign in to the AWS Console: **https://console.aws.amazon.com**
2. In the top search bar, type **EC2** and click EC2 under Services.
3. Click **Launch instance** (orange button).
4. Under **Name and tags**, enter: `back-end-simulation`
5. Under **Application and OS Images**, click **Ubuntu**, then select:
   **Ubuntu Server 24.04 LTS (HVM), SSD Volume Type** — 64-bit (x86)
6. Under **Instance type**, select: **t3.small**
7. Under **Key pair (login)**, click **Create new key pair**:
   - Key pair name: `back-end-sim`
   - Key pair type: RSA
   - Private key file format: `.pem`
   - Click **Create key pair** — `back-end-sim.pem` downloads to your Downloads folder
8. Move and secure the key file (on your Mac terminal):
   ```
   mv ~/Downloads/back-end-sim.pem ~/.ssh/back-end-sim.pem
   chmod 400 ~/.ssh/back-end-sim.pem
   ```
9. Under **Network settings**, click **Edit**, then:
   - Auto-assign public IP: **Enable**
   - Click **Create security group**, name it `back-end-simulation-sg`
   - Rule 1 (already present): SSH — Port 22 — Source: **My IP**
   - Click **Add security group rule**:
     Type: HTTP — Port 80 — Source: **Anywhere (0.0.0.0/0)**
   - Click **Add security group rule**:
     Type: HTTPS — Port 443 — Source: **Anywhere (0.0.0.0/0)**
10. Under **Configure storage**, leave the default (8 GiB gp3).
11. Click **Launch instance**.
12. Click the instance ID link in the confirmation banner.
13. Wait until the **Instance state** column shows **Running** (usually 30–60 seconds).
14. In the instance details panel, copy and save the **Public IPv4 address**
    (looks like `54.xxx.xxx.xxx`). You will need it for the next two steps.

### 11.2 Configure SSH on your Mac

Open `~/.ssh/config` in any text editor and add these lines at the bottom
(replace `<EC2_PUBLIC_IP>` with the IP you copied in step 14):

```
Host back-end-sim-ec2
  HostName <EC2_PUBLIC_IP>
  User ubuntu
  IdentityFile ~/.ssh/back-end-sim.pem
```

Save the file, then test the connection:
```
ssh back-end-sim-ec2
```
You should see an Ubuntu welcome banner. Type `exit` to disconnect.

### 11.3 Point backendsim.com DNS to the EC2 instance

1. Log in to the registrar where you bought `backendsim.com`.
2. Navigate to DNS management for `backendsim.com`.
3. Add an **A record**:
   - Host / Name: `@`
   - Value / Points to: `<EC2_PUBLIC_IP>` (same IP from step 14)
   - TTL: `300`
4. Save the record.
5. Wait 5–15 minutes, then verify propagation on your Mac:
   ```
   dig backendsim.com +short
   ```
   This should return your EC2 IP address.

### 11.4 Deploy the application (after Claude Code finishes building)

Once the code is built and pushed to GitHub, SSH into the instance and run:

```
ssh back-end-sim-ec2
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ekrock/back-end-simulation/main/deploy/setup.sh)"
```

Then edit credentials:
```
nano /home/ubuntu/back-end-simulation/.env
```

Start the service:
```
sudo systemctl start back-end-simulation
```

Enable HTTPS:
```
bash /home/ubuntu/back-end-simulation/deploy/setup-https.sh backendsim.com
```

Verify: open **https://backendsim.com** in your browser.

### 11.5 nginx configs

**Claude Code must create two nginx config files:**

`deploy/nginx-http.conf` — used during initial setup before HTTPS:
```nginx
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

`deploy/nginx-https.conf` — reference only (Certbot generates the real one):
```nginx
server {
    listen 443 ssl;
    server_name backendsim.com;
    # SSL managed by Certbot
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
server {
    listen 80;
    server_name backendsim.com;
    return 301 https://$host$request_uri;
}
```

### 11.6 Other files Claude Code must create

`deploy/back-end-simulation.service`: systemd unit running gunicorn on 127.0.0.1:5000

`.env.example`:
```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
DEMO_USERNAME=demo
DEMO_PASSWORD=changeme
```

`README.md`: covers local run, project setup (Section 10), EC2 provisioning,
DNS setup, setup.sh, HTTPS setup, and how to use the app.

---

## 12. Sample configuration and scenario files

### 12.1 sample_config.csv

`static/sample_config.csv` — a three-station PCB assembly line with a single-AMR
bottleneck, pre-filled and ready to upload:

```
[SIMULATION]
name,PCB Assembly — Single AMR Baseline
description,Three-station PCB assembly line with two Stationary Assemblers and one
Dexterous Robotic Arm. A single AMR shuttles parts to and from Central Store 60 m
away (60 ticks at 1 m/s; each tick = 1 second). With buffer size 10 and the line
consuming one part every ~10 ticks, the AMR cannot fetch and deliver simultaneously
— the line stalls periodically. Vary the AMR count to 2 and compare throughput.
max_ticks,3000

[JOB]
name,PCB Assembly
parts_to_build,50
target_ticks,12

[LINE]
input_buffer_size,10
output_buffer_size,10
central_store_distance_meters,60
fetch_trigger_threshold,0
deliver_trigger_threshold,10

[STATIONS]
station_name,action_name
Component Placement,component_placement
Solder Reflow,solder_reflow
Quality Inspection,quality_inspection

[ROBOT_TYPES]
AMR,1.0,40000
fetch parts,60,deliver parts,60
Stationary Assembler,,25000
component_placement,10,solder_reflow,10,quality_inspection,15
Dexterous Robotic Arm,,80000
component_placement,7,solder_reflow,7,quality_inspection,9

[ROBOTS]
type_name,count
AMR,1
Stationary Assembler,2
Dexterous Robotic Arm,1
```

**Sample config notes:**
- Each tick = 1 second. The AMR travels at 1.0 m/s; fetch or deliver = 60 ticks.
- `target_ticks = 12` is the Dexterous Arm's best-station time (9 ticks for Quality
  Inspection). The Stationary Assembler exceeds target at Quality Inspection (15 ticks),
  so the assignment rule routes the Arm there automatically.
- AMR `ticks_per_action` values in the CSV are ignored; actual duration =
  ceil(60 m / 1.0 m/s) = 60 ticks each way.
- With a single AMR the output buffer fills before the AMR returns from delivery, causing
  periodic line stalls. Adding a second AMR resolves the fetch/deliver conflict.

### 12.2 Scenario files (Final Assembly, Test & Pack)

Five additional CSV files in `static/` walk through a progressive case study on a
Final Assembly / Functional Test / Pack & Label line. Each tick = 1 second.
Central Store distance = 100 m (100-tick round trip at 1.0 m/s). Target = 18 ticks.

Robot operation times:
- Stationary Assembler ($25,000): Final Assembly 12 ticks ✓, Functional Test 25 ticks ✗, Pack & Label 8 ticks ✓
- Dexterous Robotic Arm ($80,000): Final Assembly 8 ticks ✓, Functional Test 14 ticks ✓, Pack & Label 6 ticks ✓

Assignment rule routes the Arm to Functional Test (only robot under 18 ticks there);
Assembler(s) handle Final Assembly and Pack & Label.

| File | Case | Robots | Total Ticks |
|------|------|--------|-------------|
| config_01_hello_world.csv | Hello World — 1 part | 1 AMR, 1 Assembler | 302 |
| config_02_single_assembler.csv | 20 parts, same config | 1 AMR, 1 Assembler | 1325 |
| config_03_add_dexterous_arm.csv | Add Dexterous Arm | 1 AMR, 1 Assembler, 1 Arm | 970 |
| config_04_two_assemblers_one_amr.csv | Full pipeline, 1 AMR | 1 AMR, 2 Assemblers, 1 Arm | 911 |
| config_05_two_assemblers_two_amrs.csv | Full pipeline, 2 AMRs | 2 AMRs, 2 Assemblers, 1 Arm | 757 |

Case 4 → Case 5: adding a second AMR saves 154 ticks (17% faster) by allowing
simultaneous fetch and deliver trips.

---

## 13. File structure

```
back-end-simulation/
  app.py                   # Flask app, routes, auth
  simulation/
    __init__.py
    engine.py              # Tick-based simulation engine (pure Python)
    robot.py               # Robot and RobotType classes
    station.py             # Station class
    line.py                # Line class (buffers, stations, job tracking)
    csv_parser.py          # CSV config parser -> SimConfig dataclass
    analytics.py           # Post-run analytics from log
    logger.py              # Structured JSONL event logger
  templates/
    base.html              # Base template (auth header, nav)
    index.html             # Home page
    results.html           # Results page
  static/
    style.css
    sample_config.csv
    config_01_hello_world.csv
    config_02_single_assembler.csv
    config_03_add_dexterous_arm.csv
    config_04_two_assemblers_one_amr.csv
    config_05_two_assemblers_two_amrs.csv
  data/
    runs/                  # Created at runtime; add to .gitignore
  deploy/
    setup.sh               # Initial EC2 setup (app + nginx HTTP)
    setup-https.sh         # Let's Encrypt / Certbot HTTPS setup
    back-end-simulation.service   # systemd unit for gunicorn
    nginx-http.conf        # nginx config (HTTP only, used before HTTPS)
    nginx-https.conf       # nginx reference config (target state after Certbot)
  .env.example
  requirements.txt         # flask gunicorn python-dotenv
  README.md
```

---

## 14. Phase 2 features (not in v1)

- Behavior Trees (Groot2 XML upload, py_trees execution) — the fetch/deliver threshold
  rule in v1 demonstrates the same concept more simply; BTs are the natural next step
- Multi-line support
- Cost vs. cycle time scatter chart aggregated across past runs
- Robot sharing across lines
- Live tick-by-tick visualization via WebSockets
- Clone past run (copy CSV as starting point for new run)
- AWS Secrets Manager (replace env var auth)
- Per-station target cycle time constraint on robot selection

---

## 15. Definition of done for Saturday

- [x] `sample_config.csv` uploads and simulation runs to completion without errors
- [x] Results page shows Configuration section, visualization, analytics tables, and log table
- [x] Robot utilization and station utilization values are non-zero and plausible
- [x] Average Part Cycle Time, Average Full Cycle Time, and Average Non-Value-Added Time
      are displayed and numerically consistent
- [x] Past runs list on home page shows completed run
- [x] Demo credentials allow access; admin credentials show delete icon
- [x] App is running on EC2 with HTTPS (no browser security warnings)
- [x] Visiting `http://backendsim.com` redirects to `https://backendsim.com`
- [x] README explains how to deploy and use the app
- [x] All five scenario CSV files load and produce expected results
- [x] https://backendsim.com is live and publicly accessible
