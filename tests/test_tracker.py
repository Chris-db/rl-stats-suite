"""Tests for Tool 1: db schema, recorder logic, and analytics queries."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tracker import db
from tracker.recorder import build_match_rows, MatchRecorder


def sample_match_ended(winner=0, arena="DFH Stadium", local_saves=2, local_goals=1):
    return {
        "arena": arena, "playlist": "Ranked Doubles", "duration_seconds": 300.0,
        "winner_team": winner,
        "teams": [{"team": 0, "score": 3 if winner == 0 else 1},
                  {"team": 1, "score": 1 if winner == 0 else 3}],
        "players": [
            {"id": "b0", "name": "You", "team": 0, "is_local": True, "score": 300,
             "goals": local_goals, "shots": 3, "saves": local_saves, "assists": 1,
             "demos": 0, "boost_used": 540},
            {"id": "b1", "name": "Nitro", "team": 0, "is_local": False, "score": 250,
             "goals": 1, "shots": 2, "saves": 1, "assists": 0, "demos": 1,
             "boost_used": 600},
            {"id": "o0", "name": "Octane", "team": 1, "is_local": False, "score": 200,
             "goals": 1, "shots": 4, "saves": 0, "assists": 1, "demos": 2,
             "boost_used": 700},
            {"id": "o1", "name": "Dominus", "team": 1, "is_local": False, "score": 180,
             "goals": 0, "shots": 1, "saves": 2, "assists": 0, "demos": 0,
             "boost_used": 480},
        ],
    }


class BuildRowsTest(unittest.TestCase):
    def test_win_and_score_attribution(self):
        match, players = build_match_rows(sample_match_ended(winner=0), "You")
        self.assertEqual(match["won"], 1)
        self.assertEqual(match["team_score"], 3)
        self.assertEqual(match["opponent_score"], 1)
        self.assertEqual(match["local_player"], "You")
        local = [p for p in players if p["is_local"]]
        self.assertEqual(len(local), 1)
        self.assertEqual(local[0]["name"], "You")

    def test_loss_attribution(self):
        match, _ = build_match_rows(sample_match_ended(winner=1), "You")
        self.assertEqual(match["won"], 0)
        self.assertEqual(match["team_score"], 1)
        self.assertEqual(match["opponent_score"], 3)

    def test_boost_used_fallback_to_accumulator(self):
        data = sample_match_ended()
        for p in data["players"]:
            p.pop("boost_used")
        _, players = build_match_rows(data, "You", boost_used={"b0": 333.4})
        local = next(p for p in players if p["is_local"])
        self.assertEqual(local["boost_used"], 333.4)


class RecorderBoostAccumulationTest(unittest.TestCase):
    def test_accumulates_boost_decreases(self):
        conn = db.connect(":memory:")
        rec = MatchRecorder(conn, "You")
        rec._on_match_created({})
        # boost goes 100 -> 60 -> 80 -> 30  => consumed 40 + 50 = 90
        for boost in (100, 60, 80, 30):
            rec._on_update({"players": [{"id": "b0", "boost": boost}]})
        self.assertAlmostEqual(rec._consumed["b0"], 90.0)


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def _insert(self, played_at, winner=0, arena="DFH Stadium", saves=2):
        match, players = build_match_rows(
            sample_match_ended(winner=winner, arena=arena, local_saves=saves), "You")
        match["played_at"] = played_at
        return db.insert_match(self.conn, match, players)

    def test_overview_and_winrate(self):
        base = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
        self._insert((base).isoformat(), winner=0)
        self._insert((base + timedelta(minutes=8)).isoformat(), winner=1)
        self._insert((base + timedelta(minutes=16)).isoformat(), winner=0)

        o = db.overview(self.conn)
        self.assertEqual(o["matches"], 3)
        self.assertEqual(o["wins"], 2)
        self.assertEqual(o["losses"], 1)
        self.assertAlmostEqual(o["win_rate"], 2 / 3)

        wr = db.win_rate_over_time(self.conn)
        self.assertEqual([round(p["cumulative_win_rate"], 3) for p in wr],
                         [1.0, 0.5, round(2 / 3, 3)])

    def test_arena_grouping(self):
        base = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
        self._insert(base.isoformat(), winner=0, arena="Mannfield")
        self._insert((base + timedelta(minutes=8)).isoformat(), winner=1, arena="Mannfield")
        self._insert((base + timedelta(minutes=16)).isoformat(), winner=0, arena="Wasteland")
        arenas = {a["arena"]: a for a in db.performance_by_arena(self.conn)}
        self.assertEqual(arenas["Mannfield"]["matches"], 2)
        self.assertAlmostEqual(arenas["Mannfield"]["win_rate"], 0.5)
        self.assertAlmostEqual(arenas["Wasteland"]["win_rate"], 1.0)

    def test_session_grouping(self):
        base = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
        # Two matches close together, then a 2h gap, then one more = 2 sessions.
        self._insert(base.isoformat(), winner=0)
        self._insert((base + timedelta(minutes=8)).isoformat(), winner=0)
        self._insert((base + timedelta(hours=2)).isoformat(), winner=1)
        sessions = db.session_summaries(self.conn)
        self.assertEqual(len(sessions), 2)
        # Most recent first: the lone later match.
        self.assertEqual(sessions[0]["matches"], 1)
        self.assertEqual(sessions[1]["matches"], 2)


if __name__ == "__main__":
    unittest.main()
