"""OpenTelemetry-shaped JSONL event log writer (Section 12.7).

Trace = job (or "simulation" for run-level events). Span = job / cell-execution /
AMR-trip, derived deterministically from run_id + names via sha256, per spec.
"""
import hashlib
import json
from datetime import timedelta

# DECISION: log() attaches job/cell/amr as displayed attributes whenever the
# caller passes them (used for trace/span routing), even for the few events
# where Section 12.7's table doesn't explicitly list that field. This keeps
# routing and display in one code path instead of a second per-event
# attribute allow-list; every listed attribute is still always present.
_SPAN_KIND = {
    "simulation_start": "simulation",
    "simulation_end": "simulation",
    "job_arrived": "job",
    "job_assigned": "job",
    "job_complete": "job",
    "part_request": "cell",
    "pickup_request": "cell",
    "job_begin": "cell",
    "station_starving": "cell",
    "station_starving_end": "cell",
    "cell_blocked": "cell",
    "cell_blocked_end": "cell",
    "unit_complete": "cell",
    "job_complete_at_cell": "cell",
    "amr_dispatched": "trip",
    "parts_delivered": "trip",
    "product_picked_up": "trip",
    "amr_returned": "trip",
    "product_delivered_to_store": "trip",
}


def _hash(s: str, length: int) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:length]


class OtelLogger:
    def __init__(self, log_path: str, run_id: str, start_time):
        self._file = open(log_path, "w")
        self.run_id = run_id
        self.start_time = start_time

    def log(self, event: str, tick: int, job=None, cell=None, amr=None,
             trip=None, **attrs) -> None:
        kind = _SPAN_KIND.get(event, "simulation")
        if kind == "simulation":
            trace_id = _hash(f"{self.run_id}:simulation", 32)
            span_name = "simulation"
        else:
            trace_id = _hash(f"{self.run_id}:{job}", 32)
            if kind == "job":
                span_name = f"job:{job}"
            elif kind == "cell":
                span_name = f"cell:{job}@{cell}"
            else:
                span_name = f"trip:{amr}#{trip}"
        span_id = _hash(f"{trace_id}:{span_name}", 16)

        severity = "INFO"
        if event in ("station_starving", "cell_blocked"):
            severity = "WARN"
        elif event == "job_complete" and attrs.get("lateness", 0) > 0:
            severity = "WARN"
        elif event == "simulation_end" and attrs.get("reason") == "max_ticks_reached":
            severity = "ERROR"

        ts = (self.start_time + timedelta(seconds=tick)).strftime("%Y-%m-%dT%H:%M:%SZ")

        full_attrs = {"tick": tick, "event": event}
        if job is not None:
            full_attrs["job"] = job
        if cell is not None:
            full_attrs["cell"] = cell
        if amr is not None:
            full_attrs["amr"] = amr
        full_attrs.update(attrs)

        record = {
            "timestamp": ts,
            "observed_timestamp": ts,
            "severity_text": severity,
            "body": event,
            "trace_id": trace_id,
            "span_id": span_id,
            "resource": {"service.name": "backend-sim-v2", "run.id": self.run_id},
            "attributes": full_attrs,
        }
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
