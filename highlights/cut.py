"""Cut a highlight reel from YOUR OWN recording (OBS / ShadowPlay / Game Bar).

This is the lean, reliable highlighter: you record however you like, a goal-logger
runs in the background while you play, and this matches the two automatically — no
manual syncing and no screen capture by us.

How it works: every recording carries a start time (creation_time metadata). We
log each goal's absolute time. So a goal's position in the video is simply
``goal_time − video_start_time``. We even figure out *which* logged goals belong
to a video by their timestamps falling inside the video's span.

    python rl.py hl-cut "C:\\Videos\\match.mp4"            # auto-match + cut
    python rl.py hl-cut match.mp4 --session <file.json>    # use a specific log
    python rl.py hl-cut match.mp4 --dry-run                 # show the plan only
    python rl.py hl-cut match.mp4 --offset -1.5            # nudge all clips
"""

from __future__ import annotations

import argparse
import logging
import os

from rlstats import load_config
from .sync import SyncSession, load_sessions, goals_in_window
from .editor import (find_tool, probe_duration, creation_time_epoch,
                     build_reel, FFmpegNotFound)

log = logging.getLogger("rlstats.highlights.cut")


def best_anchor(sessions: list[dict], candidates: list[tuple[float, str]],
                duration: float) -> tuple[float | None, str, list[dict]]:
    """Pick the recording-start guess whose window contains the most logged goals.

    Different recorders timestamp files differently: OBS "Start Recording" stamps
    the START, while a ShadowPlay/Game Bar replay-buffer clip effectively ends at
    its timestamp. We try each interpretation and use whichever lines up with the
    goals you actually logged.
    """
    best: tuple[float | None, str, list[dict]] = (None, "", [])
    for start, label in candidates:
        goals = goals_in_window(sessions, start, start + duration)
        if len(goals) > len(best[2]):
            best = (start, label, goals)
    return best


def run(config: dict, video: str, *, session_path: str | None = None,
        pre: float | None = None, post: float | None = None, offset: float = 0.0,
        out: str | None = None, dry_run: bool = False) -> str | None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pre = config["highlight_pre_seconds"] if pre is None else pre
    post = config["highlight_post_seconds"] if post is None else post

    if not os.path.isfile(video):
        log.error("video not found: %s", video)
        raise SystemExit(1)

    ffmpeg = find_tool("ffmpeg", config.get("ffmpeg_path"))
    ffprobe = find_tool("ffprobe")
    if not ffmpeg and not dry_run:
        log.error("ffmpeg not found. Install it (winget install Gyan.FFmpeg).")
        raise SystemExit(1)

    duration = probe_duration(video, ffprobe) or 0.0

    # Gather candidate logs.
    if session_path:
        sessions = [_load_one(session_path, config)]
    else:
        sessions = load_sessions(config["highlight_sessions_dir"])

    # Candidate recording-start times, covering both "timestamp = start" (OBS)
    # and "timestamp = end / replay buffer" (ShadowPlay Instant Replay, Game Bar).
    ct = creation_time_epoch(video, ffprobe)
    candidates: list[tuple[float, str]] = []
    if ct is not None:
        candidates.append((ct, "recording start (metadata)"))
        if duration:
            candidates.append((ct - duration, "replay-buffer clip (metadata = end)"))
    try:
        candidates.append((os.path.getctime(video), "file created"))
    except OSError:
        pass
    try:
        if duration:
            candidates.append((os.path.getmtime(video) - duration, "file finished (mtime - duration)"))
    except OSError:
        pass

    start_epoch, label, goals = best_anchor(sessions, candidates, duration)
    if not goals:
        _no_match_diagnostic(sessions, candidates, duration)
        raise SystemExit(1)
    log.info("video start: %s  (%s); duration %.0fs", _fmt(start_epoch), label, duration)
    log.info("matched %d goal(s) to this recording", len(goals))

    # Re-anchor the goals to the video's start and cut.
    session = SyncSession(recording_start_epoch=start_epoch, video_path=video)
    for g in goals:
        session.log_goal(scorer=g.get("scorer"), team=g.get("team"),
                         event_epoch=g["event_epoch"])

    out = out or os.path.splitext(video)[0] + "_reel.mp4"
    try:
        build_reel(session, video, out, pre=pre, post=post, offset=offset,
                   config=config, dry_run=dry_run)
    except (FFmpegNotFound, FileNotFoundError, ValueError) as exc:
        log.error("error: %s", exc)
        raise SystemExit(1)
    return None if dry_run else out


def _no_match_diagnostic(sessions: list[dict], candidates: list[tuple[float, str]],
                         duration: float) -> None:
    log.error("no logged goals line up with this video. Time windows I checked:")
    for start, label in candidates:
        log.error("   %s  ->  %s   (%s)", _fmt(start), _fmt(start + duration), label)
    all_goals = sorted(
        (g for s in sessions for g in s.get("goals", []) if g.get("event_epoch")),
        key=lambda g: g["event_epoch"])
    if all_goals:
        log.error("Your most recent logged goals were at:")
        for g in all_goals[-5:]:
            log.error("   %s  %s", _fmt(g["event_epoch"]), g.get("scorer") or "?")
        log.error("They don't fall inside this video. The recording and the goal-logger")
        log.error("must both be running AT THE SAME TIME as the goals.")
    else:
        log.error("No goals have been logged at all. Run '1. Log Goals' while you play.")


def _load_one(path: str, config: dict) -> dict:
    import json
    if not os.path.isfile(path):
        path = os.path.join(config["highlight_sessions_dir"], path)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _fmt(epoch: float) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def main(argv=None) -> None:
    config = load_config()
    p = argparse.ArgumentParser(description="Cut a highlight reel from your own recording.")
    p.add_argument("video", help="the video file you recorded (OBS/ShadowPlay/etc).")
    p.add_argument("--session", help="use a specific goal-log JSON (default: auto-match).")
    p.add_argument("--out", help="output reel path (default: <video>_reel.mp4).")
    p.add_argument("--pre", type=float, help="seconds before each goal.")
    p.add_argument("--post", type=float, help="seconds after each goal.")
    p.add_argument("--offset", type=float, default=config.get("highlight_offset", 0.0),
                   help="shift all clips N seconds (negative = earlier). "
                        "Default comes from config 'highlight_offset'.")
    p.add_argument("--dry-run", action="store_true", help="show the plan, don't cut.")
    args = p.parse_args(argv)
    out = run(config, args.video, session_path=args.session, pre=args.pre,
              post=args.post, offset=args.offset, out=args.out, dry_run=args.dry_run)
    if out:
        log.info("DONE - highlight reel: %s", out)


if __name__ == "__main__":
    main()
