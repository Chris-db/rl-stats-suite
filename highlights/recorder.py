"""Highlight session recorder.

Starts a sync session whose zero point is the moment you begin recording, then
logs every goal's position in the video as the match plays. Run this the instant
you start your OBS / screen recording::

    python rl.py hl-record --start --video "D:/clips/match.mkv"

Leave it running; each goal is logged and the session file is saved live. Stop
with Ctrl+C when you're done, then build the reel with ``hl-build``.
"""

from __future__ import annotations

import argparse
import logging
import os
import time

from rlstats import events as ev, load_config, make_feed
from rlstats.matchstate import MatchGate, DEFAULT_IGNORE_PLAYLISTS
from .sync import SyncSession

log = logging.getLogger("rlstats.highlights.recorder")


def _default_session_path(config: dict, name: str | None) -> str:
    name = name or time.strftime("session_%Y%m%d_%H%M%S")
    if not name.endswith(".json"):
        name += ".json"
    return os.path.join(config["highlight_sessions_dir"], name)


class HighlightRecorder:
    def __init__(self, session: SyncSession, save_path: str,
                 gate: MatchGate | None = None, min_gap_seconds: float = 2.0) -> None:
        self.session = session
        self.save_path = save_path
        # Only log goals while a real match is in progress (skips freeplay).
        self.gate = gate if gate is not None else MatchGate()
        # Safety net: real goals are always seconds apart (kickoff between them),
        # so ignore anything closer than this — no spam can reach the reel.
        self.min_gap = min_gap_seconds
        self._last_goal_mono: float | None = None

    def attach(self, feed) -> "HighlightRecorder":
        self.gate.attach(feed)
        feed.on(ev.GOAL_SCORED, self._on_goal)
        return self

    def _on_goal(self, data: dict) -> None:
        if not self.gate.active:
            log.debug("ignoring goal outside a real match (freeplay/training)")
            return
        now = time.monotonic()
        if self._last_goal_mono is not None and now - self._last_goal_mono < self.min_gap:
            log.debug("debounced goal within %.1fs of the previous", self.min_gap)
            return
        self._last_goal_mono = now
        scorer = (data.get("scorer") or {}).get("name")
        goal = self.session.log_goal(
            scorer=scorer,
            team=data.get("team"),
            goal_speed=data.get("goal_speed"),
            is_overtime=bool(data.get("is_overtime")),
        )
        self.session.save(self.save_path)
        log.info("goal #%d by %s -> %.1fs into the video",
                 len(self.session.goals), scorer or "?", goal.position_seconds)


def run(config: dict, video_path: str | None, name: str | None) -> str:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    save_path = _default_session_path(config, name)
    session = SyncSession.start_now(video_path=video_path)
    session.save(save_path)

    log.info("=" * 58)
    log.info(">> RECORDING SESSION STARTED - start your capture NOW")
    log.info("   zero point: %s", session.created_at)
    log.info("   session file: %s", save_path)
    log.info("=" * 58)

    feed = make_feed(config)
    ignore = tuple(config.get("ignore_playlists") or DEFAULT_IGNORE_PLAYLISTS)
    HighlightRecorder(session, save_path, MatchGate(ignore)).attach(feed)
    try:
        feed.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        feed.stop()
        session.save(save_path)
    log.info("session saved with %d goal(s): %s", len(session.goals), save_path)
    if session.goals:
        log.info("build the reel with:  python rl.py hl-build \"%s\" <video-file>", save_path)
    return save_path


def run_log(config: dict, name: str | None = None) -> str:
    """Log goal timestamps while you play; pair with your own OBS/ShadowPlay recording.

    Unlike ``run`` (which assumes you start a capture at the same instant), this
    just records each goal's absolute time. ``hl-cut`` later matches those goals
    to whatever video you recorded by their timestamps — no manual syncing.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    save_path = _default_session_path(config, name)
    session = SyncSession.start_now()
    session.save(save_path)

    log.info("=" * 60)
    log.info(">> Logging goals. Just play — record with OBS/ShadowPlay as usual.")
    log.info("   When you're done, run:  python rl.py hl-cut \"<your video file>\"")
    log.info("   (Ctrl+C to stop. log file: %s)", save_path)
    log.info("=" * 60)

    feed = make_feed(config)
    ignore = tuple(config.get("ignore_playlists") or DEFAULT_IGNORE_PLAYLISTS)

    class _Logger(HighlightRecorder):
        def _on_goal(self, data: dict) -> None:
            if not self.gate.active:
                return
            import time as _t
            now = _t.monotonic()
            if self._last_goal_mono is not None and now - self._last_goal_mono < self.min_gap:
                return
            self._last_goal_mono = now
            goal = self.session.log_goal(scorer=(data.get("scorer") or {}).get("name"),
                                         team=data.get("team"),
                                         goal_speed=data.get("goal_speed"))
            self.session.save(self.save_path)
            log.info("goal #%d by %s logged at %s",
                     len(self.session.goals), goal.scorer or "?",
                     _ts(goal.event_epoch))

    _Logger(session, save_path, MatchGate(ignore)).attach(feed)
    try:
        feed.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        feed.stop()
        session.save(save_path)
    log.info("logged %d goal(s): %s", len(session.goals), save_path)
    return save_path


def _ts(epoch: float) -> str:
    import time as _t
    return _t.strftime("%H:%M:%S", _t.localtime(epoch))


def main(argv=None) -> None:
    config = load_config()
    p = argparse.ArgumentParser(description="Record goal timings for highlight editing.")
    p.add_argument("--start", action="store_true",
                   help="start a new session now (the video's zero point).")
    p.add_argument("--video", help="path to the recording (optional; can be given at build time).")
    p.add_argument("--name", help="session file name (default: timestamp).")
    args = p.parse_args(argv)
    # --start is the only mode today; accept it implicitly too.
    run(config, args.video, args.name)


if __name__ == "__main__":
    main()
