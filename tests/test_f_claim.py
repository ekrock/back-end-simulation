"""Acceptance test for the F claim (job preemption): a late-arriving,
tight-deadline job misses its deadline without preemption, but hits it with
preemption enabled -- without causing the displaced, longer-deadline job to
miss its own (more relaxed) deadline.
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


def test_preemption_saves_the_urgent_job_without_costing_the_displaced_one(tmp_path):
    r1 = _run("f1_no_preemption.csv", tmp_path)
    r2 = _run("f2_preemption.csv", tmp_path)

    jobs1 = {j["name"]: j for j in r1["jobs"]}
    jobs2 = {j["name"]: j for j in r2["jobs"]}

    assert jobs1["JobShort"]["lateness"] > 0        # missed its deadline without preemption
    assert jobs2["JobShort"]["lateness"] == 0        # hits it with preemption
    assert jobs2["JobLong"]["lateness"] == 0         # displaced job still hits its own deadline
    assert r2["total_preemptions"] == 1
    assert r1["total_preemptions"] == 0
