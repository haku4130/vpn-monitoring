import copy
import unittest
from datetime import datetime, timezone

from demo_data import demo_summary, demo_state, demo_history
from summary import build_models, period_text

NOW = datetime(2026, 11, 11, 7, 0, 30, tzinfo=timezone.utc).timestamp()


def with_history(st):
    demo_history(st, NOW)
    return st


class Dashboard(unittest.TestCase):
    def test_dashboard_tiles(self):
        m = build_models(demo_summary(), demo_state(NOW), NOW).dashboard
        self.assertEqual([(t.label, t.value, t.status) for t in m.tiles],
                         [("Локации", "15/15", "ok"), ("Выходы", "14/14", "ok"),
                          ("YouTube без рекламы", "2/14", "warn"), ("HAProxy", "6/6", "ok")])
        self.assertEqual([g.title for g in m.groups], ["Счётчики трафика: exit-5", "Реклама YouTube — 12 локаций"])
        self.assertEqual(m.tiles[1].sub, "медленнее всех Великобритания 546 мс")
        self.assertEqual(m.tiles[2].sub, "12 видят FI")
        self.assertEqual(m.ages, ["3 д 12 ч", "9 ч 54 мин"])
        self.assertEqual(m.period, "10.11 07:00 — 11.11 07:00 UTC")
        self.assertEqual(m.badge, ("warn", "2 тревоги висят"))
        self.assertEqual(m.more, 0)

    def test_blips_line(self):
        m = build_models(demo_summary(), demo_state(NOW), NOW).dashboard
        self.assertEqual(m.blips_line, "Одиночных сбоев без тревоги: 14 · чаще всех: "
                                       "Великобритания 4, Великобритания · node-b 4, Нидерланды · node-b 4")
        m = build_models({}, {"checks": {}}, NOW).dashboard
        self.assertEqual(m.blips_line, "Одиночных сбоев без тревоги не было")

    def test_ratio_statuses_and_missing(self):
        s = demo_summary()
        s["locations"][("🇩🇪 Германия", "203.0.113.10:3442")]["status"] = 0.0
        s["yt"] = {k: "FI" for k in s["yt"]}
        del s["haproxy"]
        tiles = build_models(s, demo_state(NOW), NOW).dashboard.tiles
        self.assertEqual((tiles[0].value, tiles[0].status, tiles[0].sub), ("14/15", "bad", "Германия лежит"))
        self.assertEqual((tiles[2].value, tiles[2].status), ("0/14", "bad"))
        self.assertEqual((tiles[3].value, tiles[3].status), ("—", "none"))

    def test_haproxy_pool_down_bad(self):
        s = demo_summary()
        for b in ("be_smtp/exit-4", "be_smtp/exit-3", "be_smtp/exit-1"):
            s["haproxy"][b] = "DOWN"
        t = build_models(s, demo_state(NOW), NOW).dashboard.tiles[3]
        self.assertEqual((t.value, t.status, t.sub), ("3/6", "bad", "пул лежит: be_smtp"))

    def test_haproxy_backend_down_warn(self):
        s = demo_summary()
        s["haproxy"]["be_socks/exit-3"] = "DOWN 1/2"
        t = build_models(s, demo_state(NOW), NOW).dashboard.tiles[3]
        self.assertEqual((t.value, t.status, t.sub), ("5/6", "warn", "не UP: 1"))

    def test_groups_capped(self):
        checks = {"loc:L%d" % i: {"alerted": True, "alerted_at": NOW - i, "last_detail": str(i)} for i in range(8)}
        m = build_models({}, {"checks": checks}, NOW).dashboard
        self.assertEqual((len(m.groups), m.more, len(m.ages)), (5, 3, 5))
        self.assertEqual(m.badge, ("warn", "8 тревог висят"))

    def test_old_state_without_history_and_alerted_at(self):
        st = {"checks": {"yt:A": {"alerted": True}}}
        m = build_models({}, st, NOW)
        self.assertIsNone(m.dashboard.groups[0].since)
        self.assertEqual(m.dashboard.ages, [""])
        self.assertEqual(st, {"checks": {"yt:A": {"alerted": True}}})

    def test_no_alerts_badge(self):
        m = build_models(demo_summary(), {"checks": {}}, NOW).dashboard
        self.assertEqual(m.badge, ("ok", "всё в норме"))


class Matrix(unittest.TestCase):
    def test_matrix_rows(self):
        mx = build_models(demo_summary(), demo_state(NOW), NOW).matrix
        self.assertEqual(mx.columns, ["Основной вход", "node-b"])
        self.assertEqual(len(mx.rows), 9)
        de = next(r for r in mx.rows if r.name == "Германия")
        self.assertEqual((de.flag, de.cells, de.yt, de.latency),
                         ("🇩🇪", [("OK", "ok"), ("OK", "ok")], ("FI", "warn"), ("230 мс", "ok")))
        ru = next(r for r in mx.rows if r.name == "Россия")
        self.assertEqual(ru.cells, [("OK", "ok"), ("—", "none")])
        self.assertEqual((ru.yt, ru.latency), (("—", "none"), ("—", "none")))
        uk = next(r for r in mx.rows if r.name == "Великобритания")
        self.assertEqual(uk.latency, ("546 мс", "bad"))
        nl = next(r for r in mx.rows if r.name == "Нидерланды")
        self.assertEqual((nl.yt, nl.latency), (("RU/FI", "warn"), ("397 мс", "warn")))
        nla = next(r for r in mx.rows if r.name == "Нидерланды (с рекламой)")
        self.assertEqual(nla.yt, ("RU", "ok"))
        self.assertEqual(mx.badge, ("ok", "все входы работают"))
        self.assertFalse(any("Специальные" in r.name for r in mx.rows))

    def test_down_and_cut(self):
        s = demo_summary()
        s["locations"][("🔎 🇳🇱 Нидерланды · node-b", "203.0.113.10:3455")]["status"] = 0.0
        s["exits"][("🇸🇪 Швеция", "203.0.113.10:3459")]["status"] = 0.0
        st = demo_state(NOW)
        st["checks"]["exit:🇩🇪 Германия"]["alerted"] = True
        mx = build_models(s, st, NOW).matrix
        rows = {r.name: r for r in mx.rows}
        self.assertEqual(rows["Нидерланды"].cells[1], ("лежит", "bad"))
        self.assertEqual(rows["Швеция"].cells[0], ("режут", "warn"))
        self.assertEqual(rows["Германия"].cells[0], ("режут", "warn"))
        self.assertEqual(mx.badge, ("bad", "1 вход лежит"))
        self.assertEqual(mx.period, "состояние на 11.11 07:00 UTC")

    def test_empty(self):
        mx = build_models({}, {"checks": {}}, NOW).matrix
        self.assertEqual((mx.columns, mx.rows, mx.badge[0]), (["Основной вход"], [], "none"))


class Heatmap(unittest.TestCase):
    def test_heatmap_without_history_all_nodata(self):
        hm = build_models(demo_summary(), demo_state(NOW), NOW).heatmap
        self.assertTrue(all(c == "nodata" for r in hm.rows for c in r.cells))
        self.assertEqual(hm.hours[0], "07")
        self.assertEqual((hm.hours[-1], len(hm.hours)), ("06", 24))
        self.assertEqual(len(hm.rows), 15)
        self.assertEqual(hm.badge[0], "none")

    def test_heatmap_demo_history(self):
        hm = build_models(demo_summary(), with_history(demo_state(NOW)), NOW).heatmap
        cells = {c for r in hm.rows for c in r.cells}
        self.assertTrue({"clean", "one", "many", "alert", "nodata"} <= cells)
        self.assertEqual(hm.badge, ("warn", "3 строки с тревогой"))
        uk3 = next(r for r in hm.rows if r.name == "Великобритания · node-b")
        self.assertEqual((uk3.flag, len(uk3.cells)), ("🇬🇧", 24))
        self.assertEqual(hm.period, period_text(NOW))

    def test_demo_history_deterministic(self):
        a, b = with_history(demo_state(NOW)), with_history(demo_state(NOW))
        self.assertEqual(a, b)
        self.assertEqual(len(a["history"]["hours"]), 24)


class Speed(unittest.TestCase):
    def test_speed_sorted_and_alt(self):
        sp = build_models(demo_summary(), with_history(demo_state(NOW)), NOW).speed
        self.assertEqual(sp.alt_label, "node-b")
        self.assertEqual(len(sp.rows), 8)
        worst = [max(x for x in (r.main_ms, r.alt_ms) if x is not None) for r in sp.rows]
        self.assertEqual(worst, sorted(worst, reverse=True))
        self.assertEqual(sp.rows[0].name, "Великобритания")
        self.assertAlmostEqual(sp.rows[0].main_ms, 546, delta=30)
        self.assertAlmostEqual(sp.rows[0].alt_ms, 330, delta=30)
        auto = next(r for r in sp.rows if r.name == "AUTO Европа")
        self.assertIsNone(auto.alt_ms)
        self.assertEqual(sp.badge, ("ok", "все в норме"))

    def test_speed_partial_medians_sorted_last(self):
        st = with_history(demo_state(NOW))
        for h in st["history"]["hours"].values():
            for k in ("exit:🇩🇪 Германия", "exit:🔎 🇩🇪 Германия · node-b", "exit:🔎 🇬🇧 Великобритания · node-b"):
                h["lat"].pop(k, None)
        rows = build_models(demo_summary(), st, NOW).speed.rows
        self.assertEqual((rows[0].name, rows[0].main_ms, rows[0].alt_ms), ("Великобритания", 546.0, None))
        self.assertEqual((rows[-1].name, rows[-1].main_ms, rows[-1].alt_ms), ("Германия", None, None))
        worst = [max(x for x in (r.main_ms, r.alt_ms) if x is not None) for r in rows[:-1]]
        self.assertEqual(worst, sorted(worst, reverse=True))

    def test_speed_without_history(self):
        sp = build_models(demo_summary(), demo_state(NOW), NOW).speed
        self.assertEqual(len(sp.rows), 8)
        self.assertTrue(all(r.main_ms is None and r.alt_ms is None for r in sp.rows))
        self.assertEqual(sp.badge, ("none", "нет данных"))

    def test_speed_alerted_badge(self):
        st = with_history(demo_state(NOW))
        st["checks"]["exit:🇩🇪 Германия"]["alerted"] = True
        st["checks"]["exit:🔎 🇸🇪 Швеция · node-b"]["alerted"] = True
        self.assertEqual(build_models(demo_summary(), st, NOW).speed.badge, ("warn", "2 выхода в тревоге"))


class Misc(unittest.TestCase):
    def test_period_text(self):
        self.assertEqual(period_text(NOW), "10.11 07:00 — 11.11 07:00 UTC")

    def test_pure(self):
        s, st = demo_summary(), with_history(demo_state(NOW))
        s0, st0 = copy.deepcopy(s), copy.deepcopy(st)
        build_models(s, st, NOW)
        self.assertEqual((s, st), (s0, st0))

    def test_demo_fixture_counts(self):
        s, st = demo_summary(), demo_state(NOW)
        self.assertEqual(sum(st["blips"].values()), 14)
        self.assertEqual(len(s["yt"]), 14)
        self.assertEqual(sum(1 for k in st["checks"] if st["checks"][k].get("alerted")), 13)


if __name__ == "__main__":
    unittest.main()
