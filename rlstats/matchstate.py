"""Tell a real match apart from freeplay / training / warmup.

Rocket League's Stats API streams events in *every* game state, including
freeplay and training where there's no real game. Recording those would put
practice shots in your highlight reel and junk rows in your stats. This module
decides whether the current activity is a real match worth tracking.

Heuristic (deliberately conservative so it never drops a real match):
  * a real online match always has players on **both teams** — freeplay and
    training are solo, so "opponents exist" is the primary signal;
  * playlists whose name looks like freeplay/training are excluded outright.

Tune the playlist list in config if your game reports different names — use
``python rl.py monitor`` while you play to see exactly what it sends.
"""

from __future__ import annotations

from . import events as ev

# Substrings (case-insensitive) that mark a non-match game state.
DEFAULT_IGNORE_PLAYLISTS = (
    "freeplay", "free play", "training", "workshop", "custom",
)


def is_real_match(players: list[dict] | None,
                  playlist: str | None = None,
                  ignore_playlists: tuple[str, ...] = DEFAULT_IGNORE_PLAYLISTS) -> bool:
    """True if this looks like a real match (not freeplay/training)."""
    if playlist:
        pl = playlist.strip().lower()
        if any(token in pl for token in ignore_playlists):
            return False
    teams = {p.get("team") for p in (players or []) if p.get("team") is not None}
    return len(teams) >= 2


class MatchGate:
    """Tracks whether a real match is currently in progress.

    Attach it to a listener; tools then check ``gate.active`` before acting on a
    goal. It stays correct even if you start the tool mid-match (it confirms from
    the first ``UpdateState`` rather than relying solely on ``MatchCreated``).
    """

    def __init__(self, ignore_playlists: tuple[str, ...] = DEFAULT_IGNORE_PLAYLISTS) -> None:
        self.ignore = ignore_playlists
        self.playlist: str | None = None
        self.arena: str | None = None
        self._in_match = False
        self._real = False

    def attach(self, listener) -> "MatchGate":
        listener.on(ev.MATCH_CREATED, self._on_created)
        listener.on(ev.UPDATE_STATE, self._on_update)
        listener.on(ev.MATCH_ENDED, self._on_finished)
        listener.on(ev.MATCH_DESTROYED, self._on_finished)
        return self

    def _on_created(self, data: dict) -> None:
        self._in_match = True
        self.playlist = data.get("playlist")
        self.arena = data.get("arena")

    def _on_update(self, data: dict) -> None:
        game = data.get("game", {})
        if game.get("playlist"):
            self.playlist = game["playlist"]
        if game.get("arena"):
            self.arena = game["arena"]
        self._real = is_real_match(data.get("players", []), self.playlist, self.ignore)
        if self._real:
            self._in_match = True          # safety net if we joined mid-match

    def _on_finished(self, _data: dict) -> None:
        self._in_match = False
        self._real = False

    @property
    def active(self) -> bool:
        """A real match is in progress right now."""
        return self._in_match and self._real
