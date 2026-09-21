"""End-to-end: live mock goals -> CanonicalFeed -> HighlightRecorder positions."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from rlstats.listener import EventListener
from rlstats.derive import CanonicalFeed
from highlights.recorder import HighlightRecorder
from highlights.sync import SyncSession
from tests.helpers import MockServerThread

PORT = 49153


class HighlightRecorderE2ETest(unittest.TestCase):
    def test_records_goal_positions_from_live_feed(self):
        with MockServerThread(PORT, loop=True, oneshot=False,
                              match_seconds=20.0, speed=40.0, tick_hz=20.0):
            session = SyncSession.start_now(video_path="match.mkv")
            save_path = os.path.join(tempfile.mkdtemp(), "s.json")
            feed = CanonicalFeed(
                EventListener(f"tcp://127.0.0.1:{PORT}", reconnect_delay=0.5),
                local_name="You",
            )
            HighlightRecorder(session, save_path).attach(feed)
            feed.start()
            self.assertTrue(feed.wait_connected(5))

            deadline = time.time() + 25
            while len(session.goals) < 3 and time.time() < deadline:
                time.sleep(0.1)
            feed.stop()

        self.assertGreaterEqual(len(session.goals), 3, "no goals were logged")
        positions = session.positions()
        self.assertTrue(all(p >= 0 for p in positions))
        self.assertEqual(positions, sorted(positions))
        reloaded = SyncSession.load(save_path)
        self.assertEqual(reloaded.positions(), positions)


if __name__ == "__main__":
    unittest.main()
