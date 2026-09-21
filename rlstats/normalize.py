"""Translate the real Stats API's payloads into the suite's canonical schema.

The game sends PascalCase fields (``TeamNum``, ``Goals``, ``Boost`` …) inside a
double-encoded ``Data`` string; every tool in the suite, the mock and the tests
speak a tidy lowercase schema instead. Normalising here means nothing downstream
has to know what the wire format looks like.

Canonical UpdateState::

    {
      "game": {"arena", "playlist", "time_seconds", "is_overtime",
               "teams": [{"team", "score"}], "has_winner", "winner_name"},
      "players": [{"id", "name", "team", "is_local", "score", "goals", "shots",
                   "saves", "assists", "demos", "boost", "speed", "is_supersonic"}]
    }
"""

from __future__ import annotations

# Speed (km/h-ish in the feed) above which we treat a car as supersonic. The feed
# unit isn't documented; this is a sane default and is configurable. Calibrate
# from a real capture if alerts misfire.
DEFAULT_SUPERSONIC_SPEED = 100.0

# Internal arena codes -> friendly names. Unknown codes are prettified.
ARENA_NAMES = {
    "Stadium_P": "DFH Stadium",
    "Stadium_Day_P": "DFH Stadium (Day)",
    "EuroStadium_P": "Mannfield",
    "EuroStadium_Night_P": "Mannfield (Night)",
    "EuroStadium_Rainy_P": "Mannfield (Stormy)",
    "cs_p": "Champions Field",
    "cs_day_p": "Champions Field (Day)",
    "TrainStation_P": "Urban Central",
    "TrainStation_Night_P": "Urban Central (Night)",
    "Park_P": "Beckwith Park",
    "Park_Night_P": "Beckwith Park (Midnight)",
    "Wasteland_S_P": "Wasteland",
    "NeoTokyo_Standard_P": "Neo Tokyo",
    "Underwater_P": "AquaDome",
    "UF_Day_P": "Utopia Coliseum",
    "UF_P": "Utopia Coliseum",
    "UF_Night_P": "Utopia Coliseum (Night)",
    "UtopiaStadium_P": "Utopia Coliseum",
    "UtopiaStadium_Snow_P": "Utopia Coliseum (Snowy)",
    "ShatterShot_P": "Salty Shores",
    "Outlaw_P": "Deadeye Canyon",
    "Farm_P": "Farmstead",
}

import re

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def friendly_arena(code: str | None) -> str | None:
    if not code:
        return code
    if code in ARENA_NAMES:
        return ARENA_NAMES[code]
    name = code
    for suffix in ("_P", "_p"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    name = name.replace("_", " ")
    name = _CAMEL.sub(" ", name)          # UtopiaStadium -> Utopia Stadium
    return name.strip()


def infer_playlist(players: list[dict]) -> str | None:
    """Real UpdateState has no playlist; infer a mode label from team sizes."""
    if not players:
        return None
    per_team: dict[int, int] = {}
    for p in players:
        t = p.get("TeamNum", p.get("team"))
        per_team[t] = per_team.get(t, 0) + 1
    biggest = max(per_team.values())
    return {1: "1v1 Duel", 2: "2v2 Doubles", 3: "3v3 Standard"}.get(biggest, f"{biggest}v{biggest}")


class LocalIdentity:
    """Works out which player is *you*.

    The feed has no "is local" flag, so we lock onto your ``PrimaryId``: by the
    configured name if given, otherwise from a solo session (freeplay/warmup has
    exactly one player — that's you), otherwise from the spectated ``Target``.
    """

    def __init__(self, local_name: str | None = None) -> None:
        self.local_name = (local_name or "").strip() or None
        self.local_id: str | None = None

    def update(self, players: list[dict], target_name: str | None = None) -> None:
        if self.local_name:
            for p in players:
                if (p.get("Name") or "").strip() == self.local_name:
                    self.local_id = p.get("PrimaryId") or self.local_id
                    return
        if self.local_id is None and len(players) == 1:
            self.local_id = players[0].get("PrimaryId")
            return
        if self.local_id is None and target_name:
            for p in players:
                if p.get("Name") == target_name:
                    self.local_id = p.get("PrimaryId")
                    return

    def is_local(self, player: dict) -> bool:
        pid = player.get("PrimaryId")
        if self.local_id is not None and pid is not None:
            return pid == self.local_id
        if self.local_name:
            return (player.get("Name") or "").strip() == self.local_name
        return False


def normalize_player(p: dict, identity: LocalIdentity, supersonic_speed: float) -> dict:
    speed = float(p.get("Speed", 0) or 0)
    return {
        "id": p.get("PrimaryId") or p.get("Name"),
        "name": p.get("Name"),
        "team": p.get("TeamNum"),
        "is_local": identity.is_local(p),
        "score": p.get("Score", 0),
        "goals": p.get("Goals", 0),
        "shots": p.get("Shots", 0),
        "saves": p.get("Saves", 0),
        "assists": p.get("Assists", 0),
        "demos": p.get("Demos", 0),
        "boost": p.get("Boost", 0),
        "speed": speed,
        "is_supersonic": speed >= supersonic_speed,
    }


def normalize_update_state(data: dict, identity: LocalIdentity,
                           supersonic_speed: float = DEFAULT_SUPERSONIC_SPEED) -> dict:
    """Convert a real UpdateState ``Data`` dict into the canonical shape."""
    game = data.get("Game", {}) or {}
    players_raw = data.get("Players", []) or []

    target = game.get("Target") or {}
    identity.update(players_raw, target.get("Name"))

    teams = [{"team": t.get("TeamNum"), "score": t.get("Score", 0)}
             for t in game.get("Teams", [])]
    players = [normalize_player(p, identity, supersonic_speed) for p in players_raw]

    return {
        "game": {
            "arena": friendly_arena(game.get("Arena")),
            "playlist": infer_playlist(players_raw),
            "time_seconds": game.get("TimeSeconds"),
            "is_overtime": bool(game.get("bOvertime")),
            "teams": teams,
            "has_winner": bool(game.get("bHasWinner")),
            "winner_name": game.get("Winner") or None,
            "is_replay": bool(game.get("bReplay")),
        },
        "players": players,
    }
