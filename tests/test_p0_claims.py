"""Acceptance tests for the four P0 claims (Section 16), each backed by a
scenario pair in static/v2/scenarios/. These must pass before any web work starts.
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


def test_p0_a_adding_cells_reduces_makespan(tmp_path):
    r1 = _run("a1_one_cell.csv", tmp_path)
    r2 = _run("a2_two_cells.csv", tmp_path)
    assert r2["makespan"] < r1["makespan"] * 0.9  # at least 10% margin


def test_p0_b_adding_amrs_reduces_starvation_and_makespan(tmp_path):
    r1 = _run("b1_one_amr.csv", tmp_path)
    r2 = _run("b2_two_amrs.csv", tmp_path)
    assert r2["total_starvation_ticks"] < r1["total_starvation_ticks"] * 0.9
    assert r2["makespan"] < r1["makespan"] * 0.9


def test_p0_c_predictive_replenishment_beats_reactive(tmp_path):
    r1 = _run("c1_reactive.csv", tmp_path)
    r2 = _run("c2_predictive.csv", tmp_path)
    assert r2["total_starvation_ticks"] < r1["total_starvation_ticks"] * 0.9
    assert r2["makespan"] < r1["makespan"] * 0.9


def test_p0_d_edd_beats_fifo_on_total_lateness(tmp_path):
    r1 = _run("d1_fifo.csv", tmp_path)
    r2 = _run("d2_edd.csv", tmp_path)
    assert r2["total_lateness"] < r1["total_lateness"]
