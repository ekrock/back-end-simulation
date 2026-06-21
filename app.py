"""Flask web app for the Back-End Assembly Line Simulator."""
import functools
import json
import os
import random
import shutil
import string
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import (Flask, abort, jsonify, redirect, render_template,
                   request, send_file, send_from_directory, url_for)

from simulation.analytics import compute
from simulation.csv_parser import ParseError, parse_csv
from simulation.engine import run_simulation

load_dotenv()

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "runs")
SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "static", "sample_config.csv")


# ── Authentication ────────────────────────────────────────────────────────────

def _check_auth(username: str, password: str) -> bool:
    admin_ok = (username == os.environ.get("ADMIN_USERNAME")
                and password == os.environ.get("ADMIN_PASSWORD"))
    demo_ok = (username == os.environ.get("DEMO_USERNAME")
               and password == os.environ.get("DEMO_PASSWORD"))
    return admin_ok or demo_ok


def _is_admin(username: str) -> bool:
    return username == os.environ.get("ADMIN_USERNAME")


def _request_auth():
    return (
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Back-End Assembly Line Simulator"'},
    )


def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_auth(auth.username, auth.password):
            return _request_auth()
        return f(*args, **kwargs, username=auth.username)
    return decorated


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{stamp}_{suffix}"


def _run_dir(run_id: str) -> str:
    return os.path.join(DATA_DIR, run_id)


def _load_meta(run_id: str) -> dict | None:
    meta_path = os.path.join(_run_dir(run_id), "meta.json")
    if not os.path.exists(meta_path):
        return None
    with open(meta_path) as f:
        return json.load(f)


def _list_runs() -> list[dict]:
    if not os.path.exists(DATA_DIR):
        return []
    runs = []
    for run_id in os.listdir(DATA_DIR):
        meta = _load_meta(run_id)
        if meta:
            meta["run_id"] = run_id
            runs.append(meta)
    runs.sort(key=lambda r: r.get("start_time", ""), reverse=True)
    return runs


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
@require_auth
def index(username: str):
    runs = _list_runs()
    return render_template("index.html", runs=runs, is_admin=_is_admin(username))


@app.route("/download/template/csv")
@require_auth
def download_template(username: str):
    return send_file(SAMPLE_CSV, as_attachment=True, download_name="sample_config.csv")


@app.route("/run/new", methods=["POST"])
@require_auth
def new_run(username: str):
    if "csv_file" not in request.files:
        return render_template("index.html", runs=_list_runs(),
                               is_admin=_is_admin(username),
                               error="No file uploaded."), 400

    file = request.files["csv_file"]
    if not file.filename:
        return render_template("index.html", runs=_list_runs(),
                               is_admin=_is_admin(username),
                               error="No file selected."), 400

    csv_text = file.read().decode("utf-8", errors="replace")

    try:
        config = parse_csv(csv_text)
    except ParseError as e:
        return render_template("index.html", runs=_list_runs(),
                               is_admin=_is_admin(username),
                               error=f"CSV error: {e}"), 400

    run_id = _new_run_id()
    run_path = _run_dir(run_id)
    os.makedirs(run_path, exist_ok=True)

    # Save uploaded CSV
    with open(os.path.join(run_path, "config.csv"), "w") as f:
        f.write(csv_text)

    log_path = os.path.join(run_path, "run_log.jsonl")
    start_time = datetime.now(timezone.utc).isoformat()

    try:
        sim_result = run_simulation(config, log_path)
        analytics = compute(log_path, sim_result)
    except Exception as e:
        shutil.rmtree(run_path, ignore_errors=True)
        return render_template("index.html", runs=_list_runs(),
                               is_admin=_is_admin(username),
                               error=f"Simulation error: {e}"), 500

    # Save results.json
    with open(os.path.join(run_path, "results.json"), "w") as f:
        json.dump(analytics, f, indent=2)

    # Save meta.json
    meta = {
        "run_id": run_id,
        "name": config.simulation.name,
        "description": config.simulation.description,
        "start_time": start_time,
        "status": "completed",
        "parts_completed": sim_result["parts_completed"],
        "total_ticks": sim_result["total_ticks"],
        "termination_reason": sim_result["termination_reason"],
        "target_ticks": config.job.target_ticks,
        "central_store_distance_meters": config.line.central_store_distance_meters,
        "robot_types": [
            {
                "type_name": rt.type_name,
                "cost_dollars": rt.cost_dollars,
                "speed": rt.speed_meters_per_tick,
                "actions": rt.actions,
            }
            for rt in config.robot_types
        ],
        "robot_counts": [
            {"type_name": rc.type_name, "count": rc.count}
            for rc in config.robot_counts
        ],
    }
    with open(os.path.join(run_path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    return redirect(url_for("view_run", run_id=run_id))


@app.route("/run/<run_id>")
@require_auth
def view_run(run_id: str, username: str):
    # Basic path safety
    if "/" in run_id or ".." in run_id:
        abort(404)
    run_path = _run_dir(run_id)
    if not os.path.exists(run_path):
        abort(404)

    meta = _load_meta(run_id)
    if not meta:
        abort(404)

    results_path = os.path.join(run_path, "results.json")
    with open(results_path) as f:
        results = json.load(f)

    log_path = os.path.join(run_path, "run_log.jsonl")
    log_events = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                log_events.append(json.loads(line))

    return render_template(
        "results.html",
        meta=meta,
        results=results,
        log_events=log_events,
        run_id=run_id,
        is_admin=_is_admin(username),
    )


@app.route("/run/<run_id>/log")
@require_auth
def download_log(run_id: str, username: str):
    if "/" in run_id or ".." in run_id:
        abort(404)
    log_path = os.path.join(_run_dir(run_id), "run_log.jsonl")
    if not os.path.exists(log_path):
        abort(404)
    return send_file(log_path, as_attachment=True,
                     download_name=f"{run_id}_event_log.jsonl")


@app.route("/run/<run_id>/csv")
@require_auth
def download_run_csv(run_id: str, username: str):
    if "/" in run_id or ".." in run_id:
        abort(404)
    csv_path = os.path.join(_run_dir(run_id), "config.csv")
    if not os.path.exists(csv_path):
        abort(404)
    return send_file(csv_path, as_attachment=True,
                     download_name=f"{run_id}_config.csv")


@app.route("/run/<run_id>", methods=["DELETE"])
@require_auth
def delete_run(run_id: str, username: str):
    if not _is_admin(username):
        abort(403)
    if "/" in run_id or ".." in run_id:
        abort(404)
    run_path = _run_dir(run_id)
    if not os.path.exists(run_path):
        abort(404)
    shutil.rmtree(run_path)
    return jsonify({"status": "deleted"}), 200


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    app.run(debug=True, port=5001)
