import unittest
from summary import split_entry, flag_of, display_name, is_divider, plural, key_prefix, key_name, strip_emoji


class Names(unittest.TestCase):
    def test_split_entry(self):
        self.assertEqual(split_entry("🔎 🇩🇪 Германия · node-b"), ("🇩🇪 Германия", "node-b"))
        self.assertEqual(split_entry("🇩🇪 Германия"), ("🇩🇪 Германия", None))
        self.assertEqual(split_entry("🔎 Тест"), ("Тест", None))
        self.assertEqual(split_entry("🔎 X · a · b"), ("X · a", "b"))

    def test_flag(self):
        self.assertEqual(flag_of("🇫🇮 #1 Финляндия"), "🇫🇮")
        self.assertIsNone(flag_of("Россия"))

    def test_display_name(self):
        self.assertEqual(display_name("🇫🇮 #1 Финляндия"), "Финляндия #1")
        self.assertEqual(display_name("🇪🇺 [AUTO] Европа"), "AUTO Европа")
        self.assertEqual(display_name("🇷🇺 #3 Россия (МСК)"), "Россия (МСК) #3")
        self.assertEqual(display_name("🔎 🇩🇪 Германия · node-b"), "Германия · node-b")
        self.assertEqual(display_name("🇳🇱 Нидерланды (с рекламой)"), "Нидерланды (с рекламой)")

    def test_divider(self):
        self.assertTrue(is_divider("👇 🚧 Специальные локации 🚧 👇"))
        self.assertFalse(is_divider("🇩🇪 Германия"))

    def test_plural(self):
        f = ("локация", "локации", "локаций")
        self.assertEqual([plural(n, f) for n in (1, 2, 5, 11, 21, 22, 112)],
                         ["1 локация", "2 локации", "5 локаций", "11 локаций", "21 локация", "22 локации", "112 локаций"])

    def test_key(self):
        self.assertEqual((key_prefix("yt:🇸🇪 Швеция"), key_name("yt:🇸🇪 Швеция")), ("yt", "🇸🇪 Швеция"))
        self.assertEqual((key_prefix("mass_outage"), key_name("mass_outage")), ("mass_outage", ""))


class StripEmoji(unittest.TestCase):
    def test_trims_edges_left_by_emoji(self):
        self.assertEqual(strip_emoji("🔎 🇳🇱 Нидерланды ✅"), "Нидерланды")
        self.assertEqual(strip_emoji("⭐ звезда ⏳"), "звезда")

    def test_emoji_free_text_unchanged(self):
        for s in (" · ", "Локации × входы", "a — b…", "«x» ⌀ ™ ©", " ведущий пробел"):
            self.assertEqual(strip_emoji(s), s)

    def test_wider_emoji_ranges(self):
        for ch in ("⭐", "⬆", "⬛", "⌚", "⏰", "⏳", "‼", "⁉", "〰", "㊙",
                   "\U0001F3F4\U000E0067\U000E0062\U000E007F"):
            self.assertEqual(strip_emoji("x %s y" % ch), "x y", repr(ch))
        self.assertEqual(strip_emoji("1⃣ x"), "1 x")
