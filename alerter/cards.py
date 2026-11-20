"""Карточки сводки: PNG из моделей summary. PIL импортируется только при отрисовке."""
import io
import math
import re
from functools import lru_cache
from pathlib import Path

from summary import MAIN_COLUMN, plural, strip_emoji

ASSETS = Path(__file__).parent / "assets"
S = 2
W, W_HEAT = 720, 760
PAD = 24

BG = (24, 26, 31)
PANEL = (34, 37, 44)
LINE = (52, 56, 66)
TXT = (232, 234, 238)
MUTED = (146, 151, 162)
GREEN = (52, 199, 120)
RED = (240, 82, 82)
AMBER = (240, 176, 56)
BLUE = (88, 150, 240)
PURPLE = (150, 120, 230)
PURPLE_TXT = (170, 145, 240)
GREEN_BG = (30, 70, 50)
RED_BG = (88, 36, 40)
AMBER_BG = (84, 64, 28)
NONE_BG = (44, 47, 55)
DIM_AMBER = (90, 80, 40)
NODATA_BG = (46, 49, 57)
NODATA_LINE = (78, 83, 96)
PLAQUE = (62, 66, 78)

STATUS = {"ok": (GREEN, GREEN_BG), "warn": (AMBER, AMBER_BG), "bad": (RED, RED_BG), "none": (MUTED, NONE_BG)}
HEAT = {"clean": PANEL, "one": DIM_AMBER, "many": AMBER, "alert": RED}
HEAT_LEGEND = [("clean", "чисто"), ("one", "1 сбой"), ("many", "2+ сбоя"), ("alert", "тревога"),
               ("nodata", "нет данных")]

_FLAG = re.compile("^[\U0001F1E6-\U0001F1FF]{2}$")
# последнее число с единицей в конце строки: «… 448 мс», «… 12 локаций»
_TAIL = re.compile(r"^(.*\S)(\s+\d+(?:[.,]\d+)?(?:\s*[^\s\d]+)?)$")


@lru_cache(maxsize=None)
def font(size, bold=False):
    from PIL import ImageFont
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(ASSETS / "fonts" / name), round(size * S))


def text_width(s, size, bold=False):
    return font(size, bold).getlength(strip_emoji(s)) / S


def _cut(s, width, size, bold):
    while s and text_width(s, size, bold) > width:
        s = s[:-1]
    return s.rstrip(" ·,:;—-")


def fit_text(text, width, size, bold=False):
    """Укорачивает до ширины с «…»; число с единицей в конце сохраняется."""
    text = strip_emoji(text)
    if text_width(text, size, bold) <= width:
        return text
    m = _TAIL.match(text)
    if m:
        tail = m.group(2)
        head = _cut(m.group(1), width - text_width("…" + tail, size, bold), size, bold)
        if head:
            return head + "…" + tail
    return _cut(text, width - text_width("…", size, bold), size, bold) + "…"


def wrap(text, width, size, bold=False, max_lines=2):
    words, lines = text.split(" "), []
    while words:
        if len(lines) == max_lines - 1:
            lines.append(fit_text(" ".join(words), width, size, bold))
            break
        n = 1
        while n < len(words) and text_width(" ".join(words[:n + 1]), size, bold) <= width:
            n += 1
        lines.append(fit_text(" ".join(words[:n]), width, size, bold))
        words = words[n:]
    return lines


def _emoji_file(ch):
    return ASSETS / "twemoji" / ("%s.png" % "-".join("%x" % ord(c) for c in ch if ord(c) != 0xFE0F))


@lru_cache(maxsize=None)
def _emoji(ch, size):
    from PIL import Image
    path = _emoji_file(ch)
    if not path.exists():
        return None
    im = Image.open(path).convert("RGBA")
    im = im.crop(im.getbbox())
    h = round(size * S)
    return im.resize((max(1, round(im.width * h / im.height)), h), Image.Resampling.LANCZOS)


@lru_cache(maxsize=None)
def _hatch(wpx, hpx, rpx):
    from PIL import Image, ImageDraw
    tile = Image.new("RGB", (wpx, hpx), NODATA_BG)
    d = ImageDraw.Draw(tile)
    for k in range(-hpx, wpx, 5 * S):
        d.line([(k, hpx), (k + hpx, 0)], fill=NODATA_LINE, width=S)
    mask = Image.new("L", (wpx, hpx), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, wpx - 1, hpx - 1], radius=rpx, fill=255)
    return tile, mask


class Card:
    def __init__(self, w, h):
        from PIL import Image, ImageDraw
        self.w = w
        self.im = Image.new("RGB", (w * S, round(h * S)), BG)
        self.d = ImageDraw.Draw(self.im)

    def text(self, xy, s, size=14, color=TXT, bold=False, anchor="la"):
        self.d.text((xy[0] * S, xy[1] * S), strip_emoji(s), font=font(size, bold), fill=color, anchor=anchor)

    def rect(self, box, fill, r=10):
        self.d.rounded_rectangle([v * S for v in box], radius=r * S, fill=fill)

    def hatch(self, box, r):
        x0, y0 = round(box[0] * S), round(box[1] * S)
        tile, mask = _hatch(round(box[2] * S) - x0, round(box[3] * S) - y0, round(r * S))
        self.im.paste(tile, (x0, y0), mask)

    def line(self, x0, y0, x1, y1, color=LINE):
        self.d.line([x0 * S, y0 * S, x1 * S, y1 * S], fill=color, width=S)

    def dot(self, x, y, r, color):
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=color)

    def icon(self, x, cy, ch, size):
        """Эмодзи по центру cy; флаг без PNG — плашка с кодом страны, прочее без PNG — пропуск."""
        if not ch:
            return 0
        im = _emoji(ch, size)
        if im is not None:
            self.im.paste(im, (round(x * S), round((cy - size / 2) * S)), im)
            return im.width / S
        if not _FLAG.match(ch):
            return 0
        code = "".join(chr(ord(c) - 0x1F1E6 + ord("A")) for c in ch)
        w = round(size * 1.4)
        self.rect((x, cy - size / 2, x + w, cy + size / 2), PLAQUE, r=3)
        self.text((x + w / 2, cy), code, size * 0.55, TXT, True, "mm")
        return w

    def png(self):
        buf = io.BytesIO()
        self.im.save(buf, "PNG", optimize=True)
        return buf.getvalue()


def header(c, title, subtitle, badge):
    status, text = badge
    fg, bg = STATUS.get(status, STATUS["none"])
    text = fit_text(text, 280, 13, True)
    bx = c.w - PAD - text_width(text, 13, True) - 34
    c.rect((bx, 22, c.w - PAD, 48), bg, r=13)
    c.dot(bx + 15, 35, 4, fg)
    c.text((bx + 24, 35), text, 13, fg, True, "lm")
    c.text((PAD, 22), fit_text(title, bx - PAD - 16, 20, True), 20, bold=True)
    c.text((PAD, 50), fit_text(subtitle, c.w - 2 * PAD, 13), 13, MUTED)


def pill(c, cx, cy, text, status, min_w, max_w):
    fg, bg = STATUS.get(status, STATUS["none"])
    text = fit_text(text, max_w - 12, 12, True)
    w = min(max(min_w, text_width(text, 12, True) + 20), max_w)
    c.rect((cx - w / 2, cy - 11, cx + w / 2, cy + 11), bg, r=11)
    c.text((cx, cy), text, 12, fg, True, "mm")


def name_cell(c, x, cy, flag, name, size, flag_size, right):
    """Флаг и имя строки; имя укорачивается до right."""
    w = c.icon(x, cy, flag, flag_size)
    tx = x + (w + 8 if w else 0)
    c.text((tx, cy), fit_text(name, right - tx, size), size, anchor="lm")


# --- 1. дашборд

TILE_GAP = 12
TILE_SUB = 11
SUB_LH = 15
GROUP_H = 48
GROUP_GAP = 8
BLIPS = 12
BLIPS_LH = 17


def render_dashboard(m):
    w = W
    n = max(1, len(m.tiles))
    tw = (w - 2 * PAD - (n - 1) * TILE_GAP) / n
    subs = [wrap(t.sub, tw - 24, TILE_SUB) if t.sub else [] for t in m.tiles]
    tile_h = 82 + SUB_LH * max([len(s) for s in subs] + [1]) + 12
    blips = wrap(m.blips_line, w - 2 * PAD, BLIPS) if m.blips_line else []
    top = 84
    gy = top + tile_h + 22
    rows_y = gy + 28
    h = rows_y + len(m.groups) * (GROUP_H + GROUP_GAP)
    if m.more:
        h += 22
    h += 6 + BLIPS_LH * len(blips) + 18

    c = Card(w, h)
    header(c, "Мониторинг · сутки", m.period, m.badge)
    for i, (t, sub) in enumerate(zip(m.tiles, subs)):
        x = PAD + i * (tw + TILE_GAP)
        fg = STATUS.get(t.status, STATUS["none"])[0]
        c.rect((x, top, x + tw, top + tile_h), PANEL)
        c.text((x + 12, top + 14), fit_text(t.label, tw - 24, 11.5), 11.5, MUTED)
        c.text((x + 12, top + 34), fit_text(t.value, tw - 24, 34, True), 34, fg, True)
        for k, line in enumerate(sub):
            c.text((x + 12, top + 82 + k * SUB_LH), line, TILE_SUB, MUTED)

    if m.groups:
        c.text((PAD, gy), "Висят", 14, bold=True)
    else:
        c.text((PAD, gy), "Висящих тревог нет", 14, GREEN, bold=True)
    y = rows_y
    ages = list(m.ages) + [""] * len(m.groups)
    for g, age in zip(m.groups, ages):
        c.rect((PAD, y, w - PAD, y + GROUP_H), PANEL)
        c.d.rectangle([PAD * S, (y + 8) * S, (PAD + 3) * S, (y + GROUP_H - 8) * S], fill=RED)
        c.icon(40, y + GROUP_H / 2, g.icon, 20)
        right = w - 40
        if age:
            c.text((right, y + GROUP_H / 2), age, 13, MUTED, anchor="rm")
            right -= text_width(age, 13) + 16
        tx = 76
        detail = g.short_detail
        if detail:
            c.text((tx, y + 8), fit_text(g.card_title, right - tx, 14, True), 14, bold=True)
            c.text((tx, y + 28), fit_text(detail, right - tx, 12), 12, MUTED)
        else:
            c.text((tx, y + GROUP_H / 2), fit_text(g.card_title, right - tx, 14, True), 14, bold=True, anchor="lm")
        y += GROUP_H + GROUP_GAP
    if m.more:
        c.text((PAD, y), "и ещё %s" % plural(m.more, ("тревога", "тревоги", "тревог")), 12, MUTED)
        y += 22
    y += 6
    for k, line in enumerate(blips):
        c.text((PAD, y + k * BLIPS_LH), line, BLIPS, MUTED)
    return c.png()


# --- 2. локации × входы

ROW_H = 40
FOOTNOTE = "YouTube: страна, которую видит Google (RU = без рекламы). Задержка — худший из входов, до первого байта."


def _column_label(c, cx, cy, label, colw):
    if text_width(label, 12) <= colw - 6:
        c.text((cx, cy), label, 12, MUTED, anchor="mm")
        return
    head, _, tail = label.rpartition(" ")
    if head and max(text_width(head, 12), text_width(tail, 12)) <= colw - 6:
        c.text((cx, cy - 7), head, 12, MUTED, anchor="mm")
        c.text((cx, cy + 7), tail, 12, MUTED, anchor="mm")
    else:
        c.text((cx, cy), fit_text(label, colw - 6, 12), 12, MUTED, anchor="mm")


def render_matrix(m):
    w = W
    labels = [col if col == MAIN_COLUMN else "Вход " + col for col in m.columns] + ["YouTube", "Задержка"]
    colw = min(108, (w - 2 * PAD - 210) / len(labels))
    name_end = w - PAD - len(labels) * colw
    centers = [name_end + colw * (i + 0.5) for i in range(len(labels))]
    foot = wrap(FOOTNOTE, w - 2 * PAD, 11)
    y0 = 92
    h = y0 + 26 + ROW_H * max(1, len(m.rows)) + 14 + 15 * len(foot) + 18

    c = Card(w, h)
    header(c, "Локации × входы", m.period, m.badge)
    for label, cx in zip(labels, centers):
        _column_label(c, cx, y0 + 8, label, colw)
    y = y0 + 26
    if not m.rows:
        c.line(PAD, y, w - PAD, y)
        c.text((w / 2, y + ROW_H / 2), "нет данных", 13, MUTED, anchor="mm")
        y += ROW_H
    for r in m.rows:
        cy = y + ROW_H / 2
        c.line(PAD, y, w - PAD, y)
        name_cell(c, 28, cy, r.flag, r.name, 14, 18, name_end - 8)
        values = list(r.cells) + [r.yt]
        for i, (text, status) in enumerate(values):
            if status == "none":
                c.text((centers[i], cy), "—", 14, MUTED, anchor="mm")
            else:
                pill(c, centers[i], cy, text, status, 52 if i == len(values) - 1 else 64, colw - 8)
        text, status = r.latency
        c.text((centers[-1], cy), fit_text(text, colw - 6, 13), 13, STATUS.get(status, STATUS["none"])[0],
               anchor="mm")
        y += ROW_H
    c.line(PAD, y, w - PAD, y)
    for k, line in enumerate(foot):
        c.text((PAD, y + 14 + k * 15), line, 11, MUTED)
    return c.png()


# --- 3. сутки по часам

HEAT_ROW = 28
CELL = 20


def heat_cell(c, box, kind, r=4):
    if kind == "nodata":
        c.hatch(box, r)
    else:
        c.rect(box, HEAT.get(kind, PANEL), r=r)


def render_heatmap(m):
    w = W_HEAT
    x0 = w - PAD - len(m.hours) * CELL
    y0 = 92
    h = y0 + 22 + HEAT_ROW * max(1, len(m.rows)) + 18 + 14 + 22

    c = Card(w, h)
    header(c, "Сутки по часам", "сбои проб · " + m.period, m.badge)
    for i, hh in enumerate(m.hours):
        if i % 3 == 0:
            c.text((x0 + i * CELL + CELL / 2, y0), hh, 11, MUTED, anchor="ma")
    y = y0 + 22
    if not m.rows:
        c.text((w / 2, y + HEAT_ROW / 2), "нет данных", 13, MUTED, anchor="mm")
        y += HEAT_ROW
    for r in m.rows:
        name_cell(c, PAD, y + HEAT_ROW / 2, r.flag, r.name, 13, 16, x0 - 10)
        for i, kind in enumerate(r.cells):
            heat_cell(c, (x0 + i * CELL + 1.5, y + 3, x0 + (i + 1) * CELL - 1.5, y + HEAT_ROW - 3), kind)
        y += HEAT_ROW
    lx = PAD
    for kind, label in HEAT_LEGEND:
        heat_cell(c, (lx, y + 18, lx + 14, y + 32), kind, r=3)
        c.text((lx + 20, y + 25), label, 12, MUTED, anchor="lm")
        lx += 20 + text_width(label, 12) + 22
    return c.png()


# --- 4. скорость выходов

SPEED_ROW = 38


def _scale(vmax):
    """Шаг сетки и правый край шкалы: не больше 4 делений."""
    vmax = max(vmax * 1.05, 1)
    k = 10 ** math.floor(math.log10(vmax / 4))
    for step in (k, 2 * k, 2.5 * k, 5 * k, 10 * k):
        if math.ceil(vmax / step) <= 4:
            return step, math.ceil(vmax / step) * step
    return 10 * k, 4 * 10 * k


def render_speed(m):
    w = W
    x0, x1 = 250, w - 70
    values = [v for r in m.rows for v in (r.main_ms, r.alt_ms) if v is not None]
    n = max(1, len(m.rows))
    top = 96
    h = top + SPEED_ROW * n + (58 if values else 20)

    c = Card(w, h)
    header(c, "Скорость выходов", "время до первого байта, медиана за сутки", m.badge)
    if values:
        step, vmax = _scale(max(values))
        k = 0
        while k * step <= vmax:
            x = x0 + (x1 - x0) * k * step / vmax
            c.line(x, top, x, top + SPEED_ROW * n)
            c.text((x, top - 4), "%g" % (k * step), 11, MUTED, anchor="md")
            k += 1
    y = top
    if not m.rows:
        c.text((w / 2, y + SPEED_ROW / 2), "нет данных", 13, MUTED, anchor="mm")
        y += SPEED_ROW
    for r in m.rows:
        cy = y + SPEED_ROW / 2
        name_cell(c, PAD, cy, r.flag, r.name, 13, 16, x0 - 14)
        if r.main_ms is None and r.alt_ms is None:
            c.text((x0 + 8, cy), "нет данных", 12, MUTED, anchor="lm")
        for v, by, color, tcolor in ((r.main_ms, 7, BLUE, BLUE), (r.alt_ms, 20, PURPLE, PURPLE_TXT)):
            if v is None:
                continue
            c.rect((x0, y + by, x0 + max(8, (x1 - x0) * v / vmax), y + by + 10), color, r=4)
            c.text((x1 + 8, y + by + 5), "%.0f" % v, 11, tcolor, anchor="lm")
        y += SPEED_ROW
    if not values:
        return c.png()
    c.rect((PAD, y + 20, PAD + 14, y + 30), BLUE, r=3)
    c.text((PAD + 20, y + 25), "основной вход", 12, MUTED, anchor="lm")
    if m.alt_label:
        lx = PAD + 20 + text_width("основной вход", 12) + 26
        c.rect((lx, y + 20, lx + 14, y + 30), PURPLE, r=3)
        c.text((lx + 20, y + 25), fit_text("вход " + m.alt_label, w - PAD - 40 - lx - 20, 12), 12, MUTED,
               anchor="lm")
    c.text((w - PAD, y + 25), "мс", 11, MUTED, anchor="rm")
    return c.png()


def render_all(models):
    return [render_dashboard(models.dashboard), render_matrix(models.matrix),
            render_heatmap(models.heatmap), render_speed(models.speed)]
