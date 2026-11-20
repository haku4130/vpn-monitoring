import unittest
from unittest.mock import patch

import alerter
from alerter import run_cycle
from history import hour_key

CFG = {
    "sources": {
        "ip": {"name": "ip", "interval_seconds": 300},
        "exit": {"name": "exit", "interval_seconds": 300},
    },
    "exit_check_skip_addresses": [],
}


T0 = 1_800_000_000.0


def new_state():
    return {"checks": {}}


class CycleHistoryTest(unittest.TestCase):
    def setUp(self):
        self.now = T0
        p = patch.object(alerter.time, "time", lambda: self.now)
        p.start()
        self.addCleanup(p.stop)

    def cycle(self, state, ip=None, exit=None, cfg=CFG):
        def fake_scrape(source):
            return ip if source["name"] == "ip" else exit

        with patch.object(alerter, "scrape", fake_scrape), \
                patch.object(alerter, "checker_errors", return_value={}), \
                patch.object(alerter, "haproxy_backends", return_value=None), \
                patch.object(alerter, "quota_cycle"), \
                patch.object(alerter, "yt_region_cycle"), \
                patch.object(alerter, "yt_speed_cycle"), \
                patch.object(alerter, "mask_cycle"):
            return run_cycle(cfg, state)

    def bucket(self, state):
        return state["history"]["hours"][hour_key(T0)]

    def test_fail_and_touch_recorded(self):
        state = new_state()
        self.cycle(state, ip={("A", "a:1"): {"status": 0}, ("B", "b:1"): {"status": 1}})
        rows = self.bucket(state)["rows"]
        self.assertEqual(rows["loc:A"][0], 1)
        self.assertEqual(rows["loc:B"], [0, 0])

    def test_same_sample_not_recounted(self):
        state = new_state()
        ip = {("A", "a:1"): {"status": 0}, ("B", "b:1"): {"status": 1}}
        self.cycle(state, ip=ip)
        self.cycle(state, ip=ip)
        self.assertEqual(self.bucket(state)["rows"]["loc:A"][0], 1)

    def test_latency_only_new_successful_sample(self):
        state = new_state()
        ip = {("A", "a:1"): {"status": 1}}
        for ms in (480, 480, 500):
            self.cycle(state, ip=ip, exit={("A", "a:1"): {"status": 1, "latency": ms}})
        self.assertEqual(self.bucket(state)["lat"]["exit:A"], [480, 500])

    def test_failed_exit_sample_has_no_latency(self):
        state = new_state()
        self.cycle(state, ip={("A", "a:1"): {"status": 1}},
                   exit={("A", "a:1"): {"status": 0, "latency": 0}})
        self.assertNotIn("exit:A", self.bucket(state)["lat"])
        self.assertEqual(self.bucket(state)["rows"]["exit:A"][0], 1)

    def test_mass_outage_counts_and_paints(self):
        state = new_state()
        for ms in (1, 2, 3):
            ip = {(n, n + ":1"): {"status": 0, "latency": ms} for n in "ABCD"}
            self.cycle(state, ip=ip)
        self.assertTrue(state["checks"]["mass_outage"]["alerted"])
        self.assertEqual(self.bucket(state)["rows"]["loc:A"], [3, 1])

    def test_mass_outage_same_sample_not_recounted(self):
        state = new_state()
        ip = {(n, n + ":1"): {"status": 0, "latency": 0} for n in "ABCD"}
        self.cycle(state, ip=ip)
        self.cycle(state, ip=ip)
        self.assertEqual(self.bucket(state)["rows"]["loc:A"][0], 1)
        self.assertEqual(state["checks"]["loc:A"]["fails"], 2)

    def test_mass_outage_divider_not_recorded(self):
        state = new_state()
        ip = {(n, n + ":1"): {"status": 0} for n in ("A", "B", "C")}
        ip[("👇 Россия", "d:1")] = {"status": 0}
        self.cycle(state, ip=ip)
        self.assertEqual(sorted(self.bucket(state)["rows"]), ["loc:A", "loc:B", "loc:C"])

    def test_down_alert_not_delayed_after_mass_outage(self):
        state = new_state()
        for ms in (1, 2, 3):
            ip = {(n, n + ":1"): {"status": 0, "latency": ms} for n in "ABCD"}
            self.cycle(state, ip=ip)
            self.now += 120
        ip = {(n, n + ":1"): {"status": 1, "latency": 5} for n in "BCD"}
        ip[("A", "a:1")] = {"status": 0, "latency": 3}
        events, _ = self.cycle(state, ip=ip)
        self.assertIn("loc:A", [e[1] for e in events if e[0] == "down"])

    def test_summary_exits_exclude_skipped_addresses(self):
        cfg = dict(CFG, exit_check_skip_addresses=["ru:1"])
        _, summary = self.cycle(new_state(), ip={("A", "a:1"): {"status": 1}},
                                exit={("A", "a:1"): {"status": 1, "latency": 5},
                                      ("RU", "ru:1"): {"status": 0}}, cfg=cfg)
        self.assertEqual(list(summary["exits"]), [("A", "a:1")])

    def test_divider_not_recorded(self):
        state = new_state()
        div = "👇 Россия"
        self.cycle(state, ip={(div, "d:1"): {"status": 0}, ("B", "b:1"): {"status": 1}},
                   exit={(div, "d:1"): {"status": 1, "latency": 10}})
        b = self.bucket(state)
        self.assertEqual(list(b["rows"]), ["loc:B"])
        self.assertEqual(b["lat"], {})


class IsNewSampleTest(unittest.TestCase):
    def test_rules(self):
        src, cfg = {"interval_seconds": 300}, {"interval_seconds": 120}
        st = {"sample": [0, 0], "counted_at": 1000}
        self.assertFalse(alerter.is_new_sample(st, [0, 0], src, cfg, 1100))
        self.assertTrue(alerter.is_new_sample(st, [0, 1], src, cfg, 1100))
        self.assertTrue(alerter.is_new_sample(st, [0, 0], src, cfg, 1360))
        self.assertFalse(alerter.is_new_sample(st, [0, 0], src, cfg, 1359))


if __name__ == "__main__":
    unittest.main()
