"""Goal highlight editor — cut windows around each goal and stitch a reel.

Given a sync session (goal positions in the video) and the video file, this asks
ffmpeg to cut a window around each goal and concatenate the clips into one
highlight reel. The sync work is already done in ``highlights.sync``; this part
is purely mechanical.

    python rl.py hl-build <session.json> <video> --out reel.mp4
    python rl.py hl-build <session.json> <video> --offset -0.4   # nudge timing
    python rl.py hl-build <session.json> <video> --dry-run        # just show the plan

ffmpeg (and ffprobe) must be installed and on PATH, or set ``ffmpeg_path`` in
config. ``--dry-run`` needs neither and is handy for checking the cut plan.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
import tempfile

from rlstats import load_config
from .sync import SyncSession, plan_clips, Clip

log = logging.getLogger("rlstats.highlights.editor")


class FFmpegNotFound(RuntimeError):
    pass


def find_tool(name: str, configured: str | None = None) -> str | None:
    """Locate ffmpeg/ffprobe. Returns a path or None."""
    if configured and name == "ffmpeg":
        if os.path.isfile(configured):
            return configured
        found = shutil.which(configured)
        if found:
            return found
    return shutil.which(name)


def probe_duration(video: str, ffprobe: str | None) -> float | None:
    """Return the video's duration in seconds via ffprobe, or None."""
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def parse_iso_epoch(value: str | None) -> float | None:
    """Parse an ISO-8601 timestamp (e.g. ffprobe creation_time) to a UTC epoch."""
    if not value:
        return None
    s = value.strip().replace("Z", "+00:00")
    # ffprobe sometimes emits more than 6 fractional digits; trim to micros.
    if "." in s:
        head, _, tail = s.partition(".")
        digits = ""
        rest = ""
        for i, ch in enumerate(tail):
            if ch.isdigit() and i < 9:
                digits += ch
            else:
                rest = tail[i:]
                break
        s = f"{head}.{digits[:6]}{rest}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def creation_time_epoch(video: str, ffprobe: str | None) -> float | None:
    """The recording's start time from the file's creation_time metadata (UTC)."""
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format_tags=creation_time",
             "-of", "default=noprint_wrappers=1:nokey=1", video],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return parse_iso_epoch(out.stdout.strip())


def video_start_epoch(video: str, ffprobe: str | None) -> tuple[float | None, str]:
    """Best estimate of when the recording started, as a wall-clock epoch.

    Tries, in order: the file's ``creation_time`` metadata (OBS/ShadowPlay write
    this), the filesystem creation time, then modified-time minus duration.
    Returns (epoch, source).
    """
    ct = creation_time_epoch(video, ffprobe)
    if ct:
        return ct, "metadata"
    try:
        return os.path.getctime(video), "file-created"
    except OSError:
        pass
    dur = probe_duration(video, ffprobe)
    try:
        if dur is not None:
            return os.path.getmtime(video) - dur, "mtime-duration"
    except OSError:
        pass
    return None, "unknown"


def format_plan(clips: list[Clip], total_goals: int) -> str:
    lines = [f"Highlight plan: {len(clips)} clip(s) from {total_goals} goal(s)"]
    total = 0.0
    for i, c in enumerate(clips, 1):
        total += c.duration
        tag = f"goals {', '.join('#' + str(g + 1) for g in c.goals)}"
        lines.append(f"  clip {i:>2}: {c.start:8.2f}s -> {c.end:8.2f}s "
                     f"({c.duration:5.1f}s)  [{tag}]")
    lines.append(f"  total reel length: ~{total:.1f}s")
    return "\n".join(lines)


def _run(cmd: list[str]) -> None:
    log.debug("run: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def build_reel(
    session: SyncSession,
    video: str,
    out_path: str,
    *,
    pre: float = 8.0,
    post: float = 5.0,
    offset: float = 0.0,
    merge: bool = True,
    reencode: bool = True,
    config: dict | None = None,
    dry_run: bool = False,
) -> list[Clip]:
    """Cut and concatenate the highlight reel. Returns the clip plan."""
    config = config or {}
    ffmpeg = find_tool("ffmpeg", config.get("ffmpeg_path"))
    ffprobe = find_tool("ffprobe")

    if not session.goals:
        raise ValueError("session has no goals — nothing to build")

    duration = probe_duration(video, ffprobe) if not dry_run else None
    clips = plan_clips(session.positions(), pre, post, offset, duration, merge)
    if not clips:
        raise ValueError("no clips in range — check --offset and the video file")

    log.info("\n%s", format_plan(clips, len(session.goals)))

    if dry_run:
        return clips

    if not ffmpeg:
        raise FFmpegNotFound(
            "ffmpeg not found. Install it and ensure it's on PATH, or set "
            "'ffmpeg_path' in config.json. On Windows: `winget install Gyan.FFmpeg`. "
            "(Use --dry-run to preview the cut plan without ffmpeg.)"
        )
    if not os.path.isfile(video):
        raise FileNotFoundError(f"video not found: {video}")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="rl_highlights_")
    try:
        clip_files = []
        for i, clip in enumerate(clips):
            clip_path = os.path.join(tmp, f"clip_{i:03d}.mp4")
            # -ss before -i = fast seek; re-encode for frame-accurate cuts.
            cmd = [ffmpeg, "-y", "-ss", f"{clip.start:.3f}", "-i", video,
                   "-t", f"{clip.duration:.3f}"]
            if reencode:
                cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-c:a", "aac", "-b:a", "160k"]
            else:
                cmd += ["-c", "copy"]
            cmd.append(clip_path)
            log.info("cutting clip %d/%d (%.1fs)…", i + 1, len(clips), clip.duration)
            _run(cmd)
            clip_files.append(clip_path)

        # concat demuxer: stream-copy the (uniformly encoded) clips together.
        list_path = os.path.join(tmp, "clips.txt")
        with open(list_path, "w", encoding="utf-8") as fh:
            for cf in clip_files:
                fh.write(f"file '{cf.replace(chr(92), '/')}'\n")
        log.info("stitching %d clips -> %s", len(clip_files), out_path)
        _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
              "-c", "copy", out_path])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    log.info("Done - highlight reel written: %s", out_path)
    return clips


def _resolve_session_path(config: dict, value: str) -> str:
    if os.path.isfile(value):
        return value
    candidate = os.path.join(config["highlight_sessions_dir"], value)
    if not candidate.endswith(".json"):
        candidate += ".json"
    if os.path.isfile(candidate):
        return candidate
    raise FileNotFoundError(f"session not found: {value}")


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load_config()
    p = argparse.ArgumentParser(description="Build a goal highlight reel with ffmpeg.")
    p.add_argument("session", help="session JSON path or name (from hl-record).")
    p.add_argument("video", nargs="?", help="the recorded video file.")
    p.add_argument("--out", default="highlights_reel.mp4", help="output reel path.")
    p.add_argument("--pre", type=float, default=config["highlight_pre_seconds"],
                   help="seconds to keep before each goal.")
    p.add_argument("--post", type=float, default=config["highlight_post_seconds"],
                   help="seconds to keep after each goal.")
    p.add_argument("--offset", type=float, default=0.0,
                   help="shift all clips by N seconds to correct sync drift.")
    p.add_argument("--no-merge", dest="merge", action="store_false",
                   help="keep a separate clip per goal even if windows overlap.")
    p.add_argument("--copy", dest="reencode", action="store_false",
                   help="stream-copy instead of re-encoding (faster, less accurate).")
    p.add_argument("--dry-run", action="store_true",
                   help="print the cut plan without running ffmpeg.")
    args = p.parse_args(argv)

    session_path = _resolve_session_path(config, args.session)
    session = SyncSession.load(session_path)
    video = args.video or session.video_path
    if not video and not args.dry_run:
        p.error("no video given and the session has no stored video_path")

    try:
        build_reel(session, video or "", args.out,
                   pre=args.pre, post=args.post, offset=args.offset,
                   merge=args.merge, reencode=args.reencode,
                   config=config, dry_run=args.dry_run)
    except (FFmpegNotFound, FileNotFoundError, ValueError) as exc:
        log.error("error: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
