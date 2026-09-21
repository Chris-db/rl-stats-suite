"""SQLite storage for the Personal Stats Tracker.

The live API gives the raw feed; this database is what creates meaning across
many matches. One row per match in ``matches`` plus one row per player in that
match in ``player_stats``. All the dashboard's analytics are plain SQL over
these two tables, filtered to the local player.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at        TEXT    NOT NULL,          -- ISO 8601, when the match ended
    arena            TEXT,
    playlist         TEXT,
    duration_seconds REAL,
    local_player     TEXT,
    local_team       INTEGER,
    won              INTEGER NOT NULL,          -- 1 / 0
    team_score       INTEGER NOT NULL,
    opponent_score   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS player_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    name        TEXT,
    team        INTEGER,
    is_local    INTEGER NOT NULL DEFAULT 0,
    score       INTEGER DEFAULT 0,
    goals       INTEGER DEFAULT 0,
    shots       INTEGER DEFAULT 0,
    saves       INTEGER DEFAULT 0,
    assists     INTEGER DEFAULT 0,
    demos       INTEGER DEFAULT 0,
    boost_used  REAL    DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_player_stats_match ON player_stats(match_id);
CREATE INDEX IF NOT EXISTS idx_player_stats_local ON player_stats(is_local);
CREATE INDEX IF NOT EXISTS idx_matches_played_at ON matches(played_at);
"""

# Gap (seconds) between matches that starts a new "session".
SESSION_GAP_SECONDS = 30 * 60


def connect(path: str) -> sqlite3.Connection:
    """Open (creating dirs if needed) and initialise the database."""
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# --- writing ---------------------------------------------------------------

def insert_match(conn: sqlite3.Connection, match: dict, players: list[dict]) -> int:
    """Insert one match plus its per-player rows. Returns the new match id."""
    cur = conn.execute(
        """INSERT INTO matches
               (played_at, arena, playlist, duration_seconds, local_player,
                local_team, won, team_score, opponent_score)
           VALUES (:played_at, :arena, :playlist, :duration_seconds, :local_player,
                   :local_team, :won, :team_score, :opponent_score)""",
        match,
    )
    match_id = cur.lastrowid
    conn.executemany(
        """INSERT INTO player_stats
               (match_id, name, team, is_local, score, goals, shots, saves,
                assists, demos, boost_used)
           VALUES (:match_id, :name, :team, :is_local, :score, :goals, :shots,
                   :saves, :assists, :demos, :boost_used)""",
        [{**p, "match_id": match_id} for p in players],
    )
    conn.commit()
    return match_id


# --- reading (all scoped to the local player) ------------------------------

def _local_join() -> str:
    return (
        "FROM matches m "
        "JOIN player_stats p ON p.match_id = m.id AND p.is_local = 1 "
    )


def overview(conn: sqlite3.Connection) -> dict:
    """Headline totals across every recorded match."""
    row = conn.execute(
        "SELECT "
        "  COUNT(*) AS matches, "
        "  COALESCE(SUM(m.won), 0) AS wins, "
        "  COALESCE(SUM(p.goals), 0) AS goals, "
        "  COALESCE(SUM(p.saves), 0) AS saves, "
        "  COALESCE(SUM(p.assists), 0) AS assists, "
        "  COALESCE(SUM(p.shots), 0) AS shots, "
        "  COALESCE(SUM(p.demos), 0) AS demos, "
        "  COALESCE(AVG(p.saves), 0) AS avg_saves, "
        "  COALESCE(AVG(p.goals), 0) AS avg_goals "
        + _local_join()
    ).fetchone()
    d = dict(row)
    d["losses"] = d["matches"] - d["wins"]
    d["win_rate"] = (d["wins"] / d["matches"]) if d["matches"] else 0.0
    shots = d["shots"] or 0
    d["shooting_pct"] = (d["goals"] / shots) if shots else 0.0
    return d


def recent_matches(conn: sqlite3.Connection, limit: int = 25) -> list[dict]:
    rows = conn.execute(
        "SELECT m.id, m.played_at, m.arena, m.playlist, m.won, "
        "       m.team_score, m.opponent_score, "
        "       p.goals, p.assists, p.saves, p.shots, p.demos, p.score, p.boost_used "
        + _local_join() +
        "ORDER BY m.played_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def win_rate_over_time(conn: sqlite3.Connection) -> list[dict]:
    """Cumulative win rate after each match, oldest first."""
    rows = conn.execute(
        "SELECT m.played_at, m.won " + _local_join() + "ORDER BY m.played_at ASC"
    ).fetchall()
    out, wins = [], 0
    for i, r in enumerate(rows, start=1):
        wins += r["won"]
        out.append({
            "n": i,
            "played_at": r["played_at"],
            "cumulative_win_rate": round(wins / i, 4),
            "won": r["won"],
        })
    return out


def saves_trend(conn: sqlite3.Connection) -> list[dict]:
    """Saves the local player made in each match, oldest first."""
    rows = conn.execute(
        "SELECT m.played_at, p.saves " + _local_join() + "ORDER BY m.played_at ASC"
    ).fetchall()
    return [{"n": i, "played_at": r["played_at"], "saves": r["saves"]}
            for i, r in enumerate(rows, start=1)]


def performance_by_arena(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT m.arena AS arena, COUNT(*) AS matches, "
        "       COALESCE(SUM(m.won),0) AS wins, "
        "       ROUND(AVG(p.goals),2) AS avg_goals, "
        "       ROUND(AVG(p.saves),2) AS avg_saves "
        + _local_join() +
        "GROUP BY m.arena ORDER BY matches DESC, arena ASC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["win_rate"] = round(d["wins"] / d["matches"], 4) if d["matches"] else 0.0
        out.append(d)
    return out


def session_summaries(conn: sqlite3.Connection) -> list[dict]:
    """Group consecutive matches (gap < SESSION_GAP) into play sessions."""
    rows = conn.execute(
        "SELECT m.played_at, m.won, p.goals, p.saves, p.assists, p.demos "
        + _local_join() + "ORDER BY m.played_at ASC"
    ).fetchall()

    sessions: list[dict] = []
    prev_time: datetime | None = None
    cur: dict | None = None

    for r in rows:
        t = _parse_time(r["played_at"])
        new_session = (
            cur is None
            or prev_time is None
            or (t - prev_time) > timedelta(seconds=SESSION_GAP_SECONDS)
        )
        if new_session:
            cur = {
                "start": r["played_at"], "end": r["played_at"],
                "matches": 0, "wins": 0, "goals": 0, "saves": 0,
                "assists": 0, "demos": 0,
            }
            sessions.append(cur)
        cur["end"] = r["played_at"]
        cur["matches"] += 1
        cur["wins"] += r["won"]
        cur["goals"] += r["goals"]
        cur["saves"] += r["saves"]
        cur["assists"] += r["assists"]
        cur["demos"] += r["demos"]
        prev_time = t

    for s in sessions:
        s["losses"] = s["matches"] - s["wins"]
        s["win_rate"] = round(s["wins"] / s["matches"], 4) if s["matches"] else 0.0
    sessions.reverse()  # most recent session first
    return sessions


def _parse_time(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
