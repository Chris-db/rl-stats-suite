"""Screen recording via ffmpeg (Windows gdigrab), with a known zero-point.

The auto-highlighter records the screen itself so the video's t=0 lines up with
the instant we start listening for goals — no manual syncing with OBS. We record
to .mkv because it stays playable even if the process is killed mid-capture.

Exclusive-fullscreen DX games can come out black under gdigrab; running Rocket
League in **borderless/windowed** is the reliable setup. Capturing the whole
desktop is the most robust target; a specific window title can be used instead.
"""

from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger("rlstats.highlights.capture")


class ScreenRecorder:
    def __init__(self, ffmpeg: str, fps: int = 30,
                 window_title: str | None = None) -> None:
        self.ffmpeg = ffmpeg
        self.fps = fps
        self.window_title = window_title
        self.proc: subprocess.Popen | None = None

    def build_cmd(self, out_path: str) -> list[str]:
        target = f"title={self.window_title}" if self.window_title else "desktop"
        return [
            self.ffmpeg, "-y",
            "-f", "gdigrab", "-framerate", str(self.fps), "-i", target,
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-crf", "23",
            out_path,
        ]

    def start(self, out_path: str) -> float:
        """Start capturing. Returns the wall-clock epoch used as the video's t=0."""
        cmd = self.build_cmd(out_path)
        log.debug("capture cmd: %s", " ".join(cmd))
        # stdin=PIPE so we can send 'q' for a clean stop; swallow ffmpeg's chatter.
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        start = time.time()
        # ffmpeg needs a moment to spin up gdigrab; give it a beat and verify.
        time.sleep(0.4)
        if self.proc.poll() is not None:
            raise RuntimeError(
                "screen capture failed to start (ffmpeg exited immediately). "
                "Check that ffmpeg supports gdigrab and a desktop session is available."
            )
        return start

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 10.0) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:                                   # 'q' = graceful finalize
                if self.proc.stdin:
                    self.proc.stdin.write(b"q")
                    self.proc.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        self.proc = None
