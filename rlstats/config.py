"""Shared configuration for the Rocket League Stats Suite.

Loads ``config.json`` from the project root if present, otherwise falls back to
``config.example.json``, otherwise to the built-in defaults below. Every tool
imports :func:`load_config` so a single file configures the whole suite.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# Where user data (db, sessions, config.json) lives.
# From source: the project root. Frozen as an .exe: next to the executable, so
# the database persists across runs (a onefile exe's bundle dir is temporary).
if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS: dict[str, Any] = {
    # --- Stats API (the game's local raw-TCP socket) ---
    "stats_api_url": "tcp://127.0.0.1:49123",
    "reconnect_delay": 3.0,

    # Your in-game display name, used to identify "you" in the feed (the real API
    # has no is-local flag). If null, the suite auto-detects from a solo session
    # (freeplay) or the spectated player. Set it to be safe, e.g. "Zeph .".
    "local_player_name": None,

    # Car speed (feed units) at/above which a player counts as supersonic.
    # The feed's unit isn't documented; tune from a real capture if needed.
    "supersonic_speed": 100.0,

    # Game states to ignore so freeplay/training don't pollute stats or reels.
    # Matched as case-insensitive substrings of the playlist name. A match also
    # requires opponents on a second team, so this is a belt-and-braces guard.
    "ignore_playlists": ["freeplay", "free play", "training", "workshop", "custom"],

    # --- Tool 1: Stats Tracker ---
    "database_path": os.path.join(ROOT, "data", "matches.db"),
    "dashboard_host": "127.0.0.1",
    "dashboard_port": 5000,

    # --- Tool 2: Stream Alerts ---
    "alert_overlay_host": "127.0.0.1",
    "alert_overlay_http_port": 8080,   # serves the OBS browser-source page
    "alert_overlay_ws_port": 8765,     # pushes events to the overlay
    "alert_rules_path": os.path.join(ROOT, "alerts", "rules.json"),

    # --- Tool 3: Highlight Editor ---
    "highlight_pre_seconds": 8.0,
    "highlight_post_seconds": 5.0,
    # Shift every clip by N seconds. The goal is logged a beat after the real
    # moment (the score takes ~1s to register), so a small negative value pulls
    # clips earlier to center the goal. Negative = earlier, positive = later.
    "highlight_offset": 0.0,
    "highlight_sessions_dir": os.path.join(ROOT, "data", "highlight_sessions"),
    "ffmpeg_path": "ffmpeg",           # override with an absolute path if needed
    # Auto-highlighter (tool records the screen itself):
    "highlight_recordings_dir": os.path.join(ROOT, "data", "recordings"),
    "highlight_capture_fps": 30,
    "highlight_capture_window": None,  # None = whole desktop; or a window title
    # Shifts every clip to compensate for ffmpeg's capture spin-up (seconds).
    # More negative = clips land earlier. Tune if goals sit off-centre.
    "highlight_capture_sync_offset": -0.5,
}


def load_config(path: str | None = None) -> dict[str, Any]:
    """Return the merged config (defaults <- file overrides)."""
    cfg = dict(DEFAULTS)
    candidates = (
        [path]
        if path
        else [os.path.join(ROOT, "config.json"),
              os.path.join(ROOT, "config.example.json")]
    )
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
            break
    return cfg
