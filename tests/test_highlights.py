"""Tests for Tool 3: sync offset math, clip planning, persistence, dry-run."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from highlights import editor
from highlights.capture import ScreenRecorder
from highlights.sync import SyncSession, plan_clips, goals_in_window


class SyncMathTest(unittest.TestCase):
    def test_position_is_event_minus_start(self):
        s = SyncSession(recording_start_epoch=1000.0)
        g1 = s.log_goal(scorer="You", event_epoch=1012.5)
        g2 = s.log_goal(scorer="Nitro", event_epoch=1130.25)
        self.assertEqual(g1.position_seconds, 12.5)
        self.assertEqual(g2.position_seconds, 130.25)
        self.assertEqual(s.positions(), [12.5, 130.25])

    def test_start_now_is_recent(self):
        import time
        before = time.time()
        s = SyncSession.start_now()
        self.assertGreaterEqual(s.recording_start_epoch, before - 1)

    def test_save_load_round_trip(self):
        s = SyncSession(recording_start_epoch=2000.0, video_path="match.mkv")
        s.log_goal(scorer="You", team=0, goal_speed=92.1, event_epoch=2030.0)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sess.json")
            s.save(path)
            loaded = SyncSession.load(path)
        self.assertEqual(loaded.recording_start_epoch, 2000.0)
        self.assertEqual(loaded.video_path, "match.mkv")
        self.assertEqual(len(loaded.goals), 1)
        self.assertEqual(loaded.goals[0].position_seconds, 30.0)
        self.assertEqual(loaded.goals[0].goal_speed, 92.1)


class PlanClipsTest(unittest.TestCase):
    def test_single_goal_window(self):
        clips = plan_clips([100.0], pre_seconds=8, post_seconds=5, merge=True)
        self.assertEqual(len(clips), 1)
        self.assertEqual((clips[0].start, clips[0].end), (92.0, 105.0))
        self.assertEqual(clips[0].goals, [0])

    def test_clamp_at_zero(self):
        clips = plan_clips([3.0], pre_seconds=8, post_seconds=5)
        self.assertEqual(clips[0].start, 0.0)         # can't go before the video
        self.assertEqual(clips[0].end, 8.0)

    def test_clamp_at_video_end(self):
        clips = plan_clips([100.0], pre_seconds=8, post_seconds=5, video_duration=102.0)
        self.assertEqual(clips[0].end, 102.0)

    def test_goal_past_end_is_skipped(self):
        clips = plan_clips([500.0], video_duration=120.0)
        self.assertEqual(clips, [])

    def test_offset_shifts_window(self):
        clips = plan_clips([100.0], pre_seconds=8, post_seconds=5, offset=-2.0)
        self.assertEqual((clips[0].start, clips[0].end), (90.0, 103.0))

    def test_overlapping_windows_merge(self):
        # goals 5s apart with 8s pre + 5s post -> windows overlap -> one clip
        clips = plan_clips([100.0, 104.0], pre_seconds=8, post_seconds=5, merge=True)
        self.assertEqual(len(clips), 1)
        self.assertEqual((clips[0].start, clips[0].end), (92.0, 109.0))
        self.assertEqual(clips[0].goals, [0, 1])

    def test_no_merge_keeps_separate(self):
        clips = plan_clips([100.0, 104.0], pre_seconds=8, post_seconds=5, merge=False)
        self.assertEqual(len(clips), 2)

    def test_distant_goals_stay_separate(self):
        clips = plan_clips([30.0, 200.0], pre_seconds=8, post_seconds=5, merge=True)
        self.assertEqual(len(clips), 2)


class EditorTest(unittest.TestCase):
    def _session(self):
        s = SyncSession(recording_start_epoch=0.0)
        for pos in (20.0, 75.0, 140.0):
            s.log_goal(event_epoch=pos)
        return s

    def test_dry_run_returns_plan_without_ffmpeg(self):
        s = self._session()
        clips = editor.build_reel(s, "nonexistent.mkv", "out.mp4", dry_run=True)
        self.assertEqual(len(clips), 3)
        text = editor.format_plan(clips, len(s.goals))
        self.assertIn("3 clip(s) from 3 goal(s)", text)

    def test_missing_ffmpeg_raises(self):
        s = self._session()
        with mock.patch.object(editor, "find_tool", return_value=None):
            with self.assertRaises(editor.FFmpegNotFound):
                editor.build_reel(s, "video.mkv", "out.mp4", dry_run=False)

    def test_empty_session_raises(self):
        with self.assertRaises(ValueError):
            editor.build_reel(SyncSession(recording_start_epoch=0.0), "v.mkv", "o.mp4",
                              dry_run=True)


class CreationTimeTest(unittest.TestCase):
    def test_parse_iso_z(self):
        from datetime import datetime, timezone
        expected = datetime(2026, 6, 14, 19, 18, 42, tzinfo=timezone.utc).timestamp()
        e = editor.parse_iso_epoch("2026-06-14T19:18:42.000000Z")
        self.assertAlmostEqual(e, expected, delta=1)

    def test_parse_trims_long_fraction(self):
        # ffprobe sometimes emits 9 fractional digits
        self.assertIsNotNone(editor.parse_iso_epoch("2026-06-14T19:18:42.123456789Z"))

    def test_parse_none(self):
        self.assertIsNone(editor.parse_iso_epoch(""))
        self.assertIsNone(editor.parse_iso_epoch("not a date"))


class GoalsInWindowTest(unittest.TestCase):
    def _sessions(self):
        return [
            {"goals": [{"event_epoch": 1000.0, "scorer": "You"},
                       {"event_epoch": 1100.0, "scorer": "You"}]},
            {"goals": [{"event_epoch": 5000.0, "scorer": "Other"}]},   # different match
        ]

    def test_picks_goals_inside_video_span(self):
        goals = goals_in_window(self._sessions(), start_epoch=990.0, end_epoch=1200.0)
        self.assertEqual([g["event_epoch"] for g in goals], [1000.0, 1100.0])

    def test_excludes_goals_outside(self):
        goals = goals_in_window(self._sessions(), start_epoch=4990.0, end_epoch=5100.0)
        self.assertEqual([g["scorer"] for g in goals], ["Other"])

    def test_margin_allows_edge_goals(self):
        # a goal 10s before the recorded start still counts (margin=15)
        goals = goals_in_window(self._sessions(), start_epoch=1010.0, end_epoch=1050.0)
        self.assertIn(1000.0, [g["event_epoch"] for g in goals])

    def test_dedup_across_sessions(self):
        s = [{"goals": [{"event_epoch": 1000.0}]}, {"goals": [{"event_epoch": 1000.0}]}]
        self.assertEqual(len(goals_in_window(s, 900.0, 1100.0)), 1)


class BestAnchorTest(unittest.TestCase):
    def test_picks_end_anchor_for_replay_buffer(self):
        from highlights.cut import best_anchor
        sessions = [{"goals": [{"event_epoch": 1000.0}, {"event_epoch": 1100.0}]}]
        # "start" hypothesis window is empty; "end" (replay buffer) window has both
        cands = [(2000.0, "start"), (950.0, "replay-end")]
        start, label, goals = best_anchor(sessions, cands, duration=400.0)
        self.assertEqual(start, 950.0)
        self.assertEqual(label, "replay-end")
        self.assertEqual(len(goals), 2)

    def test_no_goals_returns_empty(self):
        from highlights.cut import best_anchor
        start, label, goals = best_anchor([{"goals": []}], [(0.0, "x")], 100.0)
        self.assertEqual(goals, [])


class ScreenRecorderCmdTest(unittest.TestCase):
    def test_desktop_target(self):
        cmd = ScreenRecorder("ffmpeg", 30, None).build_cmd("out.mkv")
        self.assertIn("gdigrab", cmd)
        self.assertIn("desktop", cmd)
        self.assertEqual(cmd[-1], "out.mkv")
        self.assertIn("30", cmd)

    def test_window_target(self):
        cmd = ScreenRecorder("ffmpeg", 60, "Rocket League").build_cmd("o.mkv")
        self.assertIn("title=Rocket League", cmd)
        self.assertIn("60", cmd)


if __name__ == "__main__":
    unittest.main()
