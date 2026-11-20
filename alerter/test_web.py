import os
import subprocess
import tempfile
import unittest
from unittest import mock

import alerter
from alerter import web_problem, web_url
from summary import format_events

CAB = {"label": "Кабинет из РФ (ctl-host → front-1)", "url": "https://cabinet.example.net/",
       "contains": "<title>ZanityVPN</title>"}
HOOK = {"label": "Бот: путь Telegram → реле → бот (через socks бота)", "webhook_from_env": "WEBHOOK_URL",
        "path": "/health/telegram-webhook", "proxy": True, "contains": '"status":"ok"'}


def env_file(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
    f.write(text)
    f.close()
    return f.name


class Problem(unittest.TestCase):
    def test_ok(self):
        self.assertIsNone(web_problem(0, 200, "<title>ZanityVPN</title>", CAB))

    def test_curl_errors(self):
        self.assertIn("не ответил", web_problem(28, 0, "", CAB))
        self.assertIn("отклонено", web_problem(7, 0, "", CAB))
        self.assertIn("кодом 99", web_problem(99, 0, "", CAB))

    def test_status_and_marker(self):
        self.assertIn("502 вместо 200", web_problem(0, 502, "", CAB))
        self.assertIn("нет «<title>ZanityVPN</title>»", web_problem(0, 200, "<title>Caddy</title>", CAB))


class Url(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(web_url(CAB, {}), "https://cabinet.example.net/")

    def test_webhook_base_from_env(self):
        path = env_file("BOT_TOKEN=x\nWEBHOOK_URL=https://exit-4.example.net:88  # реле\nWEBHOOK_PATH=/webhook\n")
        try:
            self.assertEqual(web_url(HOOK, {"bot_env": path}), "https://exit-4.example.net:88/health/telegram-webhook")
        finally:
            os.unlink(path)

    def test_webhook_missing(self):
        path = env_file("BOT_TOKEN=x\n")
        try:
            self.assertIsNone(web_url(HOOK, {"bot_env": path}))
        finally:
            os.unlink(path)


class Cycle(unittest.TestCase):
    def setUp(self):
        self.env = env_file("BOT_TOKEN=t\nPROXY_URL=socks5://u:p@172.17.0.1:1080\n"
                            "WEBHOOK_URL=https://exit-4.example.net:88\n")
        self.cfg = {"bot_env": self.env, "failures_before_alert": 3,
                    "web_checks": {"failures_before_alert": 3, "checks": [CAB, HOOK]}}
        self.state = {"checks": {}}
        self.calls = []
        self.replies = {}

    def tearDown(self):
        os.unlink(self.env)

    def fake_run(self, cmd, **kw):
        self.calls.append(cmd)
        exit_code, code, body = self.replies[cmd[-1]]
        return subprocess.CompletedProcess(cmd, exit_code, ("%s\n%s" % (body, code)).encode(), b"")

    def cycle(self):
        events = []
        with mock.patch.object(alerter.subprocess, "run", self.fake_run), \
                mock.patch.object(alerter, "log", lambda m: None):
            alerter.web_cycle(self.cfg, self.state, events, {})
        return events

    def test_proxy_only_for_webhook_and_alert_after_three(self):
        hook_url = "https://exit-4.example.net:88/health/telegram-webhook"
        self.replies = {CAB["url"]: (0, 200, "<title>ZanityVPN</title>"), hook_url: (0, 502, "")}
        for _ in range(2):
            self.assertEqual(self.cycle(), [])
        events = self.cycle()
        self.assertEqual(events, [("down", "web:" + HOOK["label"], "ответил 502 вместо 200")])
        cab_cmd, hook_cmd = self.calls[-2:]
        self.assertNotIn("--proxy", cab_cmd)
        self.assertIn("socks5h://u:p@172.17.0.1:1080", hook_cmd)
        text = format_events(events)
        self.assertIn("Бот: путь Telegram → реле → бот (через socks бота) — ответил 502 вместо 200", text)

        self.replies[hook_url] = (0, 200, '{"status":"ok","mode":"webhook"}')
        events = self.cycle()
        self.assertEqual(events, [("up", "web:" + HOOK["label"], "открывается")])

    def test_poll_seconds_throttles(self):
        self.cfg["web_checks"]["poll_seconds"] = 600
        self.replies = {CAB["url"]: (28, 0, ""), "https://exit-4.example.net:88/health/telegram-webhook": (28, 0, "")}
        self.cycle()
        self.cycle()
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
