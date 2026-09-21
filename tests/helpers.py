"""Shared test helpers: run the mock server on a background thread."""

from __future__ import annotations

import asyncio
import threading

from rlstats.mock_server import MockServer


class MockServerThread:
    """Runs a MockServer in its own asyncio loop on a daemon thread."""

    def __init__(self, port: int, **kwargs) -> None:
        kwargs.setdefault("speed", 40.0)
        kwargs.setdefault("tick_hz", 20.0)
        kwargs.setdefault("match_seconds", 20.0)
        kwargs.setdefault("loop", False)
        kwargs.setdefault("oneshot", True)
        kwargs.setdefault("local_name", "You")
        kwargs.setdefault("seed", 7)
        self.server = MockServer("127.0.0.1", port, **kwargs)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.run(self.server.serve())

    def __enter__(self) -> MockServer:
        self._thread.start()
        return self.server

    def __exit__(self, *exc) -> None:
        try:
            # Ask the loop to stop, then let the daemon thread die.
            loop = getattr(self.server._stop, "_loop", None)
            if loop and loop.is_running():
                loop.call_soon_threadsafe(self.server._stop.set)
        except Exception:  # noqa: BLE001
            pass
        self._thread.join(timeout=3)
