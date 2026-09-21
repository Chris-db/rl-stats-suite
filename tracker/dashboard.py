"""Flask dashboard for the Personal Stats Tracker.

Reads the SQLite database the recorder fills and renders trends: win rate over
time, saves per game, performance by arena, and session summaries. The charts
are drawn client-side (Chart.js) from JSON these endpoints return.
"""

from __future__ import annotations

import os
import sys

from flask import Flask, jsonify, render_template

from rlstats import load_config
from . import db


def _asset_dirs() -> tuple[str, str]:
    """Locate templates/ and static/ whether running from source or a PyInstaller exe."""
    if getattr(sys, "frozen", False):
        base = os.path.join(sys._MEIPASS, "tracker")  # bundled via --add-data
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "templates"), os.path.join(base, "static")


def create_app(config: dict | None = None) -> Flask:
    config = config or load_config()
    template_dir, static_dir = _asset_dirs()
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config["RL_DB_PATH"] = config["database_path"]

    def query(fn, *args):
        conn = db.connect(app.config["RL_DB_PATH"])
        try:
            return fn(conn, *args)
        finally:
            conn.close()

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    @app.route("/api/overview")
    def api_overview():
        return jsonify(query(db.overview))

    @app.route("/api/win-rate")
    def api_win_rate():
        return jsonify(query(db.win_rate_over_time))

    @app.route("/api/saves-trend")
    def api_saves_trend():
        return jsonify(query(db.saves_trend))

    @app.route("/api/arenas")
    def api_arenas():
        return jsonify(query(db.performance_by_arena))

    @app.route("/api/sessions")
    def api_sessions():
        return jsonify(query(db.session_summaries))

    @app.route("/api/recent")
    def api_recent():
        return jsonify(query(db.recent_matches, 25))

    return app


def run(config: dict | None = None) -> None:
    config = config or load_config()
    app = create_app(config)
    app.run(host=config["dashboard_host"], port=config["dashboard_port"], debug=False)


if __name__ == "__main__":
    run()
