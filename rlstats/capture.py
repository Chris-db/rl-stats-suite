"""Live capture / doctor for the REAL Rocket League Stats API (raw TCP).

Connects to the game, prints every event, and saves the raw feed to a .jsonl
file. UpdateState is throttled (it fires many times a second); every other event
is printed in full, so we can see the exact shape of goals, demos, saves and
match start/end as they happen.

    python rl.py capture            # print + save to data/captures/feed_<ts>.jsonl
    python rl.py capture --no-save  # just print
"""

from __future__ import annotations

import argparse
import json
import os
import time

from . import load_config
from .tcp_client import StatsApiClient


def _ts() -> str:
    return time.strftime("%H:%M:%S")


class Capture:
    def __init__(self, save_path: str | None) -> None:
        self.save = open(save_path, "a", encoding="utf-8") if save_path else None
        self.save_path = save_path
        self.counts: dict[str, int] = {}
        self._last_state = 0.0

    def attach(self, client: StatsApiClient) -> "Capture":
        client.on_raw(self._on_raw)
        from . import events as ev
        client.on(ev.ALL, self._on_event)
        return self

    def _on_raw(self, raw: str) -> None:
        if self.save:
            self.save.write(raw + "\n")
            self.save.flush()

    def _on_event(self, msg: dict) -> None:
        event = msg.get("event")
        data = msg.get("data", {})
        self.counts[event] = self.counts.get(event, 0) + 1

        if event == "UpdateState":
            now = time.time()
            if now - self._last_state < 1.0:
                return
            self._last_state = now
            game = data.get("Game", {}) if isinstance(data, dict) else {}
            teams = game.get("Teams", [])
            score = "-".join(str(t.get("Score")) for t in teams) if teams else "?"
            players = data.get("Players", []) if isinstance(data, dict) else []
            print(f"[{_ts()}] UpdateState   score {score}  "
                  f"time {game.get('TimeSeconds')}s  players {len(players)}  "
                  f"arena {game.get('Arena')}")
        else:
            # Print the full payload for anything that isn't a routine tick —
            # this is how we learn the real goal/demo/save/match-end formats.
            print(f"\n[{_ts()}] === {event} ===")
            print(json.dumps(data, indent=2)[:1500])
            print()

    def summary(self) -> None:
        print("\n--- events captured this session ---")
        for event, n in sorted(self.counts.items()):
            print(f"  {event:<18} {n}")
        if self.save:
            self.save.close()
            print(f"\nRaw feed saved to: {self.save_path}")
            print("Send me that file (or paste a few non-UpdateState lines) to finish setup.")


def main(argv=None) -> None:
    config = load_config()
    p = argparse.ArgumentParser(description="Capture the real Stats API feed (raw TCP).")
    p.add_argument("--url", default=config["stats_api_url"])
    p.add_argument("--no-save", action="store_true", help="don't write a capture file.")
    args = p.parse_args(argv)

    save_path = None
    if not args.no_save:
        d = os.path.join(config["highlight_sessions_dir"], "..", "captures")
        d = os.path.normpath(d)
        os.makedirs(d, exist_ok=True)
        save_path = os.path.join(d, time.strftime("feed_%Y%m%d_%H%M%S.jsonl"))

    cap = Capture(save_path)
    client = StatsApiClient.from_url(args.url, config["reconnect_delay"])
    cap.attach(client)

    print(f"Connecting to Rocket League Stats API at {args.url} (raw TCP)…")
    print("Open the game; the lines below appear as events happen. Ctrl+C to stop.")
    if save_path:
        print(f"Saving raw feed to: {save_path}\n")
    try:
        client.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        client.stop()
        cap.summary()


if __name__ == "__main__":
    main()
