"""V2 routes: multi-cell orchestration & replenishment simulation."""
import csv
import io
import json
import os
import random
import re
import shutil
import string
from datetime import datetime, timezone

from flask import (Blueprint, Response, abort, jsonify, redirect,
                    render_template, request, send_file, url_for)

from simulation_v2.analytics import compute
from simulation_v2.csv_parser import ParseError, parse_csv
from simulation_v2.engine import run_simulation
from web.auth import _is_admin, require_auth

v2_bp = Blueprint("v2", __name__)

_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR_V2 = os.path.join(_BASE_DIR, "data", "runs_v2")
SAMPLE_CSV_V2 = os.path.join(_BASE_DIR, "static", "v2", "sample_config_v2.csv")
SCENARIOS_DIR_V2 = os.path.join(_BASE_DIR, "static", "v2", "scenarios")
MAX_CSV_BYTES = 50 * 1024
MAX_DEMO_RUNS_V2 = 50

SCENARIOS = [
    ("a1_one_cell.csv", "P0-A baseline: four jobs share a single cell."),
    ("a2_two_cells.csv", "P0-A: a second cell lets two jobs run in parallel."),
    ("b1_one_amr.csv", "P0-B baseline: one AMR cannot keep five stations fed."),
    ("b2_two_amrs.csv", "P0-B: a second AMR roughly halves starvation."),
    ("b3_three_amrs.csv", "P0-B series: a third AMR, marginal-returns comparison."),
    ("b4_four_amrs.csv", "P0-B series: a fourth AMR, marginal-returns comparison."),
    ("b5_five_amrs.csv", "P0-B series: a fifth AMR, marginal-returns comparison."),
    ("c1_reactive.csv", "P0-C baseline: replenishment waits until the buffer empties."),
    ("c2_predictive.csv", "P0-C: predictive replenishment arrives before the buffer empties."),
    ("d1_fifo.csv", "P0-D baseline: FIFO scheduling misses a tight deadline."),
    ("d2_edd.csv", "P0-D: EDD scheduling meets the same deadline."),
    ("e1_unstaged.csv", "E baseline: an under-buffered dependent job starves repeatedly."),
    ("e2_staged.csv", "E: staging an unrelated job first lets the dependency build a real buffer."),
    ("f1_no_preemption.csv", "F baseline: a late-arriving, tight-deadline job misses it waiting its turn."),
    ("f2_preemption.csv", "F: preemption interrupts the in-progress job so the urgent one hits its deadline."),
    ("g1_no_split.csv", "G baseline: a big job on one cell alone misses its deadline."),
    ("g2_split.csv", "G: splitting the job across enough idle cells makes the same deadline."),
]

_SCENARIO_CODE_RE = re.compile(r"^([a-zA-Z]+)(\d+)")


def _scenario_sort_prefix(scenario_filename: str):
    """Derive a zero-padded, alphabetically-sortable code like 'A01' from a
    scenario filename like 'a1_one_cell.csv'. Zero-padding keeps a series
    (a1, a2, ..., a10, ...) in numeric order even past a single digit --
    plain string sort would otherwise put 'a10' before 'a2'."""
    stem = os.path.splitext(scenario_filename)[0]
    m = _SCENARIO_CODE_RE.match(stem)
    if not m:
        return None
    letters, number = m.groups()
    return f"{letters.upper()}{int(number):02d}"


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{stamp}_{suffix}"


def _run_dir(run_id: str) -> str:
    return os.path.join(DATA_DIR_V2, run_id)


def _load_meta(run_id: str):
    meta_path = os.path.join(_run_dir(run_id), "meta.json")
    if not os.path.exists(meta_path):
        return None
    with open(meta_path) as f:
        return json.load(f)


def _list_runs_alphabetical() -> list:
    """Past Runs displays alphabetically by name (e.g. A01, A02, B01, ...)
    rather than by recency, so a related series stays grouped and ordered."""
    return sorted(_list_runs(), key=lambda r: r.get("name", "").lower())


def _list_runs() -> list:
    if not os.path.exists(DATA_DIR_V2):
        return []
    runs = []
    for run_id in os.listdir(DATA_DIR_V2):
        meta = _load_meta(run_id)
        if meta:
            meta["run_id"] = run_id
            runs.append(meta)
    runs.sort(key=lambda r: r.get("start_time", ""), reverse=True)
    return runs


def _enforce_demo_run_cap():
    """Delete the oldest V2 demo runs when at or over MAX_DEMO_RUNS_V2. Admin runs are never deleted."""
    demo_runs = [r for r in _list_runs() if not _is_admin(r.get("username", ""))]
    demo_runs.sort(key=lambda r: r.get("start_time", ""))
    while len(demo_runs) >= MAX_DEMO_RUNS_V2:
        oldest = demo_runs.pop(0)
        shutil.rmtree(_run_dir(oldest["run_id"]), ignore_errors=True)


_LOG_ROW_NAMED_KEYS = {"tick", "event", "job", "cell", "station", "amr", "part", "qty", "qty_delivered"}


def _format_log_row(record: dict) -> dict:
    """Flatten one OTel-shaped log record into the Tick|Event|Job|Cell|Station|AMR|Part|Qty|Detail
    columns for the results page event log table."""
    attrs = record["attributes"]
    detail = ", ".join(f"{k}={v}" for k, v in attrs.items() if k not in _LOG_ROW_NAMED_KEYS)
    return {
        "tick": attrs.get("tick"),
        "event": attrs.get("event"),
        "job": attrs.get("job", ""),
        "cell": attrs.get("cell", ""),
        "station": attrs.get("station", ""),
        "amr": attrs.get("amr", ""),
        "part": attrs.get("part", ""),
        "qty": attrs.get("qty", attrs.get("qty_delivered", "")),
        "detail": detail,
        "severity": record["severity_text"],
    }


def _results_to_csv(results: dict) -> str:
    """Flatten results.json into a section-based CSV, mirroring the page layout:
    run summary, then one table per section (per-job, cell/station/AMR utilization)."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["[RUN_SUMMARY]"])
    writer.writerow(["metric", "value"])
    for key in ("makespan", "termination_reason", "total_lateness", "jobs_late", "jobs_unfinished",
                "total_starvation_ticks", "total_blocked_ticks", "total_blocked_ticks_starved",
                "total_blocked_ticks_output_full", "total_setup_ticks", "total_draining_ticks",
                "amr_trips_total", "amr_trips_delivery", "amr_trips_pickup", "amr_trips_return",
                "total_preemptions", "total_job_splits", "fleet_cost",
                "avg_cell_utilization", "avg_station_utilization", "avg_amr_utilization"):
        writer.writerow([key, results[key]])
    writer.writerow([])

    writer.writerow(["[PER_JOB]"])
    writer.writerow(["name", "cell", "arrival_tick", "assigned_tick", "begin_tick",
                      "complete_at_cell_tick", "completion_tick", "deadline_tick",
                      "lateness", "unfinished", "avg_unit_cycle_ticks", "times_preempted", "shard_count"])
    for j in results["jobs"]:
        writer.writerow([j["name"], j["cell"], j["arrival_tick"], j["assigned_tick"], j["begin_tick"],
                          j["complete_at_cell_tick"], j["completion_tick"], j["deadline_tick"],
                          j["lateness"], j["unfinished"], j["avg_unit_cycle_ticks"], j["times_preempted"],
                          j["shard_count"]])
    writer.writerow([])

    writer.writerow(["[CELL_UTILIZATION]"])
    writer.writerow(["cell", "utilization_pct", "setup_ticks", "blocked_ticks_starved",
                      "blocked_ticks_output_full", "draining_ticks"])
    for c in results["cells"]:
        writer.writerow([c["name"], results["cell_utilization"][c["name"]], c["setup_ticks"],
                          c["blocked_ticks_starved"], c["blocked_ticks_output_full"], c["draining_ticks"]])
    writer.writerow([])

    writer.writerow(["[STATION_UTILIZATION]"])
    writer.writerow(["station", "utilization_pct", "starving_ticks"])
    for s in results["stations"]:
        writer.writerow([s["name"], results["station_utilization"][s["name"]], s["starving_ticks"]])
    writer.writerow([])

    writer.writerow(["[AMR_UTILIZATION]"])
    writer.writerow(["amr", "type_name", "utilization_pct", "trips", "cost_dollars"])
    for a in results["amrs"]:
        writer.writerow([a["name"], a["type_name"], results["amr_utilization"][a["name"]],
                          a["trips"], a["cost_dollars"]])

    return output.getvalue()


@v2_bp.route("/")
@require_auth
def v2_index(username: str):
    runs = _list_runs_alphabetical()
    return render_template("v2/index.html", runs=runs, is_admin=_is_admin(username),
                           scenarios=SCENARIOS)


@v2_bp.route("/compare")
@require_auth
def v2_compare(username: str):
    ids = [r for r in request.args.get("runs", "").split(",") if r]
    rows = []
    for run_id in ids:
        if "/" in run_id or ".." in run_id:
            continue
        meta = _load_meta(run_id)
        if not meta:
            continue
        results_path = os.path.join(_run_dir(run_id), "results.json")
        if not os.path.exists(results_path):
            continue
        with open(results_path) as f:
            results = json.load(f)
        rows.append({
            "run_id": run_id, "name": meta.get("name", run_id),
            "scheduling_policy": meta.get("scheduling_policy"),
            "replenishment_policy": meta.get("replenishment_policy"),
            "makespan": results["makespan"], "total_lateness": results["total_lateness"],
            "total_starvation_ticks": results["total_starvation_ticks"],
            "total_blocked_ticks": results["total_blocked_ticks"],
            "amr_trips_total": results["amr_trips_total"], "fleet_cost": results["fleet_cost"],
        })
    # Sort by name, not selection order, so a related series (A01, A02, A03, ...)
    # always compares in logical order regardless of the order runs were checked.
    rows.sort(key=lambda r: r["name"])
    all_runs = _list_runs_alphabetical()
    return render_template("v2/compare.html", rows=rows, all_runs=all_runs,
                           selected_ids=set(ids), is_admin=_is_admin(username))


@v2_bp.route("/help")
@require_auth
def v2_help(username: str):
    return render_template("v2/help.html")


@v2_bp.route("/download/template/csv")
@require_auth
def v2_download_template(username: str):
    return send_file(SAMPLE_CSV_V2, as_attachment=True, download_name="sample_config_v2.csv")


@v2_bp.route("/download/scenario/<name>")
@require_auth
def v2_download_scenario(name: str, username: str):
    if "/" in name or ".." in name or not name.endswith(".csv"):
        abort(404)
    valid_names = {n for n, _ in SCENARIOS}
    if name not in valid_names:
        abort(404)
    path = os.path.join(SCENARIOS_DIR_V2, name)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=name)


@v2_bp.route("/run/new", methods=["POST"])
@require_auth
def v2_new_run(username: str):
    runs = _list_runs_alphabetical()
    scenarios = SCENARIOS

    uploaded = request.files.get("csv_file")
    scenario_name = request.form.get("scenario_name", "").strip()
    used_scenario_name = None

    if uploaded and uploaded.filename:
        csv_bytes = uploaded.read()
        if len(csv_bytes) > MAX_CSV_BYTES:
            return render_template("v2/index.html", runs=runs, is_admin=_is_admin(username),
                                   scenarios=scenarios,
                                   error=f"CSV file too large (max {MAX_CSV_BYTES // 1024} KB)."), 400
        csv_text = csv_bytes.decode("utf-8", errors="replace")
    elif scenario_name:
        valid_names = {n for n, _ in SCENARIOS}
        if scenario_name not in valid_names:
            return render_template("v2/index.html", runs=runs, is_admin=_is_admin(username),
                                   scenarios=scenarios, error="Unknown scenario file selected."), 400
        with open(os.path.join(SCENARIOS_DIR_V2, scenario_name)) as f:
            csv_text = f.read()
        used_scenario_name = scenario_name
    else:
        return render_template("v2/index.html", runs=runs, is_admin=_is_admin(username),
                               scenarios=scenarios,
                               error="Upload a CSV file or select a scenario file to run."), 400

    try:
        config = parse_csv(csv_text)
    except ParseError as e:
        return render_template("v2/index.html", runs=runs, is_admin=_is_admin(username),
                               scenarios=scenarios, error=f"CSV error: {e}"), 400

    if not _is_admin(username):
        _enforce_demo_run_cap()

    run_id = _new_run_id()
    run_path = _run_dir(run_id)
    os.makedirs(run_path, exist_ok=True)

    with open(os.path.join(run_path, "config.csv"), "w") as f:
        f.write(csv_text)

    log_path = os.path.join(run_path, "run_log.jsonl")
    start_time = datetime.now(timezone.utc)

    try:
        sim_result = run_simulation(config, log_path, run_id, start_time)
        results = compute(log_path, sim_result)
    except Exception as e:
        shutil.rmtree(run_path, ignore_errors=True)
        return render_template("v2/index.html", runs=runs, is_admin=_is_admin(username),
                               scenarios=scenarios, error=f"Simulation error: {e}"), 500

    with open(os.path.join(run_path, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    # Prefix scenario-derived runs with a sortable code (e.g. "A01: ...") so a
    # related series (a1, a2, a3, ...) sorts into logical order by name, most
    # useful for picking runs to compare on /v2/compare.
    run_name = config.simulation.name
    if used_scenario_name:
        prefix = _scenario_sort_prefix(used_scenario_name)
        if prefix:
            run_name = f"{prefix}: {run_name}"

    meta = {
        "run_id": run_id,
        "username": username,
        "name": run_name,
        "description": config.simulation.description,
        "start_time": start_time.isoformat(),
        "status": "completed" if results["termination_reason"] == "all_jobs_complete" else "max_ticks_reached",
        "scheduling_policy": config.simulation.scheduling_policy,
        "replenishment_policy": f"{config.simulation.replenishment_policy},{config.simulation.replenishment_value}",
        "makespan": results["makespan"],
        "total_lateness": results["total_lateness"],
        "total_starvation_ticks": results["total_starvation_ticks"],
        "total_blocked_ticks": results["total_blocked_ticks"],
        "amr_trips_total": results["amr_trips_total"],
        "jobs_late": results["jobs_late"],
        "jobs_unfinished": results["jobs_unfinished"],
    }
    with open(os.path.join(run_path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    return redirect(url_for("v2.v2_view_run", run_id=run_id))


@v2_bp.route("/run/<run_id>")
@require_auth
def v2_view_run(run_id: str, username: str):
    if "/" in run_id or ".." in run_id:
        abort(404)
    run_path = _run_dir(run_id)
    if not os.path.exists(run_path):
        abort(404)

    meta = _load_meta(run_id)
    if not meta:
        abort(404)

    with open(os.path.join(run_path, "results.json")) as f:
        results = json.load(f)

    with open(os.path.join(run_path, "config.csv")) as f:
        config_text = f.read()
    config = parse_csv(config_text)

    log_rows = []
    truncated = False
    with open(os.path.join(run_path, "run_log.jsonl")) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if len(log_rows) >= 5000:
                truncated = True
                break
            log_rows.append(_format_log_row(json.loads(line)))

    return render_template("v2/results.html", meta=meta, results=results, config=config,
                           log_rows=log_rows, log_truncated=truncated, run_id=run_id,
                           is_admin=_is_admin(username))


@v2_bp.route("/run/<run_id>/log")
@require_auth
def v2_download_log(run_id: str, username: str):
    if "/" in run_id or ".." in run_id:
        abort(404)
    log_path = os.path.join(_run_dir(run_id), "run_log.jsonl")
    if not os.path.exists(log_path):
        abort(404)
    return send_file(log_path, as_attachment=True, download_name=f"{run_id}_event_log.jsonl")


@v2_bp.route("/run/<run_id>/config")
@require_auth
def v2_download_config(run_id: str, username: str):
    if "/" in run_id or ".." in run_id:
        abort(404)
    csv_path = os.path.join(_run_dir(run_id), "config.csv")
    if not os.path.exists(csv_path):
        abort(404)
    return send_file(csv_path, as_attachment=True, download_name=f"{run_id}_config.csv")


@v2_bp.route("/run/<run_id>/results")
@require_auth
def v2_download_results_csv(run_id: str, username: str):
    if "/" in run_id or ".." in run_id:
        abort(404)
    results_path = os.path.join(_run_dir(run_id), "results.json")
    if not os.path.exists(results_path):
        abort(404)
    with open(results_path) as f:
        results = json.load(f)
    csv_text = _results_to_csv(results)
    return Response(csv_text, mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment; filename={run_id}_results.csv"})


@v2_bp.route("/run/<run_id>", methods=["DELETE"])
@require_auth
def v2_delete_run(run_id: str, username: str):
    if not _is_admin(username):
        abort(403)
    if "/" in run_id or ".." in run_id:
        abort(404)
    run_path = _run_dir(run_id)
    if not os.path.exists(run_path):
        abort(404)
    shutil.rmtree(run_path)
    return jsonify({"status": "deleted"}), 200
