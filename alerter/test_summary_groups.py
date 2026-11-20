import unittest
from summary import group_alerts, format_events

YT = "YouTube видит страну FI (нужна RU) — будет реклама"


def yt_checks(n):
    return {"yt:🇩🇪 Loc%d" % i: {"alerted": True, "alerted_at": 1000 + i, "last_detail": YT} for i in range(n)}


class Groups(unittest.TestCase):
    def test_same_detail_glued(self):
        checks = yt_checks(12) | {"quota_src:exit-5": {"alerted": True, "alerted_at": 10, "last_detail": "нода не отдаёт счётчики"}}
        g = group_alerts(checks)
        self.assertEqual([x.title for x in g], ["Счётчики трафика: exit-5", "Реклама YouTube — 12 локаций"])
        self.assertEqual(g[1].since, 1000)
        self.assertEqual(g[1].short_detail, "страна FI вместо RU")
        self.assertEqual(g[1].icon, "📺")

    def test_different_detail_not_glued(self):
        checks = {"loc:A": {"alerted": True, "last_detail": "node-b (1:1)"}, "loc:B": {"alerted": True, "last_detail": "node-b (1:2)"}}
        self.assertEqual(len(group_alerts(checks)), 2)

    def test_divider_and_not_alerted_skipped(self):
        checks = {"loc:👇 x 👇": {"alerted": True}, "loc:A": {"alerted": False}}
        self.assertEqual(group_alerts(checks), [])

    def test_single_flag_icon(self):
        g = group_alerts({"loc:🇳🇱 Нидерланды": {"alerted": True, "last_detail": "x"}})
        self.assertEqual(g[0].icon, "🇳🇱")

    def test_unknown_prefix_no_icon(self):
        g = group_alerts({"mass_outage": {"alerted": True, "last_detail": "x"}})
        self.assertIsNone(g[0].icon)


class Events(unittest.TestCase):
    def test_glued_with_quote(self):
        ev = [("down", "yt:Loc%d" % i, YT) for i in range(12)]
        t = format_events(ev)
        self.assertEqual(t.count("• "), 1)
        self.assertIn("Реклама YouTube — 12 локаций — " + YT, t)
        self.assertIn("<blockquote expandable>Loc0\nLoc1", t)

    def test_single_event_unchanged(self):
        self.assertEqual(format_events([("down", "loc:A", "x <y>")]), "🔴 <b>Проблема</b>\n• Локация A — x &lt;y&gt;")

    def test_warn_block_order(self):
        t = format_events([("up", "loc:A", ""), ("warn", "quota:exit-1", "80%"), ("down", "loc:B", "")])
        self.assertLess(t.index("Проблема"), t.index("Предупреждение"))
        self.assertLess(t.index("Предупреждение"), t.index("Восстановилось"))

    def test_empty(self):
        self.assertEqual(format_events([]), "")


class CardTitle(unittest.TestCase):
    def _t(self, *keys):
        from summary import AlertGroup
        g = AlertGroup(keys[0].partition(":")[0], "", list(keys))
        return g.title, g.card_title

    def test_exit(self):
        t, c = self._t("exit:🔎 🇳🇱 Нидерланды · node-b")
        self.assertEqual(c, "Выход у «Нидерланды · node-b»")
        self.assertIn("🔎", t)

    def test_loc_number_moved(self):
        self.assertEqual(self._t("loc:🇫🇮 #1 Финляндия")[1], "Локация Финляндия #1")

    def test_yt_and_ytspeed(self):
        self.assertEqual(self._t("yt:🇸🇪 Швеция")[1], "Реклама YouTube на «Швеция»")
        self.assertEqual(self._t("ytspeed:🇸🇪 Швеция")[1], "YouTube на «Швеция»")

    def test_multi_key_unchanged(self):
        t, c = self._t("yt:🇸🇪 A", "yt:🇩🇪 B")
        self.assertEqual((t, c), ("Реклама YouTube — 2 локации",) * 2)
