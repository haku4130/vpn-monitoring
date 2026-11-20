import unittest
from datetime import datetime, timezone

from demo_data import demo_summary, demo_state
from summary import build_models, caption_parts, visible_len

NOW = datetime(2026, 11, 11, 7, 0, 30, tzinfo=timezone.utc).timestamp()
BLIPS = {"mass_outage": 2, "yt:🇩🇪 Германия": 3, "loc:🇩🇪 Германия": 1, "ytspeed:🇷🇺 Россия": 2, "source:ip": 1}


class BlipLabels(unittest.TestCase):
    def test_keys_not_merged_and_not_empty(self):
        st = {"checks": {}, "blips": BLIPS}
        line = build_models(demo_summary(), st, NOW).dashboard.blips_line
        self.assertTrue(line.startswith("Одиночных сбоев без тревоги: 9 · чаще всех: "))
        self.assertIn("Реклама YouTube на «🇩🇪 Германия» 3", line)
        self.assertIn("Массовое падение локаций 2", line)
        _, d = caption_parts(demo_summary(), st, NOW)
        quote = [x for x in d.split("\n") if x.startswith("Сбои без тревоги")][0]
        for part in ("Германия 1", "Реклама YouTube на «🇩🇪 Германия» 3", "Массовое падение локаций 2",
                     "YouTube на «🇷🇺 Россия» 2", "Источник данных: ip 1"):
            self.assertIn(part, quote)
        self.assertNotIn(" 1, 1", quote)
        self.assertNotIn(": 2", quote.replace("Массовое падение локаций 2", ""))
        h, _ = caption_parts(demo_summary(), st, NOW)
        self.assertIn("сбоев без тревоги 9", h)

    def test_loc_and_exit_merge_by_name(self):
        st = {"checks": {}, "blips": {"loc:🇩🇪 Германия": 1, "exit:🇩🇪 Германия": 2}}
        self.assertIn("Германия 3", build_models({}, st, NOW).dashboard.blips_line)


class Utf16(unittest.TestCase):
    def test_flag_counts_four(self):
        self.assertEqual(visible_len("🇩🇪"), 4)
        self.assertEqual(visible_len("<b>a 🟢 &lt;</b>"), 6)


class QuoteLines(unittest.TestCase):
    def test_multi_key_has_reason(self):
        checks = {"loc:A": {"alerted": True, "last_detail": "таймаут <1>"},
                  "loc:B": {"alerted": True, "last_detail": "таймаут <1>"}}
        _, d = caption_parts({}, {"checks": checks}, NOW)
        self.assertEqual(d, "Локации — 2 локации: A, B — таймаут &lt;1&gt;")

    def test_single_key_separator(self):
        checks = {"quota_src:exit-5": {"alerted": True, "last_detail": "нода недоступна"}}
        _, d = caption_parts({}, {"checks": checks}, NOW)
        self.assertEqual(d, "Счётчики трафика: exit-5 — нода недоступна")

    def test_traffic_with_limit(self):
        s = {"quota": {"exit-1": (1536.4, 2000), "exit-4": (10.0, 0)}}
        _, d = caption_parts(s, {"checks": {}}, NOW)
        self.assertIn("Трафик: exit-1 1536 из 2000 ГиБ (77%), exit-4 10 ГиБ", d)


class NoExits(unittest.TestCase):
    def test_exit_checker_unavailable(self):
        s = demo_summary()
        del s["exits"]
        mx = build_models(s, demo_state(NOW), NOW).matrix
        de = next(r for r in mx.rows if r.name == "Германия")
        self.assertEqual(de.cells[0], ("жив", "none"))
        self.assertEqual(mx.badge, ("none", "выходы не проверены"))

    def test_down_still_bad_without_exits(self):
        s = demo_summary()
        del s["exits"]
        for (n, a), v in s["locations"].items():
            if n == "🇩🇪 Германия":
                v["status"] = 0.0
        mx = build_models(s, demo_state(NOW), NOW).matrix
        self.assertEqual(mx.badge[0], "bad")


if __name__ == "__main__":
    unittest.main()
