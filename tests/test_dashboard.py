"""Tests for the Flask dashboard: routes return 200 and well-formed JSON."""

from __future__ import annotations

import unittest

from tracker import db, seed, dashboard


class DashboardRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = ":memory:"
        # The dashboard opens its own connections per request, so seed via a
        # shared on-disk temp DB instead of :memory: (which wouldn't be shared).
        import tempfile, os
        cls.tmp = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmp, "matches.db")
        conn = db.connect(cls.db_path)
        seed.generate(conn, matches=30, seed=1)
        conn.close()
        cls.app = dashboard.create_app({"database_path": cls.db_path})
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_index_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Rocket League Stats", r.data)

    def test_overview(self):
        r = self.client.get("/api/overview")
        self.assertEqual(r.status_code, 200)
        o = r.get_json()
        self.assertEqual(o["matches"], 30)
        self.assertEqual(o["wins"] + o["losses"], 30)
        self.assertTrue(0.0 <= o["win_rate"] <= 1.0)

    def test_list_endpoints(self):
        for route, min_len in [
            ("/api/win-rate", 30),
            ("/api/saves-trend", 30),
            ("/api/arenas", 1),
            ("/api/sessions", 1),
            ("/api/recent", 1),
        ]:
            with self.subTest(route=route):
                r = self.client.get(route)
                self.assertEqual(r.status_code, 200)
                body = r.get_json()
                self.assertIsInstance(body, list)
                self.assertGreaterEqual(len(body), min_len)

    def test_winrate_is_cumulative(self):
        rows = self.client.get("/api/win-rate").get_json()
        self.assertEqual(rows[0]["n"], 1)
        self.assertEqual(rows[-1]["n"], 30)
        for r in rows:
            self.assertTrue(0.0 <= r["cumulative_win_rate"] <= 1.0)


if __name__ == "__main__":
    unittest.main()
