import unittest
from datetime import datetime, timedelta, timezone
from alerter import mask_problem

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
IP = "203.0.113.12"

class T(unittest.TestCase):
    def test_ok(self):
        self.assertIsNone(mask_problem([IP], IP, NOW + timedelta(days=60), NOW, 20))
    def test_dns_gone(self):
        self.assertIn("не резолвится", mask_problem([], IP, NOW + timedelta(days=60), NOW, 20))
    def test_dns_elsewhere(self):
        self.assertIn("1.2.3.4", mask_problem(["1.2.3.4"], IP, NOW + timedelta(days=60), NOW, 20))
    def test_cert_soon(self):
        self.assertIn("10 дн", mask_problem([IP], IP, NOW + timedelta(days=10, hours=1), NOW, 20))
    def test_cert_unreadable(self):
        self.assertIn("сертификат", mask_problem([IP], IP, None, NOW, 20))
    def test_cert_wrong_host(self):
        self.assertIn("не на домен", mask_problem([IP], IP, NOW + timedelta(days=60), NOW, 20, cert_matches=False))

if __name__ == "__main__":
    unittest.main()
