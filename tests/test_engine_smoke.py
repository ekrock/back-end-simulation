"""Engine smoke test: the sample config runs to completion and is deterministic."""
import json
import os

from simulation_v2.csv_parser import parse_csv
from simulation_v2.engine import run_simulation

SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "static", "v2", "sample_config_v2.csv")


def _run(tmp_path, run_id):
    with open(SAMPLE_CSV) as f:
        config = parse_csv(f.read())
    log_path = str(tmp_path / f"{run_id}.jsonl")
    from datetime import datetime, timezone
    start_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = run_simulation(config, log_path, run_id, start_time)
    return result, log_path


def test_sample_config_runs_to_completion(tmp_path):
    result, log_path = _run(tmp_path, "run1")
    assert result["termination_reason"] == "all_jobs_complete"
    assert result["makespan"] > 0
    assert all(j["completion_tick"] is not None for j in result["jobs"])
    assert os.path.exists(log_path)
    with open(log_path) as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert lines[0]["attributes"]["event"] == "simulation_start"
    assert lines[-1]["attributes"]["event"] == "simulation_end"


def test_sample_config_is_deterministic(tmp_path):
    result1, log_path1 = _run(tmp_path, "detrun")
    result2, log_path2 = _run(tmp_path, "detrun")

    def strip_timestamps(path):
        records = []
        with open(path) as f:
            for line in f:
                rec = json.loads(line)
                rec.pop("timestamp", None)
                rec.pop("observed_timestamp", None)
                records.append(rec)
        return records

    assert strip_timestamps(log_path1) == strip_timestamps(log_path2)
    assert result1["makespan"] == result2["makespan"]
    assert result1["jobs"] == result2["jobs"]


def test_every_logged_event_has_required_otel_fields(tmp_path):
    _, log_path = _run(tmp_path, "fieldscheck")
    with open(log_path) as f:
        for line in f:
            rec = json.loads(line)
            assert "timestamp" in rec
            assert "trace_id" in rec and len(rec["trace_id"]) == 32
            assert "span_id" in rec and len(rec["span_id"]) == 16
            assert "resource" in rec and rec["resource"]["service.name"] == "backend-sim-v2"
            assert "tick" in rec["attributes"]
            assert "event" in rec["attributes"]
