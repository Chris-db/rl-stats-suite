"""Raw-TCP client for Rocket League's real Stats API.

The shipped Stats API is **not** a WebSocket (the original spec was wrong about
that). It's a plain TCP socket on port 49123 that, the moment you connect,
streams JSON objects packed back-to-back with no delimiter::

    {"Event":"UpdateState","Data":"{...escaped json...}"}{"Event":"...","Data":...}

Two quirks this client handles:
  * objects are split by tracking brace depth (string-aware), since there's no
    newline between them;
  * ``Data`` is itself a JSON *string*, so it's decoded a second time.

Same pub/sub API as the rest of the suite (:meth:`on`, :meth:`start`, …) so it
can drop in as the listener once the data is normalised.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from collections import defaultdict
from typing import Callable

from . import events as ev

log = logging.getLogger("rlstats.tcp")

Handler = Callable[[dict], None]


def parse_host_port(url: str, default_port: int = 49123) -> tuple[str, int]:
    """Accept ws://host:port, tcp://host:port or host:port -> (host, port)."""
    u = url
    for scheme in ("ws://", "wss://", "tcp://", "http://"):
        if u.startswith(scheme):
            u = u[len(scheme):]
    u = u.split("/")[0]
    if ":" in u:
        host, port = u.rsplit(":", 1)
        try:
            return host or "127.0.0.1", int(port)
        except ValueError:
            return host or "127.0.0.1", default_port
    return u or "127.0.0.1", default_port


def split_json_objects(buffer: str) -> tuple[list[str], str]:
    """Split concatenated top-level JSON objects.

    Returns (complete_objects, remainder). String/escape aware so braces inside
    the (escaped) Data string don't confuse the depth count.
    """
    objects: list[str] = []
    depth = 0
    in_string = False
    escape = False
    start: int | None = None

    for i, ch in enumerate(buffer):
        if start is None:
            if ch == "{":
                start = i
                depth = 1
            continue
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    objects.append(buffer[start:i + 1])
                    start = None

    remainder = buffer[start:] if start is not None else ""
    return objects, remainder


class StatsApiClient:
    """Reconnecting raw-TCP reader with pub/sub dispatch."""

    def __init__(self, host: str = "127.0.0.1", port: int = 49123,
                 reconnect_delay: float = 3.0) -> None:
        self.host = host
        self.port = port
        self.reconnect_delay = reconnect_delay
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._raw_handlers: list[Callable[[str], None]] = []
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._connected = threading.Event()

    @classmethod
    def from_url(cls, url: str, reconnect_delay: float = 3.0) -> "StatsApiClient":
        host, port = parse_host_port(url)
        return cls(host, port, reconnect_delay)

    # --- subscription -----------------------------------------------------

    def on(self, event: str, handler: Handler | None = None):
        def register(fn: Handler) -> Handler:
            self._handlers[event].append(fn)
            return fn
        return register if handler is None else register(handler)

    def off(self, event: str, handler: Handler) -> None:
        try:
            self._handlers[event].remove(handler)
        except ValueError:
            pass

    def on_raw(self, handler: Callable[[str], None]) -> None:
        """Receive every raw (still-encoded) object string, before parsing."""
        self._raw_handlers.append(handler)

    def _emit(self, event: str, data: dict) -> None:
        for handler in list(self._handlers.get(event, ())):
            self._safe(handler, data)
        for handler in list(self._handlers.get(ev.ALL, ())):
            self._safe(handler, {"event": event, "data": data})

    @staticmethod
    def _safe(handler, payload) -> None:
        try:
            handler(payload)
        except Exception:  # noqa: BLE001
            log.exception("handler %r raised", getattr(handler, "__name__", handler))

    # --- parsing ----------------------------------------------------------

    def _handle_object(self, raw: str) -> None:
        for h in list(self._raw_handlers):
            self._safe(h, raw)
        try:
            envelope = json.loads(raw)
        except ValueError:
            log.debug("could not parse object: %r", raw[:120])
            return
        event = envelope.get("Event") or envelope.get("event")
        data = envelope.get("Data")
        if data is None:
            data = envelope.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {"raw": data}
        if not event:
            return
        self._emit(event, data if isinstance(data, dict) else {"value": data})

    # --- lifecycle --------------------------------------------------------

    def run_forever(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=10)
            except OSError as exc:
                log.debug("connect failed: %s", exc)
                self._stop.wait(self.reconnect_delay)
                continue

            self._connected.set()
            log.info("connected (raw TCP) to %s:%d", self.host, self.port)
            self._sock.settimeout(1.0)
            buffer = ""
            try:
                while not self._stop.is_set():
                    try:
                        chunk = self._sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break  # server closed (left match / quit)
                    buffer += chunk.decode("utf-8", errors="replace")
                    objects, buffer = split_json_objects(buffer)
                    for obj in objects:
                        self._handle_object(obj)
            except OSError as exc:
                log.debug("socket error: %s", exc)
            finally:
                self._connected.clear()
                self._close_sock()
            if not self._stop.is_set():
                log.info("disconnected - waiting for the game…")
                self._stop.wait(self.reconnect_delay)

    def _close_sock(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def start(self) -> "StatsApiClient":
        if self._thread and self._thread.is_alive():
            return self
        self._thread = threading.Thread(target=self.run_forever,
                                        name="rlstats-tcp", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._close_sock()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def wait_connected(self, timeout: float | None = None) -> bool:
        return self._connected.wait(timeout)

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()
