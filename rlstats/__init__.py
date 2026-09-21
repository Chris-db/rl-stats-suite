"""Shared core for the Rocket League Stats Suite.

Exposes the event listener and event-name constants that every tool builds on.
"""

from __future__ import annotations

from . import events
from .config import load_config
from .listener import EventListener


def _canonical_feed():  # lazy to avoid import cost when unused
    from .derive import CanonicalFeed
    return CanonicalFeed


def make_feed(config: dict | None = None):
    """Build a CanonicalFeed (real-TCP listener + normalize + derive)."""
    from .derive import CanonicalFeed
    return CanonicalFeed.from_config(config or load_config())


__all__ = ["EventListener", "events", "load_config", "make_feed"]
