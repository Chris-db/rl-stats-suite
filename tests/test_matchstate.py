"""Tests for the real-match filter (freeplay/training guard)."""

from __future__ import annotations

import os
import tempfile
import unittest

from rlstats import events as ev
from rlstats.matchstate import is_real_match, MatchGate
from tracker import db
from tracker.recorder import MatchRecorder
from highlights.recorder import HighlightRecorder
from highlights.sync import SyncSession


def two_team_players():
    return [
        {"id": "b0", "name": "You", "team": 0, "is_local": True},
        {"id": "o0", "name": "Octane", "team": 1, "is_local": False},
    ]


def solo_player():
    return [{"id": "b0", "name": "You", "team": 0, "is_local": True}]


class IsRealMatchTest(unittest.TestCase):
    def test_two_teams_is_real(self):
        self.assertTrue(is_real_match(two_team_players(), "Ranked Doubles"))

    def test_solo_is_not_real(self):
        self.assertFalse(is_real_match(solo_player(), None))

    def test_freeplay_playlist_excluded(self):
        # even if it somehow reported two teams, the name rules it out
        self.assertFalse(is_real_match(two_team_players(), "Freeplay"))

    def test_training_excluded(self):
        self.assertFalse(is_real_match(two_team_players(), "Training Pack"))


class MatchGateTest(unittest.TestCase):
    def test_active_only_during_real_match(self):
        gate = MatchGate()
        self.assertFalse(gate.active)
        gate._on_created({"playlist": "Ranked Doubles"})
        gate._on_update({"game": {"playlist": "Ranked Doubles"}, "players": two_team_players()})
        self.assertTrue(gate.active)
        gate._on_finished({})
        self.assertFalse(gate.active)

    def test_freeplay_never_active(self):
        gate = MatchGate()
        gate._on_update({"game": {"playlist": "Freeplay"}, "players": solo_player()})
        self.assertFalse(gate.active)


class TrackerIgnoresFreeplayTest(unittest.TestCase):
    def test_freeplay_match_ended_not_recorded(self):
        conn = db.connect(":memory:")
        rec = MatchRecorder(conn, "You")
        freeplay = {"playlist": "Freeplay", "winner_team": None,
                    "teams": [{"team": 0, "score": 0}], "players": solo_player()}
        self.assertIsNone(rec._on_match_ended(freeplay))
        self.assertEqual(db.overview(conn)["matches"], 0)

    def test_real_match_recorded(self):
        conn = db.connect(":memory:")
        rec = MatchRecorder(conn, "You")
        real = {"playlist": "Ranked Doubles", "winner_team": 0,
                "teams": [{"team": 0, "score": 2}, {"team": 1, "score": 1}],
                "players": two_team_players()}
        self.assertIsNotNone(rec._on_match_ended(real))
        self.assertEqual(db.overview(conn)["matches"], 1)


class HighlightIgnoresFreeplayTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "s.json")
        self.session = SyncSession(recording_start_epoch=0.0)
        self.rec = HighlightRecorder(self.session, self.path)

    def test_goal_ignored_when_no_real_match(self):
        # gate never activated -> freeplay shot must not be logged
        self.rec._on_goal({"scorer": {"name": "You"}, "team": 0})
        self.assertEqual(len(self.session.goals), 0)

    def test_goal_logged_during_real_match(self):
        self.rec.gate._on_created({"playlist": "Ranked Doubles"})
        self.rec.gate._on_update({"game": {"playlist": "Ranked Doubles"},
                                  "players": two_team_players()})
        self.rec._on_goal({"scorer": {"name": "You"}, "team": 0, "goal_speed": 90})
        self.assertEqual(len(self.session.goals), 1)

    def test_rapid_duplicate_goals_debounced(self):
        self.rec.gate._on_created({"playlist": "Ranked Doubles"})
        self.rec.gate._on_update({"game": {"playlist": "Ranked Doubles"},
                                  "players": two_team_players()})
        # two goals in the same instant -> only the first is logged
        self.rec._on_goal({"scorer": {"name": "You"}, "team": 0})
        self.rec._on_goal({"scorer": {"name": "You"}, "team": 0})
        self.assertEqual(len(self.session.goals), 1)


if __name__ == "__main__":
    unittest.main()
