"""Acceptance test for the E claim (min_available threshold + staging a
producer's build time behind an unrelated job): staging the dependent job
behind an unrelated job on the same cell lets the producer build a real
buffer, eliminating starvation and reducing makespan, versus scheduling the
dependent job as soon as its (low) threshold clears.
"""
import os

from simulation_v2.analytics import compute
from simulation_v2.csv_parser import parse_csv
from simulation_v2.engine import run_simulation

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "v2", "scenarios")


def _run(name, tmp_path):
    path = os.path.join(SCENARIOS_DIR, name)
    with open(path) as f:
        config = parse_csv(f.read())
    log_path = str(tmp_path / f"{name}.jsonl")
    sim_result = run_simulation(config, log_path, run_id=name)
    return compute(log_path, sim_result)


def test_staging_eliminates_starvation_and_reduces_makespan(tmp_path):
    r1 = _run("e1_unstaged.csv", tmp_path)
    r2 = _run("e2_staged.csv", tmp_path)
    assert r2["total_starvation_ticks"] == 0
    assert r2["total_starvation_ticks"] < r1["total_starvation_ticks"]
    assert r2["makespan"] < r1["makespan"] * 0.9
