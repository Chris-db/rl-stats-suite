"""Background recorder for the Personal Stats Tracker.

Subscribes to the shared listener and writes one match (plus per-player rows) to
SQLite whenever a match ends. Boost *usage* isn't a single field in the feed, so
we accumulate it from the per-tick ``UpdateState`` boost values across the match
and fall back to a ``boost_used`` field if the feed already provides one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from rlstats import events as ev, make_feed
from rlstats.matchstate import is_real_match, DEFAULT_IGNORE_PLAYLISTS
from . import db

log = logging.getLogger("rlstats.tracker.recorder")


def _find_local(players: list[dict], local_name: str | None) -> dict | None:
    for p in players:
        if p.get("is_local"):
            return p
    if local_name:
        for p in players:
            if p.get("name") == local_name:
                return p
    return players[0] if players else None


def build_match_rows(data: dict, local_name: str | None,
                     boost_used: dict[str, float] | None = None) -> tuple[dict, list[dict]]:
    """Turn a ``MatchEnded`` payload into (match_row, [player_rows]).

    ``boost_used`` optionally maps player id -> accumulated boost consumed,
    used when the feed itself doesn't report it.
    """
    boost_used = boost_used or {}
    players = data.get("players", [])
    local = _find_local(players, local_name)
    local_team = local["team"] if local else 0

    teams = {t["team"]: t["score"] for t in data.get("teams", [])}
    team_score = teams.get(local_team, 0)
    opponent_score = sum(s for t, s in teams.items() if t != local_team)
    winner = data.get("winner_team")
    won = 1 if winner is not None and winner == local_team else 0

    match_row = {
        "played_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "arena": data.get("arena"),
        "playlist": data.get("playlist"),
        "duration_seconds": data.get("duration_seconds"),
        "local_player": local.get("name") if local else None,
        "local_team": local_team,
        "won": won,
        "team_score": team_score,
        "opponent_score": opponent_score,
    }

    player_rows = []
    for p in players:
        bu = p.get("boost_used")
        if bu is None:
            bu = boost_used.get(p.get("id"), 0.0)
        player_rows.append({
            "name": p.get("name"),
            "team": p.get("team"),
            "is_local": 1 if p is local else 0,
            "score": p.get("score", 0),
            "goals": p.get("goals", 0),
            "shots": p.get("shots", 0),
            "saves": p.get("saves", 0),
            "assists": p.get("assists", 0),
            "demos": p.get("demos", 0),
            "boost_used": round(float(bu), 1),
        })
    return match_row, player_rows


class MatchRecorder:
    """Wires a listener to the database and records every completed match."""

    def __init__(self, conn, local_name: str | None = None,
                 ignore_playlists: tuple[str, ...] = DEFAULT_IGNORE_PLAYLISTS) -> None:
        self.conn = conn
        self.local_name = local_name
        self.ignore_playlists = ignore_playlists
        # Per-match boost accounting: player id -> (last_boost, consumed_total).
        self._last_boost: dict[str, float] = {}
        self._consumed: dict[str, float] = {}

    def attach(self, feed) -> "MatchRecorder":
        feed.on(ev.MATCH_CREATED, self._on_match_created)
        feed.on(ev.UPDATE_STATE, self._on_update)
        feed.on(ev.MATCH_ENDED, self._on_match_ended)
        return self

    def _on_match_created(self, _data: dict) -> None:
        self._last_boost.clear()
        self._consumed.clear()

    def _on_update(self, data: dict) -> None:
        for p in data.get("players", []):
            pid = p.get("id")
            if pid is None:
                continue
            boost = float(p.get("boost", 0))
            prev = self._last_boost.get(pid)
            if prev is not None and boost < prev:
                self._consumed[pid] = self._consumed.get(pid, 0.0) + (prev - boost)
            self._last_boost[pid] = boost

    def _on_match_ended(self, data: dict):
        if not is_real_match(data.get("players", []), data.get("playlist"),
                             self.ignore_playlists):
            log.info("ignored non-match (freeplay/training): %s", data.get("playlist"))
            self._last_boost.clear()
            self._consumed.clear()
            return None
        match_row, player_rows = build_match_rows(data, self.local_name, self._consumed)
        match_id = db.insert_match(self.conn, match_row, player_rows)
        result = "WON" if match_row["won"] else "lost"
        log.info(
            "recorded match #%d: %s %d-%d on %s (%s)",
            match_id, result, match_row["team_score"], match_row["opponent_score"],
            match_row["arena"], match_row["playlist"],
        )
        self._last_boost.clear()
        self._consumed.clear()
        return match_id


def run(config: dict) -> None:
    """Connect to the Stats API and record matches until interrupted (blocking)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    conn = db.connect(config["database_path"])
    feed = make_feed(config)
    ignore = tuple(config.get("ignore_playlists") or DEFAULT_IGNORE_PLAYLISTS)
    MatchRecorder(conn, config.get("local_player_name"), ignore).attach(feed)
    log.info("recording to %s - waiting for matches (Ctrl+C to stop)", config["database_path"])
    try:
        feed.run_forever()
    except KeyboardInterrupt:
        log.info("stopping recorder")
    finally:
        feed.stop()
        conn.close()


if __name__ == "__main__":
    from rlstats import load_config
    run(load_config())
