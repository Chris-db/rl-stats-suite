"""Tests for CanonicalFeed: synthesizing events from UpdateState diffs."""

from __future__ import annotations

import unittest
from collections import Counter

from rlstats import events as ev
from rlstats.derive import CanonicalFeed


class DummyListener:
    """Stand-in transport: lets the test push raw UpdateState payloads."""

    def __init__(self):
        self.handlers = {}

    def on(self, event, handler=None):
        self.handlers.setdefault(event, []).append(handler)

    def push(self, data):
        for h in self.handlers.get(ev.UPDATE_STATE, []):
            h(data)


def players(goals=(0, 0), saves=(0, 0), demos=(0, 0)):
    return [
        {"Name": "You", "PrimaryId": "Epic|me|0", "TeamNum": 0,
         "Goals": goals[0], "Saves": saves[0], "Demos": demos[0],
         "Assists": 0, "Shots": 0, "Score": 0, "Boost": 50, "Speed": 0},
        {"Name": "Opp", "PrimaryId": "Mock|opp|0", "TeamNum": 1,
         "Goals": goals[1], "Saves": saves[1], "Demos": demos[1],
         "Assists": 0, "Shots": 0, "Score": 0, "Boost": 50, "Speed": 0},
    ]


def state(scores=(0, 0), goals=(0, 0), saves=(0, 0), demos=(0, 0),
          has_winner=False, winner="", is_replay=False):
    return {
        "MatchGuid": "g",
        "Players": players(goals, saves, demos),
        "Game": {
            "Teams": [{"Name": "Blue", "TeamNum": 0, "Score": scores[0]},
                      {"Name": "Orange", "TeamNum": 1, "Score": scores[1]}],
            "TimeSeconds": 100, "bOvertime": False, "Arena": "Stadium_P",
            "bHasWinner": has_winner, "Winner": winner, "bReplay": is_replay,
            "Target": {"Name": "You", "TeamNum": 0},
        },
    }


class DeriveTest(unittest.TestCase):
    def setUp(self):
        self.listener = DummyListener()
        self.feed = CanonicalFeed(self.listener, local_name="You")
        self.events = Counter()
        self.goals = []
        self.ended = []
        self.feed.on(ev.ALL, lambda m: self.events.update([m["event"]]))
        self.feed.on(ev.GOAL_SCORED, self.goals.append)
        self.feed.on(ev.MATCH_ENDED, self.ended.append)

    def test_match_created_on_first_real_state(self):
        self.listener.push(state())
        self.assertEqual(self.events[ev.MATCH_CREATED], 1)
        self.assertEqual(self.events[ev.UPDATE_STATE], 1)

    def test_goal_detected_from_score_diff(self):
        self.listener.push(state())                       # baseline
        self.listener.push(state(scores=(1, 0), goals=(1, 0)))  # You score
        self.assertEqual(len(self.goals), 1)
        self.assertEqual(self.goals[0]["scorer"]["name"], "You")
        self.assertEqual(self.goals[0]["team"], 0)
        self.assertEqual(self.goals[0]["scoreboard"], [1, 0])

    def test_saves_and_demos_become_statfeed(self):
        self.listener.push(state())
        self.listener.push(state(saves=(1, 0), demos=(0, 1)))
        self.assertEqual(self.events[ev.STATFEED_EVENT], 2)

    def test_no_goal_spam_when_score_stable(self):
        # The bug: a player's Goals stat re-fires every tick during a replay.
        # Goals must be counted from the scoreboard, so a stable score = no goals.
        self.listener.push(state())                        # 0-0
        self.listener.push(state(scores=(1, 0), goals=(1, 0)))  # one real goal
        for g in range(2, 12):                              # stat glitches up, score stays 1-0
            self.listener.push(state(scores=(1, 0), goals=(g, 0)))
        self.assertEqual(len(self.goals), 1)

    def test_statfeed_skipped_during_replay(self):
        self.listener.push(state())
        self.listener.push(state(saves=(5, 0), is_replay=True))   # replay -> ignored
        self.assertEqual(self.events[ev.STATFEED_EVENT], 0)
        self.listener.push(state(saves=(6, 0)))                   # live -> counts once
        self.assertEqual(self.events[ev.STATFEED_EVENT], 1)

    def test_match_ended_on_winner(self):
        self.listener.push(state())
        self.listener.push(state(scores=(3, 2), goals=(3, 2)))
        self.listener.push(state(scores=(3, 2), goals=(3, 2),
                                 has_winner=True, winner="Blue"))
        self.assertEqual(len(self.ended), 1)
        self.assertEqual(self.ended[0]["winner_team"], 0)   # Blue leads 3-2
        self.assertEqual(len(self.ended[0]["players"]), 2)
        self.assertEqual(self.events[ev.MATCH_DESTROYED], 1)

    def test_records_once_despite_lingering_podium(self):
        # The real game keeps streaming bHasWinner=true (with players leaving)
        # on the podium. A match must be recorded exactly once.
        self.listener.push(state())
        self.listener.push(state(scores=(5, 0), goals=(5, 0)))
        won = state(scores=(5, 0), goals=(5, 0), has_winner=True, winner="Blue")
        for _ in range(20):                      # podium lingers for many ticks
            self.listener.push(won)
        # one teammate quits out -> roster shrinks, still must not re-record
        solo_podium = dict(won)
        solo_podium["Players"] = won["Players"][:1]
        for _ in range(10):
            self.listener.push(solo_podium)
        self.assertEqual(len(self.ended), 1)
        self.assertEqual(self.events[ev.MATCH_CREATED], 1)

    def test_new_match_records_after_reset(self):
        self.listener.push(state())
        self.listener.push(state(scores=(1, 0), goals=(1, 0), has_winner=True, winner="Blue"))
        self.assertEqual(len(self.ended), 1)
        # back to a fresh match (winner cleared, 0-0) -> tracked again
        self.listener.push(state())
        self.listener.push(state(scores=(0, 1), goals=(0, 1), has_winner=True, winner="Orange"))
        self.assertEqual(len(self.ended), 2)
        self.assertEqual(self.ended[1]["winner_team"], 1)

    def test_freeplay_solo_not_a_match(self):
        solo = state()
        solo["Players"] = solo["Players"][:1]                 # only you
        self.listener.push(solo)
        self.listener.push(solo)
        self.assertEqual(self.events[ev.MATCH_CREATED], 0)
        self.assertEqual(self.events[ev.GOAL_SCORED], 0)


if __name__ == "__main__":
    unittest.main()
