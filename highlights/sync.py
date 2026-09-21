"""Timeline sync — the heart of the Goal Highlight Auto-Editor.

The Stats API knows *when* goals happen (system clock) but knows nothing about
the video. We bridge the two clocks with a single reference point:

    recording_start_epoch  -> the video's zero point (t=0 in the file)
    goal position_in_video  = goal_event_epoch - recording_start_epoch

Everything downstream (ffmpeg cutting and joining) is mechanical. The whole
tool's reliability rests on this offset being correct, so it lives here, alone,
with no I/O beyond load/save — easy to reason about and test.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


@dataclass
class Goal:
    event_epoch: float          # system clock when the GoalScored event fired
    position_seconds: float     # where it lands in the video (event - start)
    scorer: str | None = None
    team: int | None = None
    goal_speed: float | None = None
    is_overtime: bool = False


@dataclass
class SyncSession:
    """A recording session: one video clock + the goals logged against it."""

    recording_start_epoch: float
    video_path: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    goals: list[Goal] = field(default_factory=list)

    # --- construction -----------------------------------------------------

    @classmethod
    def start_now(cls, video_path: str | None = None) -> "SyncSession":
        """Begin a session whose zero point is *this instant*.

        Call this at the same moment you start the OBS/screen recording. Any gap
        between the two becomes the sync error; correct residual drift later with
        the editor's ``--offset``.
        """
        return cls(recording_start_epoch=_now_epoch(), video_path=video_path)

    # --- logging ----------------------------------------------------------

    def log_goal(
        self,
        scorer: str | None = None,
        team: int | None = None,
        goal_speed: float | None = None,
        is_overtime: bool = False,
        event_epoch: float | None = None,
    ) -> Goal:
        """Record a goal at ``event_epoch`` (defaults to now) and place it."""
        event_epoch = _now_epoch() if event_epoch is None else event_epoch
        goal = Goal(
            event_epoch=event_epoch,
            position_seconds=round(event_epoch - self.recording_start_epoch, 3),
            scorer=scorer, team=team, goal_speed=goal_speed, is_overtime=is_overtime,
        )
        self.goals.append(goal)
        return goal

    def positions(self) -> list[float]:
        return [g.position_seconds for g in self.goals]

    # --- persistence ------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recording_start_iso"] = datetime.fromtimestamp(
            self.recording_start_epoch, tz=timezone.utc).isoformat(timespec="seconds")
        return d

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        return path

    @classmethod
    def load(cls, path: str) -> "SyncSession":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        goals = [Goal(**g) for g in data.get("goals", [])]
        return cls(
            recording_start_epoch=data["recording_start_epoch"],
            video_path=data.get("video_path"),
            created_at=data.get("created_at", ""),
            goals=goals,
        )


def load_sessions(directory: str) -> list[dict]:
    """Load every session JSON in a directory (skips unreadable ones)."""
    sessions = []
    if not os.path.isdir(directory):
        return sessions
    for fn in os.listdir(directory):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, fn), "r", encoding="utf-8") as fh:
                sessions.append(json.load(fh))
        except (OSError, ValueError):
            continue
    return sessions


def goals_in_window(sessions: list[dict], start_epoch: float, end_epoch: float,
                    margin: float = 15.0) -> list[dict]:
    """Pick logged goals whose absolute time falls within a video's span.

    This is how a recording is matched to its goals automatically: any goal
    timestamped between the video's start and end (plus a margin) belongs to it.
    Returns goal dicts sorted by time, de-duplicated.
    """
    picked: dict[float, dict] = {}
    for session in sessions:
        for goal in session.get("goals", []):
            epoch = goal.get("event_epoch")
            if epoch is None:
                continue
            if start_epoch - margin <= epoch <= end_epoch + margin:
                picked[round(epoch, 2)] = goal
    return [picked[k] for k in sorted(picked)]


@dataclass
class Clip:
    start: float
    end: float
    goals: list[int] = field(default_factory=list)   # indices of goals inside

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def plan_clips(
    positions: list[float],
    pre_seconds: float = 8.0,
    post_seconds: float = 5.0,
    offset: float = 0.0,
    video_duration: float | None = None,
    merge: bool = True,
) -> list[Clip]:
    """Turn goal positions into clip windows.

    Each goal becomes ``[pos - pre, pos + post]``, shifted by ``offset`` to
    correct residual sync drift, clamped to the video, and (by default)
    overlapping windows are merged so footage isn't repeated.
    """
    windows: list[Clip] = []
    for i, pos in enumerate(positions):
        center = pos + offset
        start = max(0.0, center - pre_seconds)
        end = center + post_seconds
        if video_duration is not None:
            end = min(end, video_duration)
            if start >= video_duration:
                continue            # goal lands past the end of the footage
        if end <= start:
            continue
        windows.append(Clip(round(start, 3), round(end, 3), [i]))

    if not merge or not windows:
        return windows

    windows.sort(key=lambda c: c.start)
    merged = [windows[0]]
    for clip in windows[1:]:
        last = merged[-1]
        if clip.start <= last.end:                  # overlap or touch -> merge
            last.end = max(last.end, clip.end)
            last.goals.extend(clip.goals)
        else:
            merged.append(clip)
    return merged
