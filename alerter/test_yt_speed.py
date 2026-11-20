import unittest
from alerter import YT_PLAYER_RE, yt_speed_log_line, yt_speed_problem, yt_speed_targets

MB = 1048576
SKIP = {"node-c.example.net:3446", "node-d.example.net:3443"}

class Targets(unittest.TestCase):
    def test_only_russian_without_headers(self):
        locs = {
            ("🇷🇺 #1 Россия (СПБ)", "node-c.example.net:3446"): {},
            ("👇 🎮 Для игр (без обхода) 👇", "node-c.example.net:3446"): {},
            ("🇷🇺 #2 Россия (МСК)", "node-d.example.net:3443"): {},
            ("🇩🇪 Германия", "node-e.example.net:3442"): {},
        }
        self.assertEqual(yt_speed_targets(locs, SKIP), ["🇷🇺 #1 Россия (СПБ)", "🇷🇺 #2 Россия (МСК)"])

    def test_no_youtube_addresses_skipped(self):
        locs = {("🇷🇺 #3 Россия (МСК)", "203.0.113.10:3444"): {}, ("🇷🇺 #2 Россия (МСК)", "node-d.example.net:3443"): {}}
        skip = SKIP | {"203.0.113.10:3444"}
        self.assertEqual(yt_speed_targets(locs, skip, {"203.0.113.10:3444"}), ["🇷🇺 #2 Россия (МСК)"])

class Problem(unittest.TestCase):
    def test_ok(self):
        self.assertIsNone(yt_speed_problem("206", MB, MB))
        self.assertIsNone(yt_speed_problem("200", 3 * MB, MB))
    def test_no_connection(self):
        self.assertIn("не открылся", yt_speed_problem("000", 0, MB))
        self.assertIn("не открылся", yt_speed_problem("", 0, MB))
    def test_bad_status(self):
        self.assertIn("403", yt_speed_problem("403", 500, MB))
    def test_throttled(self):
        self.assertIn("режут полосу", yt_speed_problem("206", 300 * 1024, MB))

class PlayerPath(unittest.TestCase):
    def test_finds_base_js(self):
        page = 'x"jsUrl":"/s/player/6b2fce74/player_ias.vflset/en_US/base.js","y'
        self.assertEqual(YT_PLAYER_RE.search(page).group(0), "/s/player/6b2fce74/player_ias.vflset/en_US/base.js")

class LogLine(unittest.TestCase):
    def test_no_targets_is_not_a_failure(self):
        self.assertEqual(yt_speed_log_line([], {}), "yt_speed: нет российских локаций с YouTube — проверять нечего")
    def test_targets_without_success(self):
        self.assertEqual(yt_speed_log_line(["🇷🇺 #2 Россия (МСК)"], {}), "yt_speed: нет удачных замеров")
    def test_speeds(self):
        self.assertEqual(yt_speed_log_line(["a", "b"], {"a": 40, "b": 12}), "yt_speed: a=40, b=12")

if __name__ == "__main__":
    unittest.main()
