"""Generate realistic demo data for the dashboard without playing matches.

Useful for trying the dashboard, screenshots, and tests. Produces matches spread
across several play sessions over the past week.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from . import db
from .recorder import build_match_rows

ARENAS = ["DFH Stadium", "Mannfield", "Champions Field", "Wasteland", "Neo Tokyo"]
PLAYLISTS = ["Ranked Doubles", "Ranked Standard", "Ranked Duels"]


def _match(rng: random.Random, won: bool, arena: str, playlist: str) -> dict:
    my_goals = rng.randint(0, 4)
    opp_goals = max(0, my_goals - rng.randint(1, 3)) if won else my_goals + rng.randint(1, 3)
    return {
        "arena": arena, "playlist": playlist,
        "duration_seconds": round(rng.uniform(300, 360), 1),
        "winner_team": 0 if won else 1,
        "teams": [{"team": 0, "score": my_goals}, {"team": 1, "score": opp_goals}],
        "players": [
            {"id": "b0", "name": "You", "team": 0, "is_local": True,
             "score": rng.randint(150, 600), "goals": my_goals,
             "shots": my_goals + rng.randint(1, 5), "saves": rng.randint(0, 5),
             "assists": rng.randint(0, 3), "demos": rng.randint(0, 3),
             "boost_used": round(rng.uniform(300, 900), 1)},
            {"id": "b1", "name": "Nitro", "team": 0, "is_local": False,
             "score": rng.randint(150, 500), "goals": rng.randint(0, 3),
             "shots": rng.randint(1, 6), "saves": rng.randint(0, 4),
             "assists": rng.randint(0, 3), "demos": rng.randint(0, 2),
             "boost_used": round(rng.uniform(300, 900), 1)},
            {"id": "o0", "name": "Octane", "team": 1, "is_local": False,
             "score": rng.randint(150, 500), "goals": rng.randint(0, 3),
             "shots": rng.randint(1, 6), "saves": rng.randint(0, 4),
             "assists": rng.randint(0, 3), "demos": rng.randint(0, 2),
             "boost_used": round(rng.uniform(300, 900), 1)},
            {"id": "o1", "name": "Dominus", "team": 1, "is_local": False,
             "score": rng.randint(150, 500), "goals": rng.randint(0, 3),
             "shots": rng.randint(1, 6), "saves": rng.randint(0, 4),
             "assists": rng.randint(0, 3), "demos": rng.randint(0, 2),
             "boost_used": round(rng.uniform(300, 900), 1)},
        ],
    }


def generate(conn, matches: int = 40, seed: int = 42, win_rate: float = 0.56) -> int:
    """Insert ``matches`` synthetic matches across realistic sessions."""
    rng = random.Random(seed)
    # Walk backward in sessions of 4-9 matches, ~1 day apart.
    when = datetime.now(timezone.utc) - timedelta(minutes=10)
    remaining = matches
    timestamps: list[datetime] = []
    while remaining > 0:
        session_len = min(remaining, rng.randint(4, 9))
        for _ in range(session_len):
            timestamps.append(when)
            when -= timedelta(minutes=rng.randint(6, 10))   # within a session
            remaining -= 1
        when -= timedelta(hours=rng.randint(18, 30))         # gap to previous session
    timestamps.sort()  # oldest first

    inserted = 0
    for ts in timestamps:
        won = rng.random() < win_rate
        data = _match(rng, won, rng.choice(ARENAS), rng.choice(PLAYLISTS))
        match_row, player_rows = build_match_rows(data, "You")
        match_row["played_at"] = ts.isoformat(timespec="seconds")
        db.insert_match(conn, match_row, player_rows)
        inserted += 1
    return inserted


def main(argv=None) -> None:
    import argparse
    from rlstats import load_config

    p = argparse.ArgumentParser(description="Seed the tracker DB with demo matches.")
    p.add_argument("--matches", type=int, default=40)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    cfg = load_config()
    conn = db.connect(cfg["database_path"])
    n = generate(conn, args.matches, args.seed)
    conn.close()
    print(f"Seeded {n} matches into {cfg['database_path']}")


if __name__ == "__main__":
    main()
