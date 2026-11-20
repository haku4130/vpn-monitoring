import os
import tempfile
import unittest
from unittest.mock import patch

import alerter


class CliTest(unittest.TestCase):
    def test_render_demo_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "sub")
            self.assertEqual(alerter.main(["--render", out, "--demo", "--demo-history"]), 0)
            self.assertEqual(sorted(os.listdir(out)),
                             ["1_dashboard.png", "2_matrix.png", "3_heatmap.png", "4_speed.png", "caption.html"])
            with open(os.path.join(out, "caption.html"), encoding="utf-8") as f:
                self.assertIn("<i>демо: данные и история из фикстуры</i>", f.read())

    def test_cli_does_not_save_state(self):
        with tempfile.TemporaryDirectory() as d, patch.object(alerter, "save_state") as ss:
            self.assertEqual(alerter.main(["--render", d, "--demo"]), 0)
            ss.assert_not_called()

    def test_test_summary_no_thread(self):
        with patch.object(alerter, "load_json", return_value={"c": 1}), \
                patch.object(alerter, "send_summary", return_value=True) as s:
            self.assertEqual(alerter.main(["--test-summary", "123", "--demo", "--demo-history"]), 0)
        self.assertEqual(s.call_args.kwargs["chat"], "123")
        self.assertIs(s.call_args.kwargs["thread"], False)
        self.assertEqual(s.call_args.kwargs["demo"], (True, True))

    def test_test_summary_failure_exit_code(self):
        with patch.object(alerter, "load_json", return_value={"c": 1}), \
                patch.object(alerter, "send_summary", return_value=False):
            self.assertEqual(alerter.main(["--test-summary", "123", "--demo"]), 1)

    def test_test_summary_demo_needs_config(self):
        with patch.object(alerter, "load_json", return_value=None), patch.object(alerter, "send_summary") as s:
            self.assertEqual(alerter.main(["--test-summary", "123", "--demo"]), 1)
            s.assert_not_called()

    def test_modes_exclusive(self):
        with self.assertRaises(SystemExit):
            alerter.main(["--render", "/x", "--test-summary", "1"])

    def test_no_config_without_demo(self):
        with patch.object(alerter, "load_json", return_value=None), patch.object(alerter, "run_cycle") as rc:
            self.assertEqual(alerter.main(["--test-summary", "1"]), 1)
            rc.assert_not_called()

    def test_real_state_is_copied_not_mutated(self):
        state = {"checks": {}, "last_heartbeat": None, "history": {"x": 1}}
        def fake_load(path, default):
            return {"c": 1} if path == alerter.CONFIG_PATH else state
        with tempfile.TemporaryDirectory() as d, patch.object(alerter, "load_json", side_effect=fake_load), \
                patch.object(alerter, "run_cycle", side_effect=lambda c, s: ([], __import__("demo_data").demo_summary())), \
                patch.object(alerter, "save_state") as ss:
            self.assertEqual(alerter.main(["--render", d, "--demo-history"]), 0)
            ss.assert_not_called()
        self.assertEqual(state["history"], {"x": 1})


class CliSafetyTest(unittest.TestCase):
    def test_empty_values_do_not_start_loop(self):
        for argv in (["--test-summary", ""], ["--render", ""], ["--test-summary", "  "]):
            with patch.object(alerter, "run_cycle") as rc, patch.object(alerter, "save_state") as ss, \
                    patch.object(alerter.time, "sleep") as sl:
                with self.assertRaises(SystemExit) as cm:
                    alerter.main(argv)
                self.assertNotEqual(cm.exception.code, 0)
                rc.assert_not_called()
                ss.assert_not_called()
                sl.assert_not_called()

    def test_demo_flags_alone_rejected(self):
        with patch.object(alerter, "run_cycle") as rc:
            with self.assertRaises(SystemExit):
                alerter.main(["--demo"])
            rc.assert_not_called()

    def test_marks(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(alerter.main(["--render", d, "--demo"]), 0)
            with open(os.path.join(d, "caption.html"), encoding="utf-8") as f:
                cap = f.read()
            self.assertIn("<i>демо: данные из фикстуры</i>", cap)
            self.assertNotIn("история", cap)
            self.assertEqual(alerter.mark_demo("a\nb"), "a\nb")
            self.assertEqual(alerter.mark_demo("a\nb", False, True), "a\n<i>демо: история из фикстуры</i>\nb")

    def test_demo_history_fills_state(self):
        captured = {}
        orig = alerter.build_models
        def spy(summary, state, now):
            captured["h"] = state.get("history")
            return orig(summary, state, now)
        with tempfile.TemporaryDirectory() as d, patch.object(alerter, "build_models", side_effect=spy):
            self.assertEqual(alerter.main(["--render", d, "--demo", "--demo-history"]), 0)
        self.assertTrue(captured["h"])

    def test_render_failure_returns_1(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(alerter, "_render_cards", side_effect=ImportError("PIL")):
                self.assertEqual(alerter.main(["--render", d, "--demo"]), 1)
            with patch.object(alerter, "_render_cards", return_value=[b"x"] * 3):
                self.assertEqual(alerter.main(["--render", d, "--demo"]), 1)
            self.assertEqual(os.listdir(d), [])

    def test_real_state_untouched_and_no_events_sent(self):
        import json
        demo = __import__("demo_data")
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "state.json")
            with open(sp, "w") as f:
                json.dump({"checks": {}, "last_heartbeat": None, "history": {"x": 1}}, f)
            os.utime(sp, (1000, 1000))
            before = open(sp).read()
            with patch.object(alerter, "STATE_PATH", sp), \
                    patch.object(alerter, "load_json", wraps=alerter.load_json) as lj, \
                    patch.object(alerter, "CONFIG_PATH", os.path.join(d, "cfg.json")):
                with open(alerter.CONFIG_PATH, "w") as f:
                    json.dump({"c": 1}, f)
                with patch.object(alerter, "run_cycle", return_value=([("down", "k", "x")], demo.demo_summary())), \
                        patch.object(alerter, "send_telegram") as st, patch.object(alerter, "save_state") as ss:
                    self.assertEqual(alerter.main(["--render", os.path.join(d, "out"), "--demo-history"]), 0)
                    st.assert_not_called()
                    ss.assert_not_called()
            self.assertEqual(open(sp).read(), before)
            self.assertEqual(os.stat(sp).st_mtime, 1000)

    def test_test_summary_demo_reaches_curl_without_thread(self):
        import json
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as d:
            env = os.path.join(d, ".env")
            with open(env, "w") as f:
                f.write("BOT_TOKEN=TOK\nADMIN_NOTIFICATIONS_CHAT_ID=-999\n")
            cfg = {"bot_env": env, "message_thread_id": 77}
            with patch.object(alerter, "load_json", return_value=cfg), \
                    patch.object(alerter.subprocess, "run", return_value=MagicMock(stdout="200")) as run:
                self.assertEqual(alerter.main(["--test-summary", "555", "--demo"]), 0)
            cmd = run.call_args_list[0].args[0]
            self.assertIn("chat_id=555", cmd)
            self.assertFalse(any("message_thread_id" in a for a in cmd))
            self.assertTrue(any(a.endswith("/sendMediaGroup") for a in cmd))
            media = next(a for a in cmd if a.startswith("media="))
            self.assertIn("демо: данные из фикстуры", media)


if __name__ == "__main__":
    unittest.main()
