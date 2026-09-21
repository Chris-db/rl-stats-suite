"""Tests for the real-format -> canonical normalizer (and local identity)."""

from __future__ import annotations

import unittest

from rlstats.normalize import (
    friendly_arena, infer_playlist, LocalIdentity, normalize_update_state,
)


def real_players():
    return [
        {"Name": "Zeph .", "PrimaryId": "Epic|abc|0", "TeamNum": 0,
         "Score": 320, "Goals": 1, "Shots": 3, "Saves": 2, "Assists": 0,
         "Demos": 1, "Boost": 47, "Speed": 67.8},
        {"Name": "Nitro", "PrimaryId": "Mock|nitro|0", "TeamNum": 0,
         "Score": 150, "Goals": 0, "Shots": 1, "Saves": 0, "Assists": 1,
         "Demos": 0, "Boost": 60, "Speed": 40.0},
        {"Name": "Octane", "PrimaryId": "Mock|oct|0", "TeamNum": 1,
         "Score": 120, "Goals": 0, "Shots": 1, "Saves": 1, "Assists": 0,
         "Demos": 0, "Boost": 80, "Speed": 110.0},
        {"Name": "Dominus", "PrimaryId": "Mock|dom|0", "TeamNum": 1,
         "Score": 90, "Goals": 0, "Shots": 0, "Saves": 0, "Assists": 0,
         "Demos": 0, "Boost": 30, "Speed": 20.0},
    ]


def real_state(players=None, arena="EuroStadium_Night_P", winner=""):
    return {
        "MatchGuid": "g",
        "Players": players if players is not None else real_players(),
        "Game": {
            "Teams": [{"Name": "Blue", "TeamNum": 0, "Score": 2},
                      {"Name": "Orange", "TeamNum": 1, "Score": 1}],
            "TimeSeconds": 182, "bOvertime": False, "Arena": arena,
            "bHasWinner": bool(winner), "Winner": winner,
            "Target": {"Name": "Zeph .", "TeamNum": 0},
        },
    }


class ArenaTest(unittest.TestCase):
    def test_known_code(self):
        self.assertEqual(friendly_arena("EuroStadium_Night_P"), "Mannfield (Night)")

    def test_unknown_code_prettified(self):
        self.assertEqual(friendly_arena("SomeNew_Map_P"), "Some New Map")


class PlaylistTest(unittest.TestCase):
    def test_doubles(self):
        self.assertEqual(infer_playlist(real_players()), "2v2 Doubles")

    def test_solo_is_duel_shape(self):
        self.assertEqual(infer_playlist(real_players()[:1]), "1v1 Duel")


class IdentityTest(unittest.TestCase):
    def test_by_configured_name(self):
        ident = LocalIdentity("Zeph .")
        ident.update(real_players())
        self.assertEqual(ident.local_id, "Epic|abc|0")
        self.assertTrue(ident.is_local(real_players()[0]))
        self.assertFalse(ident.is_local(real_players()[1]))

    def test_solo_session_locks_local(self):
        ident = LocalIdentity()
        ident.update(real_players()[:1])
        self.assertEqual(ident.local_id, "Epic|abc|0")

    def test_target_fallback(self):
        ident = LocalIdentity()
        ident.update(real_players(), target_name="Octane")
        self.assertEqual(ident.local_id, "Mock|oct|0")


class NormalizeTest(unittest.TestCase):
    def test_full_shape(self):
        ident = LocalIdentity("Zeph .")
        state = normalize_update_state(real_state(), ident, supersonic_speed=100.0)
        self.assertEqual(state["game"]["arena"], "Mannfield (Night)")
        self.assertEqual(state["game"]["playlist"], "2v2 Doubles")
        self.assertEqual(state["game"]["teams"],
                         [{"team": 0, "score": 2}, {"team": 1, "score": 1}])
        me = state["players"][0]
        self.assertEqual(me["name"], "Zeph .")
        self.assertEqual(me["team"], 0)
        self.assertTrue(me["is_local"])
        self.assertEqual(me["goals"], 1)
        self.assertEqual(me["saves"], 2)
        self.assertEqual(me["demos"], 1)
        self.assertFalse(me["is_supersonic"])          # 67.8 < 100
        octane = next(p for p in state["players"] if p["name"] == "Octane")
        self.assertTrue(octane["is_supersonic"])       # 110 >= 100

    def test_winner_surfaced(self):
        ident = LocalIdentity("Zeph .")
        state = normalize_update_state(real_state(winner="Blue"), ident)
        self.assertTrue(state["game"]["has_winner"])
        self.assertEqual(state["game"]["winner_name"], "Blue")


if __name__ == "__main__":
    unittest.main()
