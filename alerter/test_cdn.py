import unittest
from datetime import datetime, timedelta, timezone
from alerter import cdn_problem

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
EDGE = "198.51.100.1"
OTHER = "198.51.100.2"
CERT = NOW + timedelta(days=90)


class T(unittest.TestCase):
    def test_ok(self):
        self.assertIsNone(cdn_problem([EDGE], {EDGE: (200, CERT)}, NOW, 20))

    def test_ok_when_topology_moved_but_edge_serves(self):
        self.assertIsNone(cdn_problem([OTHER], {EDGE: (200, CERT)}, NOW, 20))

    def test_ok_without_topology(self):
        self.assertIsNone(cdn_problem([], {EDGE: (200, CERT)}, NOW, 20))

    def test_dead_edge_suggests_topology(self):
        p = cdn_problem([OTHER], {EDGE: (0, None)}, NOW, 20)
        self.assertIn(EDGE, p)
        self.assertIn("таймаут", p)
        self.assertIn("A-запись", p)
        self.assertIn(OTHER, p)

    def test_one_of_two_addresses_bad(self):
        p = cdn_problem([EDGE], {EDGE: (200, CERT), OTHER: (502, CERT)}, NOW, 20)
        self.assertIn("502", p)
        self.assertIn(OTHER, p)

    def test_domain_gone(self):
        self.assertIn("не резолвится", cdn_problem([EDGE], {}, NOW, 20))

    def test_cert_soon(self):
        self.assertIn("10 дн", cdn_problem([EDGE], {EDGE: (200, NOW + timedelta(days=10, hours=1))}, NOW, 20))

    def test_cert_unreadable(self):
        self.assertIn("сертификат", cdn_problem([EDGE], {EDGE: (200, None)}, NOW, 20))


if __name__ == "__main__":
    unittest.main()
