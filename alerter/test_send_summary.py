import json
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

import alerter
from alerter import album_cmd, send_album, send_summary
from datetime import datetime, timezone

from demo_data import demo_summary, demo_state

NOW = datetime(2026, 11, 11, 7, 0, 30, tzinfo=timezone.utc).timestamp()

CFG = {"bot_env": "/nonexistent.env"}


class AlbumCmdTest(unittest.TestCase):
    def test_album_cmd_shape(self):
        cmd = album_cmd("T", "-100", "socks5h://p:1", "7", "cap", ["/x/0.png", "/x/1.png"])
        media = json.loads(next(a for a in cmd if a.startswith("media="))[6:])
        self.assertEqual(media[0]["caption"], "cap")
        self.assertEqual(media[0]["parse_mode"], "HTML")
        self.assertEqual(media[1], {"type": "photo", "media": "attach://c1"})
        self.assertIn("c0=@/x/0.png", cmd)
        self.assertIn("message_thread_id=7", cmd)
        self.assertIn("chat_id=-100", cmd)
        self.assertIn("https://api.telegram.org/botT/sendMediaGroup", cmd)
        self.assertEqual(cmd[cmd.index("--proxy") + 1], "socks5h://p:1")

    def test_text_fields_are_form_strings(self):
        cmd = album_cmd("T", "@chan", None, None, "<b>x</b>", ["/x/0.png"])
        self.assertNotIn("--proxy", cmd)
        self.assertFalse(any(a.startswith("message_thread_id") for a in cmd))
        i = cmd.index("chat_id=@chan")
        self.assertEqual(cmd[i - 1], "--form-string")
        i = next(i for i, a in enumerate(cmd) if a.startswith("media="))
        self.assertEqual(cmd[i - 1], "--form-string")
        self.assertEqual(cmd[cmd.index("c0=@/x/0.png") - 1], "-F")


class SendAlbumTest(unittest.TestCase):
    def run_album(self, stdout):
        with patch.object(alerter, "tg_target", return_value=("T", "1", None, None)), \
                patch.object(alerter.subprocess, "run", return_value=MagicMock(stdout=stdout)) as run:
            return send_album(CFG, [b"a", b"b"], "cap"), run

    def test_ok(self):
        ok, run = self.run_album("200\n")
        self.assertTrue(ok)
        self.assertEqual(run.call_args[1]["timeout"], 90)

    def test_rejected(self):
        ok, _ = self.run_album("400")
        self.assertFalse(ok)

    def test_no_token(self):
        with patch.object(alerter, "tg_target", return_value=(None, None, None, None)), \
                patch.object(alerter.subprocess, "run") as run:
            self.assertFalse(send_album(CFG, [b"a"], "cap"))
        run.assert_not_called()


class SendSummaryTest(unittest.TestCase):
    def go(self, render, album=True, tg=True, caption=None):
        summary, state = demo_summary(), demo_state(NOW)
        with patch.object(alerter, "send_telegram", return_value=tg) as st, \
                patch.object(alerter, "send_album", return_value=album) as sa:
            if caption is not None:
                with patch.object(alerter, "compose_caption", return_value=caption):
                    res = send_summary(CFG, summary, state, NOW, render=render)
            else:
                res = send_summary(CFG, summary, state, NOW, render=render)
        return res, st, sa

    def test_render_failure_falls_back_to_text(self):
        def boom(_):
            raise ImportError("PIL")
        res, st, sa = self.go(boom)
        self.assertTrue(res)
        sa.assert_not_called()
        self.assertIn("Мониторинг · сутки", st.call_args[0][1])

    def test_album_rejected_falls_back(self):
        res, st, sa = self.go(lambda m: [b"x"] * 4, album=False)
        self.assertTrue(res)
        sa.assert_called_once()
        self.assertIn("Мониторинг · сутки", st.call_args[0][1])

    def test_album_ok_no_text(self):
        res, st, sa = self.go(lambda m: [b"x"] * 4, caption=("cap", None))
        self.assertTrue(res)
        st.assert_not_called()
        self.assertEqual(sa.call_args[0][1], [b"x"] * 4)
        self.assertEqual(sa.call_args[0][2], "cap")

    def test_extra_message_after_album(self):
        order = []
        summary, state = demo_summary(), demo_state(NOW)
        with patch.object(alerter, "compose_caption", return_value=("head", "<b>Подробности</b>\nx")), \
                patch.object(alerter, "send_album", side_effect=lambda *a, **k: order.append("album") or True) as sa, \
                patch.object(alerter, "send_telegram", side_effect=lambda *a, **k: order.append("text") or True) as st:
            self.assertTrue(send_summary(CFG, summary, state, NOW, render=lambda m: [b"x"]))
        self.assertEqual(order, ["album", "text"])
        self.assertEqual(sa.call_args[0][2], "head")
        self.assertTrue(st.call_args[0][1].startswith("<b>Подробности</b>"))

    def test_extra_failure_still_true(self):
        res, st, sa = self.go(lambda m: [b"x"], tg=False, caption=("head", "extra"))
        self.assertTrue(res)
        self.assertEqual(st.call_count, 1)
        self.assertEqual(st.call_args[0][1], "extra")

    def test_nothing_sent_returns_false(self):
        res, st, sa = self.go(lambda m: [b"x"], album=False, tg=False)
        self.assertFalse(res)

    def test_chat_and_thread_passed(self):
        summary, state = demo_summary(), demo_state(NOW)
        with patch.object(alerter, "send_album", return_value=False) as sa, \
                patch.object(alerter, "send_telegram", return_value=True) as st:
            send_summary(CFG, summary, state, NOW, chat="@c", thread=False, render=lambda m: [b"x"])
        self.assertEqual(sa.call_args[1], {"chat": "@c", "thread": False})
        self.assertEqual(st.call_args[1], {"chat": "@c", "thread": False})

    def test_caption_failure_sends_minimal_text(self):
        summary, state = demo_summary(), demo_state(NOW)
        with patch.object(alerter, "caption_parts", side_effect=ValueError("<x>")), \
                patch.object(alerter, "send_album") as sa, \
                patch.object(alerter, "send_telegram", return_value=True) as st:
            self.assertTrue(send_summary(CFG, summary, state, NOW, chat="@c", thread=False))
        sa.assert_not_called()
        self.assertIn("Сводку собрать не удалось", st.call_args[0][1])
        self.assertIn("&lt;x&gt;", st.call_args[0][1])
        self.assertEqual(st.call_args[1], {"chat": "@c", "thread": False})

    def test_build_models_failure_falls_back_to_text(self):
        summary, state = demo_summary(), demo_state(NOW)
        with patch.object(alerter, "build_models", side_effect=ValueError("x")), \
                patch.object(alerter, "send_album") as sa, \
                patch.object(alerter, "send_telegram", return_value=True) as st:
            self.assertTrue(send_summary(CFG, summary, state, NOW))
        sa.assert_not_called()
        self.assertIn("Мониторинг · сутки", st.call_args[0][1])

    def test_default_render_without_cards_falls_back(self):
        summary, state = demo_summary(), demo_state(NOW)
        with patch.dict(sys.modules, {"cards": None}), \
                patch.object(alerter, "send_album") as sa, \
                patch.object(alerter, "send_telegram", return_value=True) as st:
            self.assertTrue(send_summary(CFG, summary, state, NOW))
        sa.assert_not_called()
        self.assertIn("Мониторинг · сутки", st.call_args[0][1])


class TokenLeakTest(unittest.TestCase):
    def test_timeout_not_logged_with_token(self):
        exc = subprocess.TimeoutExpired(["curl", "https://api.telegram.org/botSECRET/sendMessage"], 40)
        for fn in (lambda: alerter.send_telegram(CFG, "t"),
                   lambda: send_album(CFG, [b"x"], "c")):
            with patch.object(alerter, "tg_target", return_value=("SECRET", "1", None, None)), \
                    patch.object(alerter.subprocess, "run", side_effect=exc), \
                    patch.object(alerter, "log") as lg:
                self.assertFalse(fn())
            self.assertTrue(lg.called)
            self.assertNotIn("SECRET", " ".join(str(c) for c in lg.call_args_list))


class HeartbeatStepTest(unittest.TestCase):
    CFG = {"heartbeat_hour_utc": 7}

    def step(self, sent, state):
        with patch.object(alerter, "send_summary", side_effect=sent) as ss:
            alerter.heartbeat_step(self.CFG, state, {}, NOW)
        return ss

    def test_success_marks_and_resets(self):
        state = {"blips": {"k": 1}}
        self.step(lambda *a: True, state)
        self.assertEqual(state["last_heartbeat"], "2026-11-11")
        self.assertEqual(state["blips"], {})

    def test_failure_keeps_state(self):
        state = {"blips": {"k": 1}, "last_heartbeat": "2026-11-10"}
        self.step(lambda *a: False, state)
        self.assertEqual(state, {"blips": {"k": 1}, "last_heartbeat": "2026-11-10"})

    def test_exception_keeps_state(self):
        state = {"blips": {"k": 1}}
        self.step(RuntimeError("boom"), state)
        self.assertEqual(state, {"blips": {"k": 1}})

    def test_not_in_hour_or_already_sent(self):
        state = {"last_heartbeat": "2026-11-11"}
        self.assertFalse(self.step(lambda *a: True, state).called)
        with patch.object(alerter, "send_summary") as ss:
            alerter.heartbeat_step({"heartbeat_hour_utc": 8}, {}, {}, NOW)
        ss.assert_not_called()


if __name__ == "__main__":
    unittest.main()
