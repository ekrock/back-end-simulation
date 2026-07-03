# Back-End Assembly Line Simulator — Brief

Read README.md for local dev setup and CSV format.
Read DECISIONS.md for architectural and design decisions.
Read docs/PRD.md for the full product requirements.
Read docs/Cases_2-5_Analysis.md for the cable assembly performance analysis and key simulation insights.
Read docs/backlog.md for future enhancement items.

## What This Is

A tick-based discrete-event simulator for robot-orchestrated back-end assembly lines.
Users upload a CSV configuration, run a simulation, and explore OEE metrics, robot
utilization, station throughput, and a full event log.

Live at: https://backendsim.com (nginx + gunicorn + systemd on AWS EC2)
Repo: https://github.com/ekrock/back-end-simulation

## Current State (as of 2026-07-03)

- v1 fully shipped and live
- Five cable assembly scenario CSVs in static/ (Cases 1–5)
- Cost vs. Performance scatter chart at /chart (two tabs: Total Ticks, Part Cycle Time)
- Results page: configuration, job summary, visualization, robot/station utilization, event log
- HTML doc generator at scripts/maintenance/generate_doc_html.py
- Single-click demo URL: https://backendsim.com/login?u=demo&p=CF*.iD!8.rFBruzD8W-R
- Help page at /help: CSV format reference and simulation limits
- Security: rate limiting (5 runs/hr/IP for demo), 50 demo run cap, CSV size cap (50KB), simulation parameter caps

## Deploy

SSH alias: `back-end-sim-ec2`
Service name: `back-end-simulation.service`
EC2 repo root: `~/back-end-simulation/` (also the running app; venv at `~/back-end-simulation/venv/`)
Deploy: `ssh back-end-sim-ec2 'cd ~/back-end-simulation && git pull'` then `sudo systemctl restart back-end-simulation.service`
Install new deps: `ssh back-end-sim-ec2 'cd ~/back-end-simulation && source venv/bin/activate && pip install -r requirements.txt'`
