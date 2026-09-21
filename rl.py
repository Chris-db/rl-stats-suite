#!/usr/bin/env python
"""Rocket League Stats Suite - unified launcher.

    python rl.py monitor                # watch live events (the connection doctor)
    python rl.py mock --quick           # simulate a match (no game needed)
    python rl.py track                  # record matches to SQLite
    python rl.py dashboard              # open the stats dashboard
    python rl.py seed --matches 40      # fill the dashboard with demo data
    python rl.py demo                   # mock + record + dashboard, one command
    python rl.py alerts                 # stream alert server + OBS overlay
    python rl.py hl-record --start      # start a highlight sync session
    python rl.py hl-build <session> <video>   # cut the highlight reel

Run any subcommand with -h for its own options.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

# Make the suite importable no matter where this is launched from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Never let an odd character crash console output on Windows (cp1252).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — older Pythons / redirected streams
        pass

from rlstats import load_config  # noqa: E402


def cmd_mock(rest):
    from rlstats import mock_server
    mock_server.main(rest)


def cmd_monitor(rest):
    from rlstats import monitor
    monitor.main(rest)


def cmd_capture(rest):
    from rlstats import capture
    capture.main(rest)


def cmd_hl_auto(rest):
    from highlights import auto
    auto.main(rest)


def cmd_hl_log(rest):
    from highlights import recorder
    p = argparse.ArgumentParser(prog="rl.py hl-log",
                                description="Log goal times while you play (use with OBS/ShadowPlay).")
    p.add_argument("--name", help="log file name (default: timestamp).")
    args = p.parse_args(rest)
    recorder.run_log(load_config(), args.name)


def cmd_hl_cut(rest):
    from highlights import cut
    cut.main(rest)


def cmd_setup_api(rest):
    from rlstats import setup_api
    setup_api.main(rest)


def cmd_track(rest):
    from tracker import recorder
    recorder.run(load_config())


def cmd_dashboard(rest):
    from tracker import dashboard
    cfg = load_config()
    print(f"Dashboard: http://{cfg['dashboard_host']}:{cfg['dashboard_port']}")
    dashboard.run(cfg)


def cmd_seed(rest):
    from tracker import seed
    seed.main(rest)


def cmd_alerts(rest):
    from alerts import server
    server.main(rest)


def cmd_hl_record(rest):
    from highlights import recorder
    recorder.main(rest)


def cmd_hl_build(rest):
    from highlights import editor
    editor.main(rest)


def cmd_demo(rest):
    """Run the live pipeline against the mock, then open the dashboard."""
    import asyncio
    from rlstats import events as ev, make_feed
    from rlstats.mock_server import MockServer
    from tracker import db, dashboard
    from tracker.recorder import MatchRecorder

    p = argparse.ArgumentParser(prog="rl.py demo")
    p.add_argument("--matches", type=int, default=6,
                   help="how many mock matches to record before opening the dashboard.")
    p.add_argument("--port", type=int, default=49199, help="mock server port.")
    args = p.parse_args(rest)

    cfg = load_config()
    conn = db.connect(cfg["database_path"])

    # 1) mock server on a background asyncio loop
    server = MockServer("127.0.0.1", args.port, speed=40.0, tick_hz=20.0,
                        match_seconds=120.0, loop=True, oneshot=False,
                        local_name=cfg.get("local_player_name") or "You", seed=None)
    threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True).start()

    # 2) recorder counting completed matches (feed = normalize + derive)
    recorded = {"n": 0}
    cfg_mock = dict(cfg, stats_api_url=f"tcp://127.0.0.1:{args.port}", reconnect_delay=0.5)
    feed = make_feed(cfg_mock)
    MatchRecorder(conn, cfg.get("local_player_name")).attach(feed)
    feed.on(ev.MATCH_ENDED, lambda _d: recorded.__setitem__("n", recorded["n"] + 1))
    feed.start()

    print(f"Recording {args.matches} mock matches…")
    deadline = time.time() + 120
    while recorded["n"] < args.matches and time.time() < deadline:
        time.sleep(0.2)
    feed.stop()
    conn.close()
    print(f"Recorded {recorded['n']} matches. Launching dashboard…")
    print(f"Dashboard: http://{cfg['dashboard_host']}:{cfg['dashboard_port']}")
    dashboard.run(cfg)


COMMANDS = {
    "mock": cmd_mock,
    "monitor": cmd_monitor,
    "capture": cmd_capture,
    "setup-api": cmd_setup_api,
    "track": cmd_track,
    "dashboard": cmd_dashboard,
    "seed": cmd_seed,
    "demo": cmd_demo,
    "alerts": cmd_alerts,
    "hl-log": cmd_hl_log,
    "hl-cut": cmd_hl_cut,
    "hl-auto": cmd_hl_auto,
    "hl-record": cmd_hl_record,
    "hl-build": cmd_hl_build,
}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        description="Rocket League Stats Suite launcher.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("command", choices=list(COMMANDS), help="subcommand to run")
    if not argv or argv[0] in ("-h", "--help"):
        parser.print_help()
        return
    ns, rest = parser.parse_known_args(argv[:1])
    COMMANDS[ns.command](argv[1:])


if __name__ == "__main__":
    main()
