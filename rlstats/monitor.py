"""Live event monitor / connection doctor.

Connects to the Stats API and prints every event in plain language, so you can
see exactly what Rocket League sends in each state — menu, freeplay, queue, real
match. Crucially it shows, per goal/match, whether the suite would **track** it
or **ignore** it (freeplay/training), which is how we confirm and tune the
real-match filter against your actual game.

    python rl.py monitor                 # connect to the real game (or mock)
    python rl.py monitor --show-state     # include the per-tick UpdateState line
    python rl.py monitor --raw            # dump full JSON for every event
    python rl.py monitor --save feed.jsonl   # log everything for later analysis
"""

from __future__ import annotations

import argparse
import json
import time

from . import events as ev, load_config
from .listener import EventListener
from .matchstate import MatchGate, is_real_match, DEFAULT_IGNORE_PLAYLISTS


def _ts() -> str:
    return time.strftime("%H:%M:%S")


class Monitor:
    def __init__(self, ignore, show_state: bool, raw: bool, save_path: str | None) -> None:
        self.gate = MatchGate(ignore)
        self.ignore = ignore
        self.show_state = show_state
        self.raw = raw
        self.save = open(save_path, "a", encoding="utf-8") if save_path else None
        self._last_state_print = 0.0
        self._counts: dict[str, int] = {}

    def attach(self, listener: EventListener) -> "Monitor":
        self.gate.attach(listener)
        listener.on(ev.ALL, self._on_any)
        listener.on(ev.MATCH_CREATED, lambda d: self._line("MATCH CREATED", f"{d.get('playlist')} @ {d.get('arena')}"))
        listener.on(ev.GOAL_SCORED, self._on_goal)
        listener.on(ev.STATFEED_EVENT, self._on_statfeed)
        listener.on(ev.MATCH_ENDED, self._on_match_ended)
        listener.on(ev.MATCH_DESTROYED, lambda d: self._line("MATCH DESTROYED", ""))
        listener.on(ev.UPDATE_STATE, self._on_state)
        return self

    # raw/jsonl logging + counting for every event
    def _on_any(self, msg: dict) -> None:
        event = msg.get("event")
        self._counts[event] = self._counts.get(event, 0) + 1
        if self.save:
            self.save.write(json.dumps({"event": event, "data": msg.get("data")}) + "\n")
            self.save.flush()
        if self.raw:
            print(f"[{_ts()}] {event}\n{json.dumps(msg.get('data'), indent=2)}")

    def _line(self, label: str, detail: str = "", flag: str = "") -> None:
        if self.raw:
            return  # raw mode already printed the full payload
        tail = f"   {flag}" if flag else ""
        print(f"[{_ts()}] {label:<14} {detail}{tail}")

    def _on_goal(self, data: dict) -> None:
        scorer = (data.get("scorer") or {}).get("name", "?")
        team = data.get("team")
        speed = data.get("goal_speed")
        score = data.get("scoreboard")
        flag = "[WOULD TRACK]" if self.gate.active else "[ignored: not a real match]"
        self._line("GOAL", f"{scorer} (team {team}) {speed} kph  score {score}", flag)

    def _on_statfeed(self, data: dict) -> None:
        main = (data.get("main_target") or {}).get("name", "?")
        sec = (data.get("secondary_target") or {}).get("name")
        detail = f"{data.get('type')}: {main}" + (f" -> {sec}" if sec else "")
        self._line("STATFEED", detail)

    def _on_match_ended(self, data: dict) -> None:
        real = is_real_match(data.get("players", []), data.get("playlist"), self.ignore)
        teams = data.get("teams", [])
        scores = "-".join(str(t.get("score")) for t in teams) if teams else "?"
        flag = "[RECORDED to stats]" if real else "[ignored: freeplay/training]"
        self._line("MATCH ENDED", f"winner team {data.get('winner_team')}  {scores}", flag)

    def _on_state(self, data: dict) -> None:
        if not self.show_state:
            return
        now = time.time()
        if now - self._last_state_print < 1.0:
            return
        self._last_state_print = now
        game = data.get("game", {})
        me = next((p for p in data.get("players", []) if p.get("is_local")), None)
        boost = me.get("boost") if me else "?"
        status = "REAL MATCH" if self.gate.active else "not a match"
        teams = game.get("teams", [])
        scores = "-".join(str(t.get("score")) for t in teams) if teams else "?"
        self._line("state", f"{game.get('playlist')}  t={game.get('time_seconds')}s  "
                            f"score {scores}  your boost {boost}  [{status}]")

    def summary(self) -> None:
        print("\n--- event counts this session ---")
        for event, n in sorted(self._counts.items()):
            print(f"  {event:<16} {n}")
        if self.save:
            self.save.close()


def main(argv=None) -> None:
    config = load_config()
    p = argparse.ArgumentParser(description="Live Stats API event monitor / doctor.")
    p.add_argument("--url", default=config["stats_api_url"], help="Stats API URL (raw TCP).")
    p.add_argument("--show-state", action="store_true", help="include the per-tick UpdateState line.")
    p.add_argument("--raw", action="store_true", help="dump full JSON for every event.")
    p.add_argument("--save", help="append every event to a .jsonl file.")
    args = p.parse_args(argv)

    from .derive import CanonicalFeed
    ignore = tuple(config.get("ignore_playlists") or DEFAULT_IGNORE_PLAYLISTS)
    mon = Monitor(ignore, args.show_state, args.raw, args.save)
    listener = EventListener(args.url, config["reconnect_delay"])
    feed = CanonicalFeed(listener, config.get("local_player_name"),
                         config.get("supersonic_speed", 100.0), ignore)
    mon.attach(feed)

    print(f"Connecting to {args.url} … (waiting for the game; Ctrl+C to stop)")
    print("Tip: open Rocket League, go to freeplay, then start a match — watch the flags below.\n")
    try:
        feed.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        feed.stop()
        mon.summary()


if __name__ == "__main__":
    main()
