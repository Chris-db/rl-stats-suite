"""The shared event listener — the core every tool is built on.

Connects to the Rocket League Stats API and dispatches each ``{"Event":...,
"Data":...}`` message to subscribers registered with :meth:`EventListener.on`.
Auto-reconnects when the game isn't running yet and survives the socket dropping
when a match ends.

Transport note: the real Stats API is a **raw TCP** socket (not a WebSocket, as
some docs claim) that streams JSON objects packed back-to-back, with ``Data``
itself double-encoded as a string. All of that is handled by
:class:`rlstats.tcp_client.StatsApiClient`; this class just adapts it to the
URL-based constructor the rest of the suite uses.

Example
-------
    from rlstats.listener import EventListener
    from rlstats import events

    listener = EventListener()

    @listener.on(events.UPDATE_STATE)
    def on_state(data):
        print(data["Game"]["TimeSeconds"])

    listener.run_forever()          # blocking
    # or: listener.start() / listener.stop() for background use

Most tools don't subscribe here directly — they wrap the listener in a
:class:`rlstats.derive.CanonicalFeed`, which normalises the data and adds
synthesized GoalScored / MatchEnded events.
"""

from __future__ import annotations

from .tcp_client import StatsApiClient, parse_host_port

DEFAULT_URL = "tcp://127.0.0.1:49123"


class EventListener(StatsApiClient):
    """Raw-TCP Stats API listener with URL-based construction."""

    def __init__(self, url: str = DEFAULT_URL, reconnect_delay: float = 3.0) -> None:
        host, port = parse_host_port(url)
        super().__init__(host, port, reconnect_delay)
