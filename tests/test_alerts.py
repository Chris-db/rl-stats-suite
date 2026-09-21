"""Tests for Tool 2: rule matching, alert rendering, and event context."""

from __future__ import annotations

import unittest

from alerts import rules as r
from alerts.server import AlertServer
from rlstats import events as ev

BASE_CONFIG = {
    "local_player_name": None,
    "alert_rules_path": None,
    "alert_overlay_host": "127.0.0.1",
    "alert_overlay_http_port": 8080,
    "alert_overlay_ws_port": 8765,
    "stats_api_url": "ws://localhost:49123",
    "reconnect_delay": 1.0,
}


class RuleMatchTest(unittest.TestCase):
    def test_equality_condition(self):
        self.assertTrue(r.matches({"by_me": True}, {"by_me": True}))
        self.assertFalse(r.matches({"by_me": True}, {"by_me": False}))

    def test_operator_condition(self):
        self.assertTrue(r.matches({"goal_speed": {">=": 100}}, {"goal_speed": 120}))
        self.assertFalse(r.matches({"goal_speed": {">=": 100}}, {"goal_speed": 80}))

    def test_missing_key_does_not_crash(self):
        self.assertFalse(r.matches({"goal_speed": {">=": 100}}, {}))
        self.assertFalse(r.matches({"x": 1}, {}))

    def test_multiple_conditions_all_required(self):
        when = {"scored_by_me": True, "goal_speed": {">=": 90}}
        self.assertTrue(r.matches(when, {"scored_by_me": True, "goal_speed": 95}))
        self.assertFalse(r.matches(when, {"scored_by_me": True, "goal_speed": 50}))

    def test_build_alert_formats_template(self):
        rule = {"name": "g", "alert": {"title": "GOAL!", "subtitle": "{scorer} @ {goal_speed}"}}
        alert = r.build_alert(rule, {"scorer": "You", "goal_speed": 92})
        self.assertEqual(alert["subtitle"], "You @ 92")
        self.assertEqual(alert["rule"], "g")
        self.assertIn("animation", alert)  # defaulted

    def test_build_alert_missing_placeholder_blank(self):
        rule = {"alert": {"subtitle": "by {assister}"}}
        alert = r.build_alert(rule, {})
        self.assertEqual(alert["subtitle"], "by ")

    def test_evaluate_filters_by_event(self):
        rules = [
            {"name": "a", "event": "GoalScored", "when": {}, "alert": {"title": "A"}},
            {"name": "b", "event": "StatfeedEvent", "when": {}, "alert": {"title": "B"}},
        ]
        fired = r.evaluate(rules, "GoalScored", {})
        self.assertEqual([a["title"] for a in fired], ["A"])

    def test_example_rules_load(self):
        rules = r.load_rules(None)  # falls back to rules.example.json
        self.assertTrue(any(rule["event"] == "GoalScored" for rule in rules))


class ServerContextTest(unittest.TestCase):
    def setUp(self):
        self.s = AlertServer(dict(BASE_CONFIG))

    def test_is_me_by_flag_and_name(self):
        self.assertTrue(self.s._is_me({"is_local": True, "name": "You"}))
        self.s.local_name = "Zephyr"
        self.assertTrue(self.s._is_me({"name": "Zephyr"}))
        self.assertFalse(self.s._is_me({"name": "Other"}))

    def test_goal_context_conceded(self):
        self.s.local_team = 0
        ctx = self.s._ctx_goal({
            "scorer": {"name": "Octane", "team": 1}, "assister": None,
            "goal_speed": 70, "team": 1,
        })
        self.assertTrue(ctx["conceded"])
        self.assertFalse(ctx["scored_by_me"])

    def test_goal_context_my_goal(self):
        self.s.local_team = 0
        ctx = self.s._ctx_goal({
            "scorer": {"name": "You", "is_local": True, "team": 0},
            "assister": {"name": "Nitro", "team": 0},
            "goal_speed": 110, "team": 0,
        })
        self.assertTrue(ctx["scored_by_me"])
        self.assertFalse(ctx["conceded"])

    def test_statfeed_demo_against_me(self):
        ctx = self.s._ctx_statfeed({
            "type": "Demolition",
            "main_target": {"name": "Octane", "team": 1},
            "secondary_target": {"name": "You", "is_local": True, "team": 0},
        })
        self.assertEqual(ctx["statfeed_type"], "Demolition")
        self.assertTrue(ctx["against_me"])
        self.assertFalse(ctx["by_me"])

    def test_supersonic_rising_edge_fires_once(self):
        fired = []
        self.s._push = lambda alert: fired.append(alert)
        self.s.rules = [{"name": "ss", "event": "Supersonic", "when": {},
                         "alert": {"title": "SUPERSONIC"}}]
        me = {"name": "You", "is_local": True, "team": 0, "is_supersonic": False, "speed": 1000}
        self.s._on_update({"players": [me]})
        me["is_supersonic"] = True
        self.s._on_update({"players": [me]})   # rising edge -> fire
        self.s._on_update({"players": [me]})   # still supersonic -> no repeat
        self.assertEqual(len(fired), 1)


if __name__ == "__main__":
    unittest.main()
