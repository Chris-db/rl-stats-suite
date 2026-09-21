#!/usr/bin/env python
"""All-in-one background tracker — the entry point for the shareable .exe.

Double-click and it:
  1. turns on Rocket League's Stats API (finds the install for you),
  2. records every real match in the background,
  3. opens your stats dashboard in the browser.

Keep the window open while you play; close it to stop. Freeplay/training is
ignored automatically — only real matches are recorded.

Run from source with:  python app.py   (or:  python rl.py track  + dashboard)
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

# Make the suite importable from source and when frozen.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from rlstats import load_config                       # noqa: E402
from rlstats.setup_api import ensure_enabled, _MESSAGES  # noqa: E402


def _enable_api() -> None:
    print("Checking Rocket League's Stats API...")
    results = ensure_enabled()
    if not results:
        print("  ! Couldn't find Rocket League automatically.")
        print("    Set PacketSendRate=10 in ...\\rocketleague\\TAGame\\Config\\DefaultStatsAPI.ini")
        return
    for path, status in results:
        print(f"  - {_MESSAGES.get(status, status)}: {path}")
    if any(s == "updated" for _, s in results):
        print("  -> Restart Rocket League so it picks up the change.")
    if any(s == "denied" for _, s in results):
        print("  ! Needs admin to enable. Right-click this app and 'Run as administrator' once.")


def _run_recorder(config: dict) -> None:
    # recorder.run creates its DB connection and listener in *this* thread.
    from tracker import recorder
    recorder.run(config)


def _run_dashboard(config: dict) -> None:
    from tracker import dashboard
    app = dashboard.create_app(config)
    app.run(host=config["dashboard_host"], port=config["dashboard_port"],
            debug=False, use_reloader=False)


def main() -> None:
    print("=" * 60)
    print("  Rocket League Stats Tracker")
    print("=" * 60)
    config = load_config()

    _enable_api()

    threading.Thread(target=_run_recorder, args=(config,), daemon=True).start()
    threading.Thread(target=_run_dashboard, args=(config,), daemon=True).start()

    url = f"http://{config['dashboard_host']}:{config['dashboard_port']}"
    time.sleep(1.2)
    if os.environ.get("RL_NO_BROWSER") != "1":
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    print()
    print(f"  Dashboard:  {url}")
    print("  Recording real matches in the background (freeplay is ignored).")
    print("  Keep this window open while you play. Close it to stop.")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping. Bye!")


if __name__ == "__main__":
    main()
