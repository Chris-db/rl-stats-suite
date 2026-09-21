"""Stream Alert App server.

The brain that decides when alerts fire. It:
  1. listens to the Stats API (shared core),
  2. builds a flat context per event and evaluates the user's rules,
  3. pushes matched alerts to the OBS overlay over its own local WebSocket,
  4. serves the overlay page over HTTP so OBS can load it as a browser source.

OBS setup: add a Browser source pointing at
``http://<host>:<http_port>/`` (printed on startup). The overlay connects back
to the push socket automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import logging
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os

import websockets

from rlstats import events as ev, load_config, make_feed
from . import rules as rules_mod

log = logging.getLogger("rlstats.alerts.server")

OVERLAY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay")


class _OverlayHTTPHandler(SimpleHTTPRequestHandler):
    """Serves the overlay directory and a /config.json with the push-socket URL."""

    ws_url = "ws://127.0.0.1:8765"

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/config.json":
            body = json.dumps({"ws_url": self.ws_url}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):  # quieter logs
        log.debug("http: " + args[0], *args[1:])


class AlertServer:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.local_name = config.get("local_player_name")
        self.rules = rules_mod.load_rules(config.get("alert_rules_path"))
        self.host = config["alert_overlay_host"]
        self.http_port = config["alert_overlay_http_port"]
        self.ws_port = config["alert_overlay_ws_port"]

        self.clients: set = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop = asyncio.Event()

        # tracked local identity + supersonic edge detection
        self.local_team: int | None = None
        self._was_supersonic = False

    # --- identity helpers -------------------------------------------------

    def _is_me(self, ref: dict | None) -> bool:
        if not ref:
            return False
        if ref.get("is_local"):
            return True
        return bool(self.local_name) and ref.get("name") == self.local_name

    def _remember_local(self, players: list[dict]) -> None:
        for p in players:
            if self._is_me(p):
                self.local_team = p.get("team")
                if not self.local_name:
                    self.local_name = p.get("name")
                return

    # --- context builders -------------------------------------------------

    def _ctx_goal(self, data: dict) -> dict:
        scorer = data.get("scorer") or {}
        assister = data.get("assister") or {}
        team = data.get("team")
        ctx = {
            "scorer": scorer.get("name"),
            "assister": assister.get("name"),
            "goal_speed": data.get("goal_speed"),
            "team": team,
            "scored_by_me": self._is_me(scorer),
            "assisted_by_me": self._is_me(assister),
            "is_overtime": data.get("is_overtime", False),
        }
        ctx["conceded"] = (
            self.local_team is not None and team is not None and team != self.local_team
        )
        return ctx

    def _ctx_statfeed(self, data: dict) -> dict:
        main = data.get("main_target") or {}
        secondary = data.get("secondary_target") or {}
        return {
            "statfeed_type": data.get("type"),
            "main": main.get("name"),
            "secondary": secondary.get("name"),
            "victim": secondary.get("name"),
            "by_me": self._is_me(main),
            "against_me": self._is_me(secondary),
        }

    # --- event handling (runs on the listener thread) ---------------------

    def _on_update(self, data: dict) -> None:
        players = data.get("players", [])
        self._remember_local(players)
        # also surface any embedded statfeed the mock rides along with state
        statfeed = data.get("last_statfeed")
        if statfeed:
            self._on_statfeed(statfeed)
        # supersonic rising-edge -> synthetic event
        me = next((p for p in players if self._is_me(p)), None)
        if me is not None:
            now_super = bool(me.get("is_supersonic"))
            if now_super and not self._was_supersonic:
                self._fire("Supersonic", {"speed": me.get("speed")})
            self._was_supersonic = now_super

    def _on_goal(self, data: dict) -> None:
        self._fire(ev.GOAL_SCORED, self._ctx_goal(data))

    def _on_statfeed(self, data: dict) -> None:
        self._fire(ev.STATFEED_EVENT, self._ctx_statfeed(data))

    def _fire(self, event: str, context: dict) -> None:
        for alert in rules_mod.evaluate(self.rules, event, context):
            log.info("ALERT: %s — %s", alert.get("title"), alert.get("rule"))
            self._push(alert)

    def _push(self, alert: dict) -> None:
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(alert), self.loop)

    # --- overlay socket (async) -------------------------------------------

    async def _broadcast(self, alert: dict) -> None:
        if not self.clients:
            return
        message = json.dumps(alert)
        for ws in list(self.clients):
            try:
                await ws.send(message)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)

    async def _overlay_handler(self, websocket, path=None):
        self.clients.add(websocket)
        log.info("overlay connected (%d total)", len(self.clients))
        try:
            async for message in websocket:
                # overlay can ask the server to fire a test alert
                if message == "ping":
                    await websocket.send(json.dumps({"title": "Connected",
                                                     "subtitle": "overlay is live",
                                                     "icon": "✅", "color": "#34d399",
                                                     "animation": "slide",
                                                     "duration_ms": 2000}))
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.clients.discard(websocket)
            log.info("overlay disconnected (%d left)", len(self.clients))

    # --- lifecycle --------------------------------------------------------

    def _start_http(self) -> ThreadingHTTPServer:
        _OverlayHTTPHandler.ws_url = f"ws://{self.host}:{self.ws_port}"
        handler = functools.partial(_OverlayHTTPHandler, directory=OVERLAY_DIR)
        httpd = ThreadingHTTPServer((self.host, self.http_port), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd

    async def _main(self) -> None:
        self.loop = asyncio.get_running_loop()

        httpd = self._start_http()
        log.info("overlay page:  http://%s:%d/   (add as OBS browser source)",
                 self.host, self.http_port)

        feed = make_feed(self.config)
        feed.on(ev.UPDATE_STATE, self._on_update)
        feed.on(ev.GOAL_SCORED, self._on_goal)
        feed.on(ev.STATFEED_EVENT, self._on_statfeed)
        feed.start()

        async with websockets.serve(self._overlay_handler, self.host, self.ws_port):
            log.info("alert push socket: ws://%s:%d", self.host, self.ws_port)
            log.info("waiting for events (Ctrl+C to stop)…")
            try:
                await self._stop.wait()
            finally:
                feed.stop()
                httpd.shutdown()
                httpd.server_close()

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except KeyboardInterrupt:
            pass


def run(config: dict | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    AlertServer(config or load_config()).run()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Rocket League stream alert server.")
    parser.add_argument("--rules", help="path to a rules JSON file.")
    args = parser.parse_args(argv)
    config = load_config()
    if args.rules:
        config["alert_rules_path"] = args.rules
    run(config)


if __name__ == "__main__":
    main()
