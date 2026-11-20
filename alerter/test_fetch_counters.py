import subprocess
import unittest
from unittest.mock import patch

import alerter

CFG = {"quota_key": "/k"}
NODE = {"name": "exit-5", "host": "198.51.100.30", "port": 22}
OK = subprocess.CompletedProcess([], 0, "host x\nuptime 100\nens3 rx 1 tx 2\n", "")
RESET = subprocess.CompletedProcess([], 255, "", "Connection closed by 198.51.100.30 port 22\n")


class FetchCountersTest(unittest.TestCase):
    def run_with(self, results):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return results[len(calls) - 1]

        with patch.object(alerter.subprocess, "run", fake_run), patch.object(alerter.time, "sleep") as sl:
            return alerter.fetch_counters(NODE, CFG), calls, sl

    def test_first_ok_single_call(self):
        data, calls, sl = self.run_with([OK])
        self.assertEqual(data, {"ifaces": {"ens3": [1, 2]}, "uptime": 100})
        self.assertEqual(len(calls), 1)
        sl.assert_not_called()

    def test_retry_after_reset(self):
        # анти-DDoS хостера (EXIT-5, 11-20) сбрасывает первое соединение с «нового» адреса, повтор проходит
        data, calls, sl = self.run_with([RESET, OK])
        self.assertEqual(data["ifaces"], {"ens3": [1, 2]})
        self.assertEqual(len(calls), 2)
        sl.assert_called_once()

    def test_gives_up_after_two_failures(self):
        data, calls, _ = self.run_with([RESET, RESET])
        self.assertIsNone(data)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
