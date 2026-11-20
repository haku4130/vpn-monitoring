import unittest
from alerter import yt_region_targets

PORTS = [
    (10001, "🇩🇪 Германия"),
    (10002, "👇 🚧 Специальные локации 🚧 👇"),
    (10003, "🇩🇪 Германия (личный)"),
    (10004, "🇵🇱 Польша (личный)"),
]


class Targets(unittest.TestCase):
    def test_headers_always_skipped(self):
        self.assertEqual([n for _, n in yt_region_targets(PORTS)],
                         ["🇩🇪 Германия", "🇩🇪 Германия (личный)", "🇵🇱 Польша (личный)"])

    def test_skip_pattern(self):
        self.assertEqual(yt_region_targets(PORTS, r"\(личный\)"), [(10001, "🇩🇪 Германия")])

    def test_empty_pattern_skips_nothing_extra(self):
        self.assertEqual(len(yt_region_targets(PORTS, "")), 3)


if __name__ == "__main__":
    unittest.main()
