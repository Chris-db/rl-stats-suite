"""One-command auto-highlighter.

Records your screen, logs every goal against that recording, and when the match
ends (or you press Ctrl+C) automatically cuts a reel of the goal moments.

    python rl.py hl-auto                 # record + auto-build on match end
    python rl.py hl-auto --pre 6 --post 4
    python rl.py hl-auto --no-build      # just record + log goals, build later

Because the tool starts the recording itself, the video's t=0 and the goal clock
are the same instant — no manual syncing. A small startup offset
(highlight_capture_sync_offset) compensates for ffmpeg's spin-up; tune it if
clips land slightly early or late.
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time

from rlstats import events as ev, load_config, make_feed
from rlstats.matchstate import MatchGate, DEFAULT_IGNORE_PLAYLISTS
from .sync import SyncSession
from .recorder import HighlightRecorder
from .capture import ScreenRecorder
from .editor import find_tool, build_reel, FFmpegNotFound

log = logging.getLogger("rlstats.highlights.auto")


def run(config: dict, name: str | None = None, *, pre: float | None = None,
        post: float | None = None, build: bool = True,
        duration: float | None = None) -> str | None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    ffmpeg = find_tool("ffmpeg", config.get("ffmpeg_path"))
    if not ffmpeg:
        log.error("ffmpeg not found. Install it (winget install Gyan.FFmpeg) and "
                  "open a fresh terminal, then try again.")
        raise SystemExit(1)

    pre = config["highlight_pre_seconds"] if pre is None else pre
    post = config["highlight_post_seconds"] if post is None else post
    offset = config.get("highlight_capture_sync_offset", -0.5)

    rec_dir = config["highlight_recordings_dir"]
    sess_dir = config["highlight_sessions_dir"]
    os.makedirs(rec_dir, exist_ok=True)
    os.makedirs(sess_dir, exist_ok=True)
    stamp = name or time.strftime("match_%Y%m%d_%H%M%S")
    video_path = os.path.join(rec_dir, stamp + ".mkv")
    session_path = os.path.join(sess_dir, stamp + ".json")

    recorder = ScreenRecorder(ffmpeg, config.get("highlight_capture_fps", 30),
                              config.get("highlight_capture_window"))
    ignore = tuple(config.get("ignore_playlists") or DEFAULT_IGNORE_PLAYLISTS)

    log.info("=" * 60)
    target = recorder.window_title or "the whole desktop"
    log.info(">> Starting screen capture (%s) - play your match!", target)
    try:
        t0 = recorder.start(video_path)
    except RuntimeError as exc:
        if recorder.window_title:
            log.warning("window capture failed (%s).", exc)
            log.warning("Falling back to full desktop. Tip: run Rocket League in "
                        "borderless/windowed so its window can be captured.")
            recorder = ScreenRecorder(ffmpeg, config.get("highlight_capture_fps", 30), None)
            t0 = recorder.start(video_path)
        else:
            raise
    session = SyncSession(recording_start_epoch=t0, video_path=video_path)
    session.save(session_path)
    log.info("   recording to: %s", video_path)
    log.info("   goals will be clipped %.0fs before -> %.0fs after", pre, post)
    log.info("   (auto-builds the reel when the match ends; Ctrl+C to stop early)")
    log.info("=" * 60)

    feed = make_feed(config)
    HighlightRecorder(session, session_path, MatchGate(ignore)).attach(feed)
    done = threading.Event()
    feed.on(ev.MATCH_ENDED, lambda _d: done.set())
    feed.start()

    try:
        done.wait(timeout=duration)
    except KeyboardInterrupt:
        log.info("stopping early…")
    finally:
        feed.stop()
        recorder.stop()
        session.save(session_path)

    log.info("captured %d goal(s); video saved: %s", len(session.goals), video_path)

    if not build:
        if session.goals:
            log.info("build later with:  python rl.py hl-build \"%s\" \"%s\"",
                     session_path, video_path)
        return None
    if not session.goals:
        log.info("no goals captured — no reel built (your video is still saved).")
        return None

    out_path = os.path.join(rec_dir, stamp + "_reel.mp4")
    try:
        build_reel(session, video_path, out_path, pre=pre, post=post,
                   offset=offset, config=config)
    except (FFmpegNotFound, FileNotFoundError, ValueError) as exc:
        log.error("reel build failed: %s", exc)
        return None
    return out_path


def main(argv=None) -> None:
    config = load_config()
    p = argparse.ArgumentParser(description="Record + auto-clip goal highlights.")
    p.add_argument("--name", help="base name for the video/session/reel files.")
    p.add_argument("--pre", type=float, help="seconds to keep before each goal.")
    p.add_argument("--post", type=float, help="seconds to keep after each goal.")
    p.add_argument("--no-build", dest="build", action="store_false",
                   help="record + log goals but don't auto-cut the reel.")
    p.add_argument("--duration", type=float,
                   help="auto-stop after N seconds (default: until match ends/Ctrl+C).")
    p.add_argument("--window", help="capture only this window title.")
    p.add_argument("--desktop", action="store_true",
                   help="capture the whole desktop instead of a single window.")
    args = p.parse_args(argv)
    if args.desktop:
        config["highlight_capture_window"] = None
    elif args.window:
        config["highlight_capture_window"] = args.window
    out = run(config, args.name, pre=args.pre, post=args.post,
              build=args.build, duration=args.duration)
    if out:
        log.info("DONE — highlight reel: %s", out)


if __name__ == "__main__":
    main()
