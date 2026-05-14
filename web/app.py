#!/usr/bin/env python3
"""
NetTrace Web — Flask dashboard + REST API.
"""

import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone

import yaml
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

# Add parent dir so we can import collector
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collector.collector import (
    CFG,
    DB_PATH,
    get_state,
    run_speedtest,
    probe_traceroute,
    save_traceroute,
    start_collector,
    starlink_reboot,
    starlink_start_speedtest,
    starlink_get_speedtest_status,
    state,
    state_lock,
)

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
)
CORS(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Dashboard page
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("dashboard.html", config=CFG)


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@app.route("/api/state")
def api_state():
    """Current live state — polled by dashboard JS."""
    return jsonify(get_state())


@app.route("/api/config", methods=["GET", "PUT"])
def api_config():
    """Read or update configuration."""
    config_path = os.environ.get(
        "NETTRACE_CONFIG", "/opt/nettrace/config/nettrace.yaml"
    )
    if request.method == "GET":
        return jsonify(CFG)
    else:
        new_cfg = request.get_json()
        with open(config_path, "w") as f:
            yaml.dump(new_cfg, f, default_flow_style=False)
        return jsonify({"status": "ok", "message": "Config saved. Restart collector to apply."})


@app.route("/api/targets", methods=["GET", "POST", "DELETE"])
def api_targets():
    """Manage ping targets."""
    if request.method == "GET":
        return jsonify(CFG["ping"]["targets"])
    elif request.method == "POST":
        new_target = request.get_json()
        CFG["ping"]["targets"].append(new_target)
        return jsonify({"status": "ok", "targets": CFG["ping"]["targets"]})
    elif request.method == "DELETE":
        host = request.args.get("host")
        CFG["ping"]["targets"] = [
            t for t in CFG["ping"]["targets"] if t["host"] != host
        ]
        return jsonify({"status": "ok", "targets": CFG["ping"]["targets"]})


@app.route("/api/speedtest", methods=["POST"])
def api_speedtest():
    """Trigger a speed test (runs in background, returns immediately)."""
    def _run():
        result = run_speedtest()
        with state_lock:
            state["speedtest"] = result

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"status": "running", "message": "Speed test started."})


@app.route("/api/speedtest/history")
def api_speedtest_history():
    """Get speed test history."""
    limit = request.args.get("limit", 20, type=int)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM speedtest_runs ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/traceroute/run", methods=["POST"])
def api_traceroute_run():
    """Trigger an immediate traceroute."""
    def _run():
        hops = probe_traceroute()
        if hops:
            save_traceroute(hops)
            with state_lock:
                state["traceroute"] = {
                    "hops": hops,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"status": "running"})


@app.route("/api/traceroute/history")
def api_traceroute_history():
    """Get traceroute history for comparison."""
    hours = request.args.get("hours", 24, type=int)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM traceroute_runs WHERE timestamp > ? ORDER BY timestamp DESC",
        (cutoff,),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/traceroute/compare")
def api_traceroute_compare():
    """Compare two traceroute runs by ID."""
    id_a = request.args.get("a", type=int)
    id_b = request.args.get("b", type=int)
    if not id_a or not id_b:
        return jsonify({"error": "Provide ?a=ID&b=ID"}), 400

    conn = get_db()
    run_a = conn.execute("SELECT * FROM traceroute_runs WHERE id=?", (id_a,)).fetchone()
    run_b = conn.execute("SELECT * FROM traceroute_runs WHERE id=?", (id_b,)).fetchone()
    conn.close()

    if not run_a or not run_b:
        return jsonify({"error": "Run not found"}), 404

    hops_a = json.loads(run_a["hops_json"])
    hops_b = json.loads(run_b["hops_json"])

    # Build diff
    ips_a = {h["hop"]: h for h in hops_a}
    ips_b = {h["hop"]: h for h in hops_b}
    all_hops = sorted(set(list(ips_a.keys()) + list(ips_b.keys())))

    diff = []
    for hop_num in all_hops:
        a = ips_a.get(hop_num)
        b = ips_b.get(hop_num)
        entry = {"hop": hop_num}
        if a and b:
            entry["status"] = "changed" if a["ip"] != b["ip"] else "same"
            entry["a"] = a
            entry["b"] = b
            if a["ip"] == b["ip"]:
                entry["rtt_delta"] = round(b["avg"] - a["avg"], 2)
        elif a and not b:
            entry["status"] = "removed"
            entry["a"] = a
        else:
            entry["status"] = "added"
            entry["b"] = b
        diff.append(entry)

    return jsonify({
        "run_a": {"id": run_a["id"], "timestamp": run_a["timestamp"]},
        "run_b": {"id": run_b["id"], "timestamp": run_b["timestamp"]},
        "diff": diff,
    })


@app.route("/api/badspots")
def api_badspots():
    """Get bad spot history."""
    hours = request.args.get("hours", 24, type=int)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bad_spots WHERE start_time > ? ORDER BY start_time DESC",
        (cutoff,),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/ping/history")
def api_ping_history():
    """Get ping history for graphing."""
    target = request.args.get("target", "1.1.1.1")
    minutes = request.args.get("minutes", 30, type=int)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM ping_log WHERE target=? AND timestamp > ? ORDER BY timestamp ASC",
        (target, cutoff),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/gps/track")
def api_gps_track():
    """Get GPS track from ping log (uses lat/lon stored per reading)."""
    minutes = request.args.get("minutes", 60, type=int)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    conn = get_db()
    rows = conn.execute(
        """SELECT timestamp, lat, lon, latency_ms, loss_pct, jitter_ms
           FROM ping_log
           WHERE timestamp > ? AND lat != 0
           GROUP BY CAST(strftime('%s', timestamp) AS INTEGER) / 5
           ORDER BY timestamp ASC""",
        (cutoff,),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/starlink/reboot", methods=["POST"])
def api_starlink_reboot():
    """Reboot the Starlink dish."""
    result = starlink_reboot()
    return jsonify(result)


@app.route("/api/starlink/speedtest", methods=["POST"])
def api_starlink_speedtest():
    """Start a speed test on the Starlink dish."""
    result = starlink_start_speedtest()
    return jsonify(result)


@app.route("/api/starlink/speedtest/status")
def api_starlink_speedtest_status():
    """Get Starlink dish speed test results."""
    result = starlink_get_speedtest_status()
    return jsonify(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Start the collector in background threads
    start_collector()

    # Run Flask
    web_cfg = CFG["web"]
    app.run(
        host=web_cfg["host"],
        port=web_cfg["port"],
        debug=web_cfg.get("debug", False),
        use_reloader=False,  # Reloader conflicts with collector threads
    )


if __name__ == "__main__":
    main()
