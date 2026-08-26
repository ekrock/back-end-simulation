"""Acceptance test for the G claim (job splitting): a large job that can't
finish on one cell by its deadline hits it once split across enough of the
idle capable cells to make it, without needing every cell available.
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


def test_splitting_makes_the_deadline_a_single_cell_cannot(tmp_path):
    r1 = _run("g1_no_split.csv", tmp_path)
    r2 = _run("g2_split.csv", tmp_path)

    job1 = r1["jobs"][0]
    job2 = r2["jobs"][0]

    assert job1["lateness"] > 0                  # single cell misses the deadline
    assert job2["lateness"] == 0                  # split across cells hits it
    assert job1["cell"] == "CellA"                # ran on exactly one cell
    assert job2["cell"] == "CellA, CellB, CellC"  # split across all three
    assert job1["units"] == job2["units"] == 30   # same total work either way
