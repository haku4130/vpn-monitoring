import unittest
from datetime import datetime, timezone

from history import (day_window, touch, add_fail, add_latency, prune,
                     hour_key, heat_rows, latency_medians)

T = datetime(2026, 11, 11, 7, 0, 30, tzinfo=timezone.utc).timestamp()
H = 3600


class History(unittest.TestCase):
    def test_window(self):
        w = day_window(T)
        self.assertEqual((len(w), w[0], w[-1]), (24, "2026-11-10T07", "2026-11-11T06"))

    def test_nodata_vs_clean_vs_fail(self):
        s = {}
        touch(s, T - 2 * H, "loc:A", False)
        add_fail(s, T - 3 * H, "loc:A"); add_fail(s, T - 3 * H, "exit:A")
        add_fail(s, T - 4 * H, "loc:A")
        touch(s, T - 5 * H, "loc:A", True)
        cells = heat_rows(s, T)["A"]
        self.assertEqual(cells[-2:], ["clean", "nodata"])
        self.assertEqual(cells[-3], "many"); self.assertEqual(cells[-4], "one"); self.assertEqual(cells[-5], "alert")
        self.assertEqual(cells[0], "nodata")

    def test_prune(self):
        s = {}
        touch(s, T - 30 * H, "loc:A", False); touch(s, T, "loc:A", False)
        prune(s, T)
        self.assertEqual(list(s["history"]["hours"]), [hour_key(T)])

    def test_median(self):
        s = {}
        for ms in (100, 300, 200):
            add_latency(s, T - 2 * H, "exit:A", ms)
        add_latency(s, T + H, "exit:A", 9999)  # вне окна
        self.assertEqual(latency_medians(s, T), {"A": 200})

    def test_divider_ignored(self):
        s = {}
        touch(s, T - H, "loc:👇 x 👇", False)
        self.assertEqual(heat_rows(s, T), {})

    def test_alerted_is_or_ed(self):
        s = {}
        touch(s, T - H, "loc:A", True)
        touch(s, T - H, "loc:A", False)
        self.assertEqual(s["history"]["hours"][hour_key(T - H)]["rows"]["loc:A"], [0, 1])
