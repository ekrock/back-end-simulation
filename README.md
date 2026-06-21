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

app.py            — Flask web layer (auth, run management, file downloads)
templates/        — base.html, index.html, results.html
static/           — style.css, sample_config.csv
data/runs/        — one directory per run (gitignored)
deploy/           — systemd service, nginx configs, setup scripts
```
