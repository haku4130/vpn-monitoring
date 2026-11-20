import unittest
from datetime import datetime, timezone

from demo_data import demo_summary, demo_state
from summary import caption_parts, compose_caption, fallback_text, visible_len

NOW = datetime(2026, 11, 11, 7, 0, 30, tzinfo=timezone.utc).timestamp()


class CaptionTest(unittest.TestCase):
    def test_header_demo(self):
        h, d = caption_parts(demo_summary(), demo_state(NOW), NOW)
        lines = h.split("\n")
        self.assertEqual(lines[0], "<b>Мониторинг · сутки</b> до 11.11 07:00 UTC")
        self.assertEqual(lines[1], "🔴 <b>Висят 2 тревоги</b>")
        self.assertTrue(lines[2].startswith("• Счётчики трафика: exit-5 · 3 д"))
        self.assertTrue(lines[3].startswith("• "))
        self.assertEqual(lines[4], "🟢 Локации 15/15 · выходы 14/14 · HAProxy 6/6")
        self.assertEqual(lines[5], "🟡 YouTube без рекламы 2/14 · сбоев без тревоги 14")
        self.assertEqual(len(lines), 6)
        cap, extra = compose_caption(h, d)
        self.assertIsNone(extra)
        self.assertLessEqual(visible_len(cap), 1024)

    def test_details_demo(self):
        _, d = caption_parts(demo_summary(), demo_state(NOW), NOW)
        self.assertIn("Медленнее всех: Великобритания 546 мс", d)
        self.assertIn("Трафик: exit-1 1210 ГиБ", d)
        self.assertIn("Сбои без тревоги: ", d)
        self.assertNotIn("Не работает", d)
        self.assertNotIn("HAProxy не UP", d)

    def test_slowest_uses_day_median_not_last_sample(self):
        import history
        s = demo_summary()
        st = {"checks": {}}
        uk = "exit:🇬🇧 Великобритания"
        nl = "exit:🔎 🇳🇱 Нидерланды · node-b"
        for i in range(10):
            history.add_latency(st, NOW - 3600 * (i + 1), uk, 200)
            history.add_latency(st, NOW - 3600 * (i + 1), nl, 700)
        _, d = caption_parts(s, st, NOW)
        line = [x for x in d.split("\n") if x.startswith("Медленнее всех")][0]
        self.assertTrue(line.startswith("Медленнее всех (медиана за сутки): Нидерланды · node-b 700 мс"), line)
        self.assertIn("Великобритания 200 мс", line)
        self.assertNotIn("546", line)

    def test_no_alerts(self):
        h, _ = caption_parts(demo_summary(), {"checks": {}}, NOW)
        self.assertEqual(h.split("\n")[1], "💚 Тревог нет")

    def test_circles_by_ratio_only(self):
        s = demo_summary()
        for k in list(s["haproxy"])[:3]:
            s["haproxy"][k] = "DOWN"
        h, d = caption_parts(s, {"checks": {}, "blips": {"loc:a": 5}}, NOW)
        lines = h.split("\n")
        self.assertEqual(lines[2], "🟡 Локации 15/15 · выходы 14/14 · HAProxy 3/6")
        self.assertIn("HAProxy не UP: be_smtp/exit-4", d)
        h, _ = caption_parts({}, {"checks": {}, "blips": {"loc:a": 5}}, NOW)
        self.assertEqual(h.split("\n")[2], "сбоев без тревоги 5")
        self.assertEqual(len(caption_parts({}, {"checks": {}}, NOW)[0].split("\n")), 2)

    def test_many_groups_header_max_7(self):
        checks = {"loc:%s" % ("Я" * 200 + str(i)): {"alerted": True, "last_detail": str(i)} for i in range(20)}
        h, d = caption_parts(demo_summary(), {"checks": checks}, NOW)
        self.assertLessEqual(len(h.split("\n")), 7)
        self.assertIn("• и ещё 18", h)
        self.assertNotIn("Я" * 81, h)
        cap, extra = compose_caption(h, d)
        self.assertLessEqual(visible_len(cap), 1024)
        self.assertIsNotNone(extra)
        self.assertTrue(extra.startswith("<b>Подробности</b>\n<blockquote expandable>"))
        self.assertLessEqual(len(extra), 4096)
        self.assertEqual(extra.count("<blockquote expandable>"), 1)
        self.assertEqual(extra.count("</blockquote>"), 1)
        self.assertTrue(extra.endswith("\n…</blockquote>"))

    def test_html_escaped_and_counted(self):
        self.assertEqual(visible_len("<b>a &lt;b&gt;</b>"), 5)
        checks = {"loc:<x>&": {"alerted": True, "last_detail": "d"}}
        h, d = caption_parts({}, {"checks": checks}, NOW)
        self.assertIn("&lt;x&gt;&amp;", h)
        self.assertNotIn("<x>", h + d)

    def test_fallback_limit(self):
        t = fallback_text("h", "строка\n" * 2000)
        self.assertLessEqual(len(t), 4096)
        self.assertTrue(t.endswith("…</blockquote>"))
        t = fallback_text("h", "A&amp;B &lt;x&gt; &amp;&amp;\n" * 600)
        self.assertLessEqual(len(t), 4096)
        self.assertEqual(t.count("<blockquote expandable>"), 1)
        self.assertEqual(t.count("</blockquote>"), 1)
        self.assertTrue(t.endswith("\n…</blockquote>"))
        short = fallback_text("h", "a\nb")
        self.assertEqual(short, "h\n<blockquote expandable>a\nb</blockquote>")
