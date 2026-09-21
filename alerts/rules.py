"""Rule engine for the Stream Alert App.

A *rule* maps a Stats API event (plus optional conditions) to an *alert* that
gets pushed to the OBS overlay. Rules are plain JSON so streamers can edit them
without touching Python.

Rule shape::

    {
      "name": "My goal",
      "event": "GoalScored",
      "when": { "scored_by_me": true, "goal_speed": { ">=": 90 } },
      "alert": {
        "title": "GOAL!",
        "subtitle": "{scorer} — {goal_speed} kph",
        "icon": "🥅",
        "color": "#2f8bff",
        "animation": "pop",          # pop | slide | flash
        "sound": "chime",            # built-in name, or a URL/path to an audio file
        "duration_ms": 4000
      }
    }

``when`` conditions are matched against a flat *context* the server builds from
each event (see ``alerts.server``). A bare value means equality; a dict means an
operator comparison, e.g. ``{"goal_speed": {">=": 90}}``.

Built-in sound names the overlay can synthesize (no audio files needed):
``chime``, ``ding``, ``airhorn``, ``pop``, ``buzz``, ``coin``, ``whoosh``,
``sad``. Any other value is treated as an audio URL.
"""

from __future__ import annotations

import json
import logging
import operator
import os
from typing import Any

log = logging.getLogger("rlstats.alerts.rules")

_OPS = {
    "==": operator.eq, "!=": operator.ne,
    ">": operator.gt, ">=": operator.ge,
    "<": operator.lt, "<=": operator.le,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: bool(a) and b in a,
}


def _compare(op: str, actual: Any, expected: Any) -> bool:
    fn = _OPS.get(op)
    if fn is None:
        log.warning("unknown operator %r in rule condition", op)
        return False
    try:
        return bool(fn(actual, expected))
    except TypeError:
        # e.g. comparing None to a number — treat as "doesn't match".
        return False


def matches(when: dict, context: dict) -> bool:
    """True if every condition in ``when`` holds for ``context``."""
    for key, expected in (when or {}).items():
        actual = context.get(key)
        if isinstance(expected, dict):
            for op, value in expected.items():
                if not _compare(op, actual, value):
                    return False
        else:
            if actual != expected:
                return False
    return True


class _SafeDict(dict):
    def __missing__(self, key):  # leave unknown {placeholders} blank
        return ""


def _fmt(value: Any, context: dict) -> Any:
    if isinstance(value, str):
        try:
            return value.format_map(_SafeDict(context))
        except (ValueError, IndexError):
            return value
    return value


def build_alert(rule: dict, context: dict) -> dict:
    """Render a rule's alert template against the event context."""
    template = rule.get("alert", {})
    alert = {k: _fmt(v, context) for k, v in template.items()}
    alert.setdefault("animation", "pop")
    alert.setdefault("duration_ms", 4000)
    alert["rule"] = rule.get("name", "")
    return alert


def evaluate(rules: list[dict], event: str, context: dict) -> list[dict]:
    """Return rendered alerts for every rule that fires on this event."""
    fired = []
    for rule in rules:
        if rule.get("event") != event:
            continue
        if matches(rule.get("when", {}), context):
            fired.append(build_alert(rule, context))
    return fired


def load_rules(path: str | None) -> list[dict]:
    """Load rules from ``path``, falling back to the bundled example rules."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [p for p in (path, os.path.join(here, "rules.json"),
                              os.path.join(here, "rules.example.json")) if p]
    for candidate in candidates:
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            rules = data["rules"] if isinstance(data, dict) else data
            log.info("loaded %d alert rule(s) from %s", len(rules), candidate)
            return rules
    log.warning("no rules file found; no alerts will fire")
    return []
