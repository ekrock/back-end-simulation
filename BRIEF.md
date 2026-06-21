# Back-End Assembly Line Simulator — Brief

Read README.md for local dev setup and CSV format.
Read DECISIONS.md for architectural and design decisions.
Read docs/PRD.md for the full product requirements.
Read docs/Cases_2-5_Analysis.md for the cable assembly performance analysis and key simulation insights.

## What This Is

A tick-based discrete-event simulator for robot-orchestrated back-end assembly lines.
Users upload a CSV configuration, run a simulation, and explore OEE metrics, robot
utilization, station throughput, and a full event log.

Live at: https://backendsim.com (nginx + gunicorn + systemd on AWS EC2)
Repo: https://github.com/ekrock/back-end-simulation

## Current State (as of 2026-06-21)

- v1 fully shipped and live
- Five cable assembly scenario CSVs in static/ (Cases 1–5)
- Cost vs. Performance scatter chart at /chart (two tabs: Total Ticks, Part Cycle Time)
- Results page: configuration, job summary, visualization, robot/station utilization, event log
- HTML doc generator at scripts/maintenance/generate_doc_html.py

## Deploy

SSH alias: `back-end-sim-ec2`
Service name: `back-end-simulation.service`
Deploy: `git pull && sudo systemctl restart back-end-simulation`
