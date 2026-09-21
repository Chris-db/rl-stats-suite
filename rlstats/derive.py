"""Derive high-level events from the UpdateState stream.

The real Stats API does emit dedicated goal/demo events, but their exact shapes
vary by game version and we can't rely on them. Everything we need, however, is
already in ``UpdateState``: per-player Goals/Saves/Demos and team scores every
tick. So we diff consecutive states and synthesize the canonical events the rest
of the suite consumes (``GoalScored``, ``StatfeedEvent``, ``MatchCreated``,
``MatchEnded``). One code path works for both the real game and the mock.

``CanonicalFeed`` wraps a raw transport and re-exposes the same ``on()`` pub/sub,
so tools attach to it exactly as they did to the old listener.
"""

from __future__ import annotations

import time

from . import events as ev
from .listener import EventListener
from .matchstate import is_real_match
from .normalize import LocalIdentity, normalize_update_state, DEFAULT_SUPERSONIC_SPEED


def _ref(p: dict) -> dict:
    return {"id": p.get("id"), "name": p.get("name"),
            "team": p.get("team"), "is_local": p.get("is_local", False)}


class CanonicalFeed:
    def __init__(self, listener, local_name: str | None = None,
                 supersonic_speed: float = DEFAULT_SUPERSONIC_SPEED,
                 ignore_playlists: tuple[str, ...] | None = None) -> None:
        self.listener = listener
        self.identity = LocalIdentity(local_name)
        self.supersonic_speed = supersonic_speed
        self.ignore_playlists = ignore_playlists
        self._handlers: dict[str, list] = {}

        self._in_match = False
        self._ended = False
        self._match_guid: str | None = None
        self._match_start = 0.0
        self._arena = None
        self._playlist = None
        self._prev_players: dict[str, dict] = {}
        self._prev_scores: dict[int, int] = {}

        listener.on(ev.UPDATE_STATE, self._on_update)

    @classmethod
    def from_config(cls, config: dict) -> "CanonicalFeed":
        listener = EventListener(config["stats_api_url"], config["reconnect_delay"])
        return cls(listener, config.get("local_player_name"),
                   config.get("supersonic_speed", DEFAULT_SUPERSONIC_SPEED),
                   tuple(config.get("ignore_playlists") or ()))

    # --- pub/sub ----------------------------------------------------------

    def on(self, event: str, handler=None):
        def register(fn):
            self._handlers.setdefault(event, []).append(fn)
            return fn
        return register if handler is None else register(handler)

    def _emit(self, event: str, data: dict) -> None:
        for h in list(self._handlers.get(event, ())):
            self._safe(h, data)
        for h in list(self._handlers.get(ev.ALL, ())):
            self._safe(h, {"event": event, "data": data})

    @staticmethod
    def _safe(handler, payload) -> None:
        try:
            handler(payload)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger("rlstats.derive").exception("handler raised")

    # --- transport passthrough -------------------------------------------

    def start(self):
        self.listener.start()
        return self

    def run_forever(self):
        self.listener.run_forever()

    def stop(self):
        self.listener.stop()

    def wait_connected(self, timeout=None):
        return self.listener.wait_connected(timeout)

    @property
    def is_connected(self):
        return self.listener.is_connected

    # --- the heart: diff UpdateState -> canonical events ------------------

    def _on_update(self, raw_data: dict) -> None:
        state = normalize_update_state(raw_data, self.identity, self.supersonic_speed)
        game = state["game"]
        players = state["players"]
        guid = raw_data.get("MatchGuid") or ""
        has_winner = bool(game.get("has_winner"))
        if self.ignore_playlists is not None:
            real = is_real_match(players, game.get("playlist"), self.ignore_playlists)
        else:
            real = is_real_match(players, game.get("playlist"))

        # After a match is recorded, stay latched until the game clearly moves on
        # — winner cleared, left the match, or a new match id. Without this the
        # post-game podium (which keeps bHasWinner=true for many ticks, with
        # players leaving) would re-record the same match over and over.
        if self._ended and (not real or not has_winner or guid != self._match_guid):
            self._ended = False
            self._in_match = False

        # Only begin tracking a match that's actually in progress (no winner yet),
        # so we never "start" on a leftover podium state.
        if real and not has_winner and not self._in_match and not self._ended:
            self._begin_match(game, guid)

        self._emit(ev.UPDATE_STATE, state)

        if self._in_match:
            self._detect_goals(players, game)
            if not game.get("is_replay"):       # stats re-fire during goal replays
                self._detect_statfeed(players)
            if has_winner:
                self._end_match(state)

        self._prev_players = {p["id"]: p for p in players if p.get("id") is not None}
        self._prev_scores = {t["team"]: t["score"] for t in game["teams"]}

    def _begin_match(self, game: dict, guid: str = "") -> None:
        self._in_match = True
        self._ended = False
        self._match_guid = guid
        self._match_start = time.time()
        self._arena = game.get("arena")
        self._playlist = game.get("playlist")
        self._prev_players = {}
        self._prev_scores = {}
        self._emit(ev.MATCH_CREATED, {"arena": self._arena, "playlist": self._playlist})

    def _detect_goals(self, players: list[dict], game: dict) -> None:
        # Count goals from the authoritative team scoreboard (it increments
        # exactly once per goal), NOT from per-player Goals stats — those re-fire
        # every tick during a goal replay. Per-player deltas are used only to
        # attribute the scorer/assister at the moment the score changes.
        if not self._prev_scores:
            return
        scores = {t["team"]: t.get("score", 0) for t in game["teams"]}
        scoreboard = [scores.get(0, 0), scores.get(1, 0)]
        scorer_by_team: dict[int, dict] = {}
        for p in players:
            if self._delta(p, "goals") > 0:
                scorer_by_team.setdefault(p["team"], p)
        assist_by_team = {p["team"]: p for p in players if self._delta(p, "assists") > 0}

        for team, score in scores.items():
            inc = max(0, min(score - self._prev_scores.get(team, score), 5))
            for _ in range(inc):
                scorer = scorer_by_team.get(team)
                assister = assist_by_team.get(team)
                self._emit(ev.GOAL_SCORED, {
                    "scorer": _ref(scorer) if scorer else None,
                    "assister": _ref(assister) if assister and assister is not scorer else None,
                    "goal_speed": None,
                    "team": team,
                    "scoreboard": scoreboard,
                    "is_overtime": game.get("is_overtime", False),
                })

    def _detect_statfeed(self, players: list[dict]) -> None:
        for p in players:
            if self._delta(p, "saves") > 0:
                self._emit(ev.STATFEED_EVENT,
                           {"type": ev.STATFEED_SAVE, "main_target": _ref(p),
                            "secondary_target": None})
            if self._delta(p, "demos") > 0:
                self._emit(ev.STATFEED_EVENT,
                           {"type": ev.STATFEED_DEMOLITION, "main_target": _ref(p),
                            "secondary_target": None})

    def _end_match(self, state: dict) -> None:
        game = state["game"]
        scores = {t["team"]: t["score"] for t in game["teams"]}
        winner_team = self._winner_team(state)
        self._emit(ev.MATCH_ENDED, {
            "arena": game.get("arena"),
            "playlist": game.get("playlist"),
            "duration_seconds": round(time.time() - self._match_start, 1),
            "winner_team": winner_team,
            "teams": game["teams"],
            "players": state["players"],
        })
        self._emit(ev.MATCH_DESTROYED, {})
        self._in_match = False
        self._ended = True

    @staticmethod
    def _winner_team(state: dict) -> int | None:
        game = state["game"]
        name = game.get("winner_name")
        if name:
            for p in state["players"]:
                if p.get("name") == name:
                    return p.get("team")
        scores = {t["team"]: t["score"] for t in game["teams"]}
        if len(scores) >= 2:
            return max(scores, key=scores.get)
        return None

    def _delta(self, player: dict, field: str) -> int:
        prev = self._prev_players.get(player.get("id"))
        if prev is None:
            return 0
        return max(0, int(player.get(field, 0)) - int(prev.get(field, 0)))
