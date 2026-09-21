"""End-to-end test of the shared core.

Raw-TCP mock -> EventListener -> CanonicalFeed (normalize + derive) -> dispatch.
Proves the real wire format is parsed and high-level events are synthesized.
"""

from __future__ import annotations

import threading
import time
import unittest
from collections import Counter

from rlstats import events as ev
from rlstats.listener import EventListener
from rlstats.derive import CanonicalFeed
from tests.helpers import MockServerThread

PORT = 49150


class CoreTest(unittest.TestCase):
    def test_feed_receives_full_match(self) -> None:
        seen = Counter()
        goals = []
        ended = threading.Event()
        final = {}

        with MockServerThread(PORT):
            feed = CanonicalFeed(
                EventListener(f"tcp://127.0.0.1:{PORT}", reconnect_delay=0.5),
                local_name="You",
            )
            feed.on(ev.ALL, lambda m: seen.update([m["event"]]))
            feed.on(ev.GOAL_SCORED, goals.append)

            @feed.on(ev.MATCH_ENDED)
            def _end(data):
                final.update(data)
                ended.set()

            feed.start()
            self.assertTrue(feed.wait_connected(5), "listener never connected")
            self.assertTrue(ended.wait(15), "MatchEnded never arrived")
            time.sleep(0.2)
            feed.stop()

        # Lifecycle events fired in plausible quantities.
        self.assertEqual(seen[ev.MATCH_CREATED], 1)
        self.assertEqual(seen[ev.MATCH_ENDED], 1)
        self.assertGreater(seen[ev.UPDATE_STATE], 3)

        # MatchEnded carried a full per-player snapshot (canonical schema).
        self.assertEqual(len(final["players"]), 4)
        self.assertIn(final["winner_team"], (0, 1))
        for p in final["players"]:
            self.assertIn("name", p)
            self.assertIn("team", p)

        # Derived goals are well-formed (overtime guarantees at least one).
        self.assertGreaterEqual(len(goals), 1)
        for g in goals:
            self.assertIn("name", g["scorer"])
            self.assertIn(g["team"], (0, 1))


if __name__ == "__main__":
    unittest.main()
