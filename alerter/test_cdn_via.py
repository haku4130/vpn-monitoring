import subprocess
import unittest
from unittest import mock

import alerter
from alerter import cdn_via_cmd, cdn_via_cycle, cdn_via_targets, parse_cdn_via
from summary import format_events, pretty

PORTS = [(10001, "🇳🇱 Нидерланды"), (10007, "🇷🇺 Россия"), (10016, "🇩🇪 Германия (личный)")]
DOMAINS = ["sub.example.org", "sub-cdn.example.com"]
CC = {"path": "/SU", "checks": [{"domain": d} for d in DOMAINS], "failures_before_alert": 2,
      "via_locations": ["🇷🇺 Россия", "🇳🇱 Нидерланды", "🇬🇧 Великобритания"]}
CFG = {"sources": {"ip": {"container": "checker"}}, "failures_before_alert": 3}
XRAY = '{"inbounds": [%s]}' % ", ".join(
    '{"port": %d, "tag": "%s_vless_%d_Inbound"}' % (p, n, i) for i, (p, n) in enumerate(PORTS))


def fake_run(curl_out):
    def run(cmd, **kw):
        out = XRAY if cmd[-1] == "/app/xray_config.json" else curl_out
        return subprocess.CompletedProcess(cmd, 0, out, "")
    return run


class Pure(unittest.TestCase):
    def test_targets_in_config_order_and_skip_missing(self):
        self.assertEqual(cdn_via_targets(PORTS, CC["via_locations"]), [(10007, "🇷🇺 Россия"), (10001, "🇳🇱 Нидерланды")])

    def test_cmd_runs_all_in_parallel(self):
        cmd = cdn_via_cmd([(10007, "x"), (10001, "y")], DOMAINS, "/SU", 15)
        self.assertEqual(cmd.count("curl "), 4)
        self.assertEqual(cmd.count(") &"), 4)
        self.assertTrue(cmd.endswith(" wait"))
        self.assertIn("-x socks5h://127.0.0.1:10007 https://sub-cdn.example.com/SU", cmd)
        self.assertIn("-m 15 ", cmd)

    def test_cmd_output_parses(self):
        # сам шелл-сниппет: echo печатает «порт домен код»
        out = subprocess.run(["sh", "-c", cdn_via_cmd([(1, "x")], DOMAINS, "/SU", 1).replace(
            "curl -s", "true -s").replace("$(true", "$(echo 200; true")], capture_output=True, text=True).stdout
        self.assertEqual(parse_cdn_via(out), {(1, "sub.example.org"): 200, (1, "sub-cdn.example.com"): 200})

    def test_parse(self):
        self.assertEqual(parse_cdn_via("10007 sub.example.org 200\n10001 sub.example.org 000\njunk\n10001 x\n"),
                         {(10007, "sub.example.org"): 200, (10001, "sub.example.org"): 0})

    def test_pretty_and_glue(self):
        self.assertEqual(pretty("cdn_via:🇳🇱 Нидерланды · sub.example.org"), "Подписка sub.example.org через «🇳🇱 Нидерланды»")
        self.assertEqual(pretty("cdn:sub.example.org"), "Подписка sub.example.org")
        bad = "эдж CDN не отдаёт подписку"
        text = format_events([("down", "cdn_via:🇳🇱 Нидерланды · sub.example.org", bad),
                              ("down", "cdn_via:🇬🇧 Великобритания · sub.example.org", bad)])
        self.assertIn("Подписка через локации — 2 пути", text)


class Cycle(unittest.TestCase):
    def run_cycle(self, out, state=None, now=10_000):
        state = state or {"checks": {}}
        events = []
        with mock.patch.object(alerter.subprocess, "run", side_effect=fake_run(out)), \
                mock.patch.object(alerter, "log"):
            cdn_via_cycle(CFG, CC, state, events, now)
        return state, events

    def test_alert_after_two_failures_only_for_failing_exit(self):
        out = ("10007 sub.example.org 200\n10007 sub-cdn.example.com 200\n"
               "10001 sub.example.org 000\n10001 sub-cdn.example.com 200\n")
        st, ev = self.run_cycle(out)
        self.assertEqual(ev, [])
        st, ev = self.run_cycle(out, st, now=20_000)
        self.assertEqual([(k, key) for k, key, _ in ev], [("down", "cdn_via:🇳🇱 Нидерланды · sub.example.org")])
        self.assertFalse(st["checks"]["cdn_via:🇷🇺 Россия · sub.example.org"]["alerted"])

    def test_respects_poll_interval(self):
        st, _ = self.run_cycle("10007 sub.example.org 200\n")
        st2, _ = self.run_cycle("", st, now=10_100)
        self.assertEqual(st2["cdn_via_last_poll"], 10_000)

    def test_empty_output_is_not_a_failure(self):
        st, ev = self.run_cycle("")
        st, ev = self.run_cycle("", st, now=20_000)
        self.assertEqual(ev, [])
        self.assertFalse([k for k in st["checks"] if k.startswith("cdn_via:")])

    def test_removed_location_alert_is_dropped(self):
        st = {"checks": {"cdn_via:🇫🇮 #1 Финляндия · sub.example.org": {"fails": 5, "alerted": True}}}
        st, _ = self.run_cycle("10007 sub.example.org 200\n", st)
        self.assertNotIn("cdn_via:🇫🇮 #1 Финляндия · sub.example.org", st["checks"])

    def test_disabled_without_via_locations(self):
        state, events = {"checks": {}}, []
        with mock.patch.object(alerter.subprocess, "run") as run:
            cdn_via_cycle(CFG, {**CC, "via_locations": []}, state, events, 10_000)
            cdn_via_cycle(CFG, {}, state, events, 10_000)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
