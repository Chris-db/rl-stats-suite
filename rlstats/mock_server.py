"""A mock Rocket League Stats API server (raw TCP, real wire format).

The real Stats API only exists on a machine running Rocket League. This stand-in
lets the whole suite be developed, tested and demoed without the game. It mimics
the real thing faithfully: a **raw TCP** socket that streams JSON objects packed
back-to-back, each ``{"Event":"UpdateState","Data":"<escaped json>"}`` with the
game's PascalCase fields.

It only emits ``UpdateState`` (plus the odd ``BallHit``) — exactly like the game,
the higher-level goal/match events are *derived* downstream from state diffs.

    python -m rlstats.mock_server --quick        # one fast match
    python -m rlstats.mock_server                # realtime, loops forever
    python -m rlstats.mock_server --freeplay     # solo session (to test filtering)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import time

from . import events as ev

log = logging.getLogger("rlstats.mock")

# Internal arena codes (normalize.py maps these to friendly names).
ARENAS = [
    "Stadium_P", "EuroStadium_Night_P", "cs_p", "TrainStation_P",
    "Park_P", "Wasteland_S_P", "NeoTokyo_Standard_P", "Underwater_P",
]
TEAM_NAMES = {0: "Blue", 1: "Orange"}


def _player(name: str, team: int, pid: str) -> dict:
    return {
        "Name": name, "PrimaryId": pid, "Shortcut": team * 10,
        "TeamNum": team, "Score": 0, "Goals": 0, "Shots": 0, "Assists": 0,
        "Saves": 0, "Touches": 0, "CarTouches": 0, "Demos": 0,
        "bHasCar": True, "Speed": 0.0, "Boost": 33,
    }


def _roster(local_name: str, freeplay: bool) -> list[dict]:
    if freeplay:
        return [_player(local_name, 0, "Epic|mocklocal|0")]
    return [
        _player(local_name, 0, "Epic|mocklocal|0"),
        _player("Nitro", 0, "Mock|nitro|0"),
        _player("Octane", 1, "Mock|octane|0"),
        _player("Dominus", 1, "Mock|dominus|0"),
    ]


class MockServer:
    def __init__(self, host: str, port: int, *, speed: float, tick_hz: float,
                 match_seconds: float, loop: bool, oneshot: bool,
                 local_name: str, seed: int | None, freeplay: bool = False) -> None:
        self.host, self.port = host, port
        self.speed, self.tick_hz = speed, tick_hz
        self.match_seconds = match_seconds
        self.loop, self.oneshot, self.freeplay = loop, oneshot, freeplay
        self.local_name = local_name
        self.rng = random.Random(seed)
        self._writers: set[asyncio.StreamWriter] = set()
        self._sim_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # --- networking -------------------------------------------------------

    async def _on_client(self, reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        log.info("client connected (%d total)", len(self._writers))
        if self._sim_task is None or self._sim_task.done():
            self._sim_task = asyncio.create_task(self._simulate())
        try:
            await reader.read()       # wait until the client disconnects
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._writers.discard(writer)
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass
            log.info("client disconnected (%d left)", len(self._writers))

    async def _send(self, event: str, data: dict) -> None:
        # Real format: Data is a JSON *string*; objects stream back-to-back.
        envelope = json.dumps({"Event": event, "Data": json.dumps(data)})
        payload = envelope.encode("utf-8")
        for w in list(self._writers):
            try:
                w.write(payload)
                await w.drain()
            except (ConnectionError, RuntimeError):
                self._writers.discard(w)

    async def serve(self) -> None:
        server = await asyncio.start_server(self._on_client, self.host, self.port)
        log.info("mock Stats API (raw TCP) listening on %s:%d", self.host, self.port)
        async with server:
            await self._stop.wait()
        log.info("mock server stopped")

    def request_stop(self) -> None:
        self._stop.set()

    # --- simulation -------------------------------------------------------

    async def _simulate(self) -> None:
        try:
            while not self._stop.is_set():
                await self._run_match()
                if self.oneshot:
                    self._stop.set()
                    break
                if not self.loop:
                    break
                await asyncio.sleep(1.0 / max(self.speed, 1.0))
        except asyncio.CancelledError:  # pragma: no cover
            pass

    async def _run_match(self) -> None:
        arena = self.rng.choice(ARENAS)
        players = _roster(self.local_name, self.freeplay)
        score = {0: 0, 1: 0}
        clock = self.match_seconds
        dt = self.speed / self.tick_hz
        tick_sleep = 1.0 / self.tick_hz
        log.info("match started: %s%s", arena, " (freeplay)" if self.freeplay else "")

        while clock > 0 and not self._stop.is_set():
            clock = max(0.0, clock - dt)
            self._advance(players, dt)
            if not self.freeplay:
                self._maybe_goal(players, score)
                self._maybe_statfeed(players)
            await self._send(ev.UPDATE_STATE,
                             self._state(arena, clock, score, players, winner=None))
            await asyncio.sleep(tick_sleep)

        if self.freeplay:
            return  # no result in freeplay

        if score[0] == score[1]:                      # overtime: someone scores
            t = self.rng.randint(0, 1)
            self._score_goal(players, score, t)
        winner = 0 if score[0] > score[1] else 1
        await self._send(ev.UPDATE_STATE,
                         self._state(arena, 0.0, score, players, winner=winner))
        log.info("match ended %d-%d, %s wins", score[0], score[1], TEAM_NAMES[winner])
        await asyncio.sleep(tick_sleep)

    # --- per-tick mechanics ----------------------------------------------

    def _advance(self, players: list[dict], dt: float) -> None:
        for p in players:
            p["Boost"] = max(0, min(100, round(p["Boost"] + self.rng.uniform(-15, 12) * dt)))
            p["Speed"] = round(self.rng.uniform(0, 120), 1)
            p["Touches"] += self.rng.random() < 0.3

    def _maybe_goal(self, players: list[dict], score: dict) -> None:
        if self.rng.random() < 0.02 * self.speed / self.tick_hz:
            self._score_goal(players, score, self.rng.randint(0, 1))

    def _score_goal(self, players: list[dict], score: dict, team: int) -> None:
        score[team] += 1
        team_players = [p for p in players if p["TeamNum"] == team]
        scorer = self.rng.choice(team_players)
        scorer["Goals"] += 1
        scorer["Shots"] += 1
        scorer["Score"] += 100
        if len(team_players) > 1 and self.rng.random() < 0.45:
            other = self.rng.choice([p for p in team_players if p is not scorer])
            other["Assists"] += 1
            other["Score"] += 50

    def _maybe_statfeed(self, players: list[dict]) -> None:
        if self.rng.random() > 0.06 * self.speed / self.tick_hz:
            return
        p = self.rng.choice(players)
        roll = self.rng.random()
        if roll < 0.4:
            p["Saves"] += 1; p["Score"] += 50
        elif roll < 0.7:
            p["Demos"] += 1; p["Score"] += 25
        else:
            p["Shots"] += 1

    def _state(self, arena, clock, score, players, winner) -> dict:
        return {
            "MatchGuid": "mock-match",
            "Players": [dict(p) for p in players],
            "Game": {
                "Teams": [
                    {"Name": "Blue", "TeamNum": 0, "Score": score[0],
                     "ColorPrimary": "959595", "ColorSecondary": "E5E5E5"},
                    {"Name": "Orange", "TeamNum": 1, "Score": score[1],
                     "ColorPrimary": "959595", "ColorSecondary": "E5E5E5"},
                ],
                "TimeSeconds": round(clock),
                "bOvertime": clock <= 0 and winner is None,
                "Ball": {"Speed": 0.0, "TeamNum": 255},
                "bReplay": False,
                "bHasWinner": winner is not None,
                "Winner": TEAM_NAMES.get(winner, "") if winner is not None else "",
                "Arena": arena,
                "bHasTarget": True,
                "Target": {"Name": self.local_name, "Shortcut": 0, "TeamNum": 0},
            },
        }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Mock Rocket League Stats API server (raw TCP).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=49123)
    p.add_argument("--speed", type=float, default=1.0,
                   help="game-seconds advanced per real second (e.g. 30 = 30x).")
    p.add_argument("--tick-hz", type=float, default=5.0,
                   help="UpdateState messages per real second.")
    p.add_argument("--match-seconds", type=float, default=300.0)
    p.add_argument("--local-name", default="You")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--freeplay", action="store_true",
                   help="simulate a solo freeplay session (no opponents).")
    p.add_argument("--no-loop", dest="loop", action="store_false")
    p.add_argument("--oneshot", action="store_true",
                   help="play one match then shut down (for scripts/tests).")
    p.add_argument("--quick", action="store_true",
                   help="shortcut: one fast match.")
    p.set_defaults(loop=True)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    if args.quick:
        args.speed, args.loop, args.oneshot = 40.0, False, True
    server = MockServer(
        args.host, args.port, speed=args.speed, tick_hz=args.tick_hz,
        match_seconds=args.match_seconds, loop=args.loop, oneshot=args.oneshot,
        local_name=args.local_name, seed=args.seed, freeplay=args.freeplay,
    )
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
