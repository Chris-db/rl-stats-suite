"""End-to-end test for Tool 2.

Mock Stats API -> AlertServer (listener + rules + push socket) -> overlay client.
Proves the threaded listener -> asyncio broadcast bridge actually delivers a
rule-matched alert to a connected overlay.
"""

from __future__ import annotations

import json
import threading
import time
import unittest

from websockets.sync.client import connect

from alerts.server import AlertServer
from tests.helpers import MockServerThread

MOCK_PORT = 49152
HTTP_PORT = 8091
WS_PORT = 8767


def make_config():
    return {
        "local_player_name": None,
        "alert_rules_path": None,           # falls back to rules.example.json
        "alert_overlay_host": "127.0.0.1",
        "alert_overlay_http_port": HTTP_PORT,
        "alert_overlay_ws_port": WS_PORT,
        "stats_api_url": f"ws://127.0.0.1:{MOCK_PORT}",
        "reconnect_delay": 0.5,
    }


class AlertEndToEndTest(unittest.TestCase):
    def test_match_produces_overlay_alert(self):
        server = AlertServer(make_config())
        threading.Thread(target=server.run, daemon=True).start()

        with MockServerThread(MOCK_PORT, loop=True, oneshot=False,
                              match_seconds=20.0, speed=40.0, tick_hz=20.0):
            client = None
            for _ in range(60):                      # wait for the push socket
                try:
                    client = connect(f"ws://127.0.0.1:{WS_PORT}")
                    break
                except Exception:
                    time.sleep(0.1)
            self.assertIsNotNone(client, "overlay push socket never came up")

            real_alert = None
            deadline = time.time() + 20
            try:
                while time.time() < deadline:
                    try:
                        msg = json.loads(client.recv(timeout=2))
                    except TimeoutError:
                        continue
                    # The "ping" reply has no rule; real fired alerts do.
                    if msg.get("rule"):
                        real_alert = msg
                        break
            finally:
                client.close()

            self.assertIsNotNone(real_alert, "no rule-matched alert was delivered")
            self.assertIn("title", real_alert)
            self.assertIn("animation", real_alert)

        if server.loop is not None:
            server.loop.call_soon_threadsafe(server._stop.set)


if __name__ == "__main__":
    unittest.main()
