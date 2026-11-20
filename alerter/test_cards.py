import copy
import io
import unittest
from unittest import mock
from datetime import datetime, timezone

from PIL import Image

from cards import fit_text, render_all, render_dashboard, render_heatmap, render_matrix, render_speed, text_width
from demo_data import demo_history, demo_state, demo_summary
from summary import _EMOJI, AlertGroup, build_models

NOW = datetime(2026, 11, 11, 7, 0, 30, tzinfo=timezone.utc).timestamp()


def with_history(st):
    demo_history(st, NOW)
    return st


def demo_models():
    return build_models(demo_summary(), with_history(demo_state(NOW)), NOW)


def png(data):
    return Image.open(io.BytesIO(data))


class Render(unittest.TestCase):
    def test_each_card_renders(self):
        m = demo_models()
        for fn, model, w in ((render_dashboard, m.dashboard, 1440), (render_matrix, m.matrix, 1440),
                             (render_heatmap, m.heatmap, 1520), (render_speed, m.speed, 1440)):
            im = png(fn(model))
            self.assertEqual((im.format, im.width), ("PNG", w))

    def test_render_all_order(self):
        widths = [png(b).width for b in render_all(demo_models())]
        self.assertEqual(widths, [1440, 1440, 1520, 1440])

    def test_missing_twemoji_does_not_crash(self):
        m = demo_models()
        m.matrix.rows[0].flag = "🇿🇿"
        m.heatmap.rows[0].flag = "🇿🇿"
        m.speed.rows[0].flag = "🇿🇿"
        m.dashboard.groups[0].keys = ["loc:🇿🇿 Зурбагань"]
        render_matrix(m.matrix)
        render_heatmap(m.heatmap)
        render_speed(m.speed)
        render_dashboard(m.dashboard)

    def test_empty_models_render(self):
        for b in render_all(build_models({}, {"checks": {}}, NOW)):
            self.assertEqual(png(b).format, "PNG")

    def test_no_history_renders(self):
        render_all(build_models(demo_summary(), demo_state(NOW), NOW))

    def test_height_follows_rows(self):
        m = demo_models()
        short = copy.deepcopy(m.matrix)
        short.rows = short.rows[:2]
        self.assertLess(png(render_matrix(short)).height, png(render_matrix(m.matrix)).height)
        short = copy.deepcopy(m.heatmap)
        short.rows = short.rows[:2]
        self.assertLess(png(render_heatmap(short)).height, png(render_heatmap(m.heatmap)).height)

    def test_no_emoji_reaches_font_drawing(self):
        from PIL import ImageDraw
        m = demo_models()
        m.dashboard.groups = [
            AlertGroup("exit", "node-b (1:1) 🔎 ⚠️", ["exit:🔎 🇳🇱 Нидерланды · node-b"], 1.0),
            AlertGroup("loc", "👨\u200d👩 нет 🇫🇮 связи", ["loc:🇫🇮 #1 Финляндия"], 2.0),
            AlertGroup("yt", "страна", ["yt:🇸🇪 Швеция", "yt:🇩🇪 X"], 3.0),
        ]
        m.dashboard.blips_line = "🔎 🇳🇱 Нидерланды ✅"
        drawn = []
        orig = ImageDraw.ImageDraw.text

        def spy(self, xy, text, *a, **kw):
            drawn.append(text)
            return orig(self, xy, text, *a, **kw)

        with mock.patch.object(ImageDraw.ImageDraw, "text", spy):
            render_dashboard(m.dashboard)
        self.assertIn("Выход у «Нидерланды · node-b»", drawn)
        self.assertIn("Локация Финляндия #1", drawn)
        for s in drawn:
            self.assertIsNone(_EMOJI.search(s), s)
            self.assertNotIn("  ", s)


class Fit(unittest.TestCase):
    def test_fit_keeps_value_tail(self):
        s = fit_text("медленнее всех Великобритания · node-b 448 мс", 140, 11)
        self.assertTrue(s.endswith("… 448 мс"), s)
        self.assertLessEqual(text_width(s, 11), 140)

    def test_fit_short_text_unchanged(self):
        self.assertEqual(fit_text("12 видят FI", 140, 11), "12 видят FI")

    def test_fit_plain_ellipsis(self):
        s = fit_text("Нидерланды (с рекламой) очень длинное имя", 100, 14, bold=True)
        self.assertTrue(s.endswith("…"), s)
        self.assertLessEqual(text_width(s, 14, bold=True), 100)
