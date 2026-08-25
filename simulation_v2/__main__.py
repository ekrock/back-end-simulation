"""CLI: python -m simulation_v2 <config.csv> --out <dir>"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from simulation_v2.analytics import compute
from simulation_v2.csv_parser import ParseError, parse_csv
from simulation_v2.engine import run_simulation


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run a V2 multi-cell orchestration simulation.")
    parser.add_argument("config_csv")
    parser.add_argument("--out", required=True, help="Output directory for run_log.jsonl and results.json")
    args = parser.parse_args(argv)

    with open(args.config_csv) as f:
        csv_text = f.read()
    try:
        config = parse_csv(csv_text)
    except ParseError as e:
        print(f"CSV error: {e}", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    log_path = os.path.join(args.out, "run_log.jsonl")
    run_id = os.path.basename(os.path.normpath(args.out)) or "cli_run"
    start_time = datetime.now(timezone.utc)

    sim_result = run_simulation(config, log_path, run_id, start_time)
    results = compute(log_path, sim_result)

    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    print(f"Makespan: {results['makespan']} ticks ({results['termination_reason']})")
    print(f"Total lateness: {results['total_lateness']} ticks "
          f"(jobs late: {results['jobs_late']}, unfinished: {results['jobs_unfinished']})")
    print(f"Total starvation ticks: {results['total_starvation_ticks']}")
    print(f"Total blocked ticks: {results['total_blocked_ticks']} "
          f"(starved: {results['total_blocked_ticks_starved']}, "
          f"output_full: {results['total_blocked_ticks_output_full']})")
    print(f"AMR trips: {results['amr_trips_total']} "
          f"(delivery: {results['amr_trips_delivery']}, pickup: {results['amr_trips_pickup']})")
    print(f"Fleet cost: ${results['fleet_cost']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
