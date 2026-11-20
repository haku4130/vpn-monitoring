"""Хелперы сводки: имена локаций, склонения, тексты ключей."""
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

DIVIDER = "\U0001f447"
_FLAG = re.compile("[\U0001F1E6-\U0001F1FF]{2}")
# \u0442\u043E\u043B\u044C\u043A\u043E \u044D\u043C\u043E\u0434\u0437\u0438-\u043F\u0440\u0435\u0434\u0441\u0442\u0430\u0432\u043B\u0435\u043D\u0438\u044F: \u2122 \u00A9 \u2300 \u0438 \u0441\u0442\u0440\u0435\u043B\u043A\u0438 DejaVu \u0440\u0438\u0441\u0443\u0435\u0442 \u0441\u0430\u043C
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u20E3\U000E0020-\U000E007F"
    "\u203C\u2049\u231A\u231B\u2328\u23CF\u23E9-\u23F3\u23F8-\u23FA"
    "\u2B05-\u2B07\u2B1B\u2B1C\u2B50\u2B55\u3030\u303D\u3297\u3299]")


def is_divider(name):
    return DIVIDER in name


def split_entry(name):
    if not name.startswith("🔎 "):
        return name, None
    base, sep, node = name[2:].rpartition(" · ")
    return (base, node) if sep else (name[2:], None)


def flag_of(name):
    m = _FLAG.search(name)
    return m.group(0) if m else None


def display_name(name):
    base, node = split_entry(name)
    base = _EMOJI.sub("", base).strip()
    m = re.match(r"#(\d+)\s+(.*)$", base)
    if m:
        base = "%s #%s" % (m.group(2), m.group(1))
    m = re.match(r"\[([^\]]+)\]\s*(.*)$", base)
    if m:
        base = ("%s %s" % (m.group(1), m.group(2))).strip()
    base = re.sub(r"\s+", " ", base)
    return "%s · %s" % (base, node) if node else base


def strip_emoji(s):
    cleaned = _EMOJI.sub("", s)
    if cleaned == s:
        return s
    return re.sub(r" {2,}", " ", cleaned).strip()


def plural(n, forms):
    m100, m10 = n % 100, n % 10
    if 11 <= m100 <= 14:
        f = forms[2]
    elif m10 == 1:
        f = forms[0]
    elif 2 <= m10 <= 4:
        f = forms[1]
    else:
        f = forms[2]
    return "%d %s" % (n, f)


def key_prefix(key):
    return key.partition(":")[0]


def key_name(key):
    return key.partition(":")[2]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pretty(key, name=lambda s: s):
    if key.startswith("loc:"):
        return "Локация " + name(key[4:])
    if key.startswith("exit:"):
        return "Выход у «" + name(key[5:]) + "»"
    if key.startswith("hap_pool:"):
        return "HAProxy, пул " + key[9:]
    if key.startswith("hap:"):
        return "HAProxy " + key[4:]
    if key.startswith("yt:"):
        return "Реклама YouTube на «" + name(key[3:]) + "»"
    if key.startswith("ytspeed:"):
        return "YouTube на «" + name(key[8:]) + "»"
    if key.startswith("quota:"):
        return "Трафик на " + key[6:]
    if key.startswith("quota_src:"):
        return "Счётчики трафика: " + key[10:]
    if key.startswith("source:"):
        return "Источник данных: " + key[7:]
    if key.startswith("mask:"):
        return "Маскировка " + key[5:]
    if key.startswith("web:"):
        return key[4:]
    if key.startswith("cdn:"):
        return "Подписка " + key[4:]
    if key.startswith("cdn_via:"):
        loc, _, domain = key[8:].rpartition(" · ")
        return "Подписка %s через «%s»" % (domain, name(loc))
    if key == "mass_outage":
        return "Массовое падение локаций"
    return key


def duration_text(seconds):
    minutes = int(seconds // 60)
    if minutes < 60:
        return "%d мин" % minutes
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return "%d ч %d мин" % (hours, minutes)
    days, hours = divmod(hours, 24)
    return "%d д %d ч" % (days, hours)


GROUP_KINDS = {
    "yt": ("Реклама YouTube", ("локация", "локации", "локаций"), "📺"),
    "ytspeed": ("YouTube", ("локация", "локации", "локаций"), "📺"),
    "loc": ("Локации", ("локация", "локации", "локаций"), "🔌"),
    "exit": ("Выходы", ("выход", "выхода", "выходов"), "🔌"),
    "hap": ("HAProxy", ("бэкенд", "бэкенда", "бэкендов"), "🔌"),
    "hap_pool": ("HAProxy, пулы", ("пул", "пула", "пулов"), "🔌"),
    "quota": ("Трафик", ("нода", "ноды", "нод"), "🔌"),
    "quota_src": ("Счётчики трафика", ("нода", "ноды", "нод"), "🔌"),
    "mask": ("Маскировка", ("домен", "домена", "доменов"), "🔌"),
    "cdn_via": ("Подписка через локации", ("путь", "пути", "путей"), "📥"),
    "source": ("Источники данных", ("источник", "источника", "источников"), "🔌"),
}

_YT_REGION = re.compile(r"^YouTube видит страну (\w+) \(нужна (\w+)\) — будет реклама$")


@dataclass
class AlertGroup:
    prefix: str
    detail: str
    keys: list
    since: "float | None" = None

    @property
    def title(self):
        if len(self.keys) == 1:
            return pretty(self.keys[0])
        title, forms, _ = GROUP_KINDS[self.prefix]
        return "%s — %s" % (title, plural(len(self.keys), forms))

    @property
    def card_title(self):
        if len(self.keys) == 1:
            return pretty(self.keys[0], display_name)
        return self.title

    @property
    def icon(self):
        if len(self.keys) == 1:
            flag = flag_of(key_name(self.keys[0]))
            if flag:
                return flag
        kind = GROUP_KINDS.get(self.prefix)
        return kind[2] if kind else None

    @property
    def short_detail(self):
        m = _YT_REGION.match(self.detail)
        return "страна %s вместо %s" % m.groups() if m else self.detail


def _glue(items):
    """items: (key, detail, since) -> группы; клеятся только известные префиксы с одинаковым detail."""
    groups, index = [], {}
    for key, detail, since in items:
        prefix = key_prefix(key)
        gk = (prefix, detail) if prefix in GROUP_KINDS else None
        g = index.get(gk) if gk else None
        if g is None:
            g = AlertGroup(prefix, detail, [], None)
            groups.append(g)
            if gk:
                index[gk] = g
        g.keys.append(key)
        if since is not None and (g.since is None or since < g.since):
            g.since = since
    return groups


def group_alerts(checks):
    items = [(k, st.get("last_detail") or "", st.get("alerted_at"))
             for k, st in checks.items() if st.get("alerted") and not is_divider(k)]
    groups = _glue(items)
    groups.sort(key=lambda g: (g.since is None, g.since or 0))
    return groups


def format_events(events):
    blocks = []
    for kind, head in (("down", "🔴 <b>Проблема</b>"), ("warn", "🟡 <b>Предупреждение</b>"),
                       ("up", "🟢 <b>Восстановилось</b>")):
        items = [(k, d, None) for kd, k, d in events if kd == kind]
        if not items:
            continue
        lines = [head]
        for g in _glue(items):
            lines.append("• %s%s" % (esc(g.title), (" — " + esc(g.detail)) if g.detail else ""))
            if len(g.keys) > 1:
                lines.append("<blockquote expandable>%s</blockquote>" % "\n".join(esc(key_name(k)) for k in g.keys))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# --- модели карточек: данные для отрисовки, без Pillow

MAIN_COLUMN = "Основной вход"
MAX_GROUPS = 5
LAT_OK, LAT_WARN = 300, 500


@dataclass
class Tile:
    label: str
    value: str
    status: str
    sub: str


@dataclass
class DashboardModel:
    period: str
    badge: tuple
    tiles: list
    groups: list
    more: int
    blips_line: str
    ages: list = field(default_factory=list)   # длительность каждой группы, "" без alerted_at


@dataclass
class MatrixRow:
    flag: "str | None"
    name: str
    cells: list
    yt: tuple
    latency: tuple


@dataclass
class MatrixModel:
    period: str
    badge: tuple
    columns: list
    rows: list


@dataclass
class HeatRow:
    flag: "str | None"
    name: str
    cells: list


@dataclass
class HeatmapModel:
    period: str
    badge: tuple
    hours: list
    rows: list


@dataclass
class SpeedRow:
    flag: "str | None"
    name: str
    main_ms: "float | None"
    alt_ms: "float | None"


@dataclass
class SpeedModel:
    badge: tuple
    alt_label: "str | None"
    rows: list


@dataclass
class SummaryModels:
    dashboard: DashboardModel
    matrix: MatrixModel
    heatmap: HeatmapModel
    speed: SpeedModel


def _utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc)


def period_text(now):
    end = now - now % 3600
    return "%s — %s UTC" % (_utc(end - 86400).strftime("%d.%m %H:%M"), _utc(end).strftime("%d.%m %H:%M"))


def ratio_status(x, y):
    if x == y:
        return "ok"
    return "warn" if x > 0 else "bad"


def _verb(n, one, many):
    return one if n % 10 == 1 and n % 100 != 11 else many


def _entries(data):
    """{(name, addr): v} -> {name: v} без разделителей."""
    return {n: v for (n, _), v in (data or {}).items() if not is_divider(n)}


def _up(v):
    return v.get("status", 0) >= 1


def _alerted(checks, key):
    return bool(checks.get(key, {}).get("alerted"))


def subsystem_counts(summary):
    """Счётчики x/y подсистем (общие для плиток и подписи); нет данных — ключа нет."""
    counts = {}
    locs = _entries(summary.get("locations"))
    if locs:
        counts["loc"] = (sum(1 for v in locs.values() if _up(v)), len(locs))
    exits = _entries(summary.get("exits"))
    if exits:
        counts["exit"] = (sum(1 for v in exits.values() if _up(v)), len(exits))
    yt = {n: g for n, g in (summary.get("yt") or {}).items() if not is_divider(n)}
    if yt:
        counts["yt"] = (sum(1 for g in yt.values() if g == "RU"), len(yt))
    hap = summary.get("haproxy") or {}
    if hap:
        counts["hap"] = (sum(1 for v in hap.values() if v.startswith("UP")), len(hap))
    return counts


def _tiles(summary):
    tiles = []
    counts = subsystem_counts(summary)
    locs = _entries(summary.get("locations"))
    if locs:
        down = [display_name(n) for n, v in locs.items() if not _up(v)]
        if not down:
            sub = "все работают"
        elif len(down) == 1:
            sub = "%s лежит" % down[0]
        else:
            sub = "лежат: " + ", ".join(down[:2]) + (" и ещё %d" % (len(down) - 2) if len(down) > 2 else "")
        x = counts["loc"][0]
        tiles.append(Tile("Локации", "%d/%d" % (x, len(locs)), "bad" if down else "ok", sub))
    else:
        tiles.append(Tile("Локации", "—", "none", "нет данных"))
    exits = _entries(summary.get("exits"))
    if exits:
        x = counts["exit"][0]
        slow = max(((v.get("latency") or 0, n) for n, v in exits.items() if _up(v)), default=(0, None))
        sub = "медленнее всех %s %.0f мс" % (display_name(slow[1]), slow[0]) if slow[0] else ""
        tiles.append(Tile("Выходы", "%d/%d" % (x, len(exits)), ratio_status(x, len(exits)), sub))
    else:
        tiles.append(Tile("Выходы", "—", "none", "нет данных"))
    yt = {n: g for n, g in (summary.get("yt") or {}).items() if not is_divider(n)}
    if yt:
        bad = [g for g in yt.values() if g != "RU"]
        if not bad:
            sub = "все видят RU"
        elif len(set(bad)) == 1:
            sub = "%d видят %s" % (len(bad), bad[0])
        else:
            sub = "%d видят не RU" % len(bad)
        x = counts["yt"][0]
        tiles.append(Tile("YouTube без рекламы", "%d/%d" % (x, len(yt)), ratio_status(x, len(yt)), sub))
    else:
        tiles.append(Tile("YouTube без рекламы", "—", "none", "нет данных"))
    hap = summary.get("haproxy") or {}
    if hap:
        pools = {}
        for k, v in hap.items():
            pools.setdefault(k.partition("/")[0], []).append(v.startswith("UP"))
        dead = sorted(p for p, ups in pools.items() if not any(ups))
        x = counts["hap"][0]
        if dead:
            sub = ("пул лежит: " if len(dead) == 1 else "пулы лежат: ") + ", ".join(dead)
        elif x < len(hap):
            sub = "не UP: %d" % (len(hap) - x)
        else:
            sub = ", ".join(sorted(pools))
        # падение целого пула — красный, как и падение локации
        tiles.append(Tile("HAProxy", "%d/%d" % (x, len(hap)), "bad" if dead else ratio_status(x, len(hap)), sub))
    else:
        tiles.append(Tile("HAProxy", "—", "none", "нет данных"))
    return tiles


def _blip_counts(blips):
    counts = {}
    for key, n in (blips or {}).items():
        if not is_divider(key):
            name = display_name(key_name(key)) if key_prefix(key) in ("loc", "exit") else pretty(key)
            counts[name] = counts.get(name, 0) + n
    return counts


def _blips_line(blips):
    counts = _blip_counts(blips)
    total = sum(counts.values())
    if not total:
        return "Одиночных сбоев без тревоги не было"
    top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:3]
    return "Одиночных сбоев без тревоги: %d · чаще всех: %s" % (total, ", ".join("%s %d" % t for t in top))


def _dashboard(summary, state, now):
    tiles = _tiles(summary)
    groups = group_alerts(state.get("checks") or {})
    if groups:
        n = len(groups)
        badge = ("warn", "%s %s" % (plural(n, ("тревога", "тревоги", "тревог")), _verb(n, "висит", "висят")))
    elif all(t.status == "none" for t in tiles):
        badge = ("none", "нет данных")
    else:
        badge = ("ok", "всё в норме")
    shown = groups[:MAX_GROUPS]
    ages = [duration_text(now - g.since) if g.since is not None else "" for g in shown]
    return DashboardModel(period_text(now), badge, tiles, shown, len(groups) - len(shown),
                          _blips_line(state.get("blips")), ages)


def _layout(*datas):
    """Базовые локации по порядку появления и найденные суффиксы входов."""
    bases, nodes = {}, set()
    for data in datas:
        for name in data:
            base, node = split_entry(name)
            bases.setdefault(base, {})[node] = name
            if node:
                nodes.add(node)
    return bases, sorted(nodes)


def _entry_cell(name, locs, exits, checks, exits_checked=True):
    loc, ex = locs.get(name), exits.get(name)
    if loc is None and ex is None:
        return ("—", "none")
    if loc is not None and not _up(loc):
        return ("лежит", "bad")
    if ex is not None and (not _up(ex) or _alerted(checks, "exit:" + name)):
        return ("режут", "warn")
    if not exits_checked:
        return ("жив", "none")
    return ("OK", "ok")


def _yt_cell(names, yt):
    gls = sorted({yt[n] for n in names if n in yt}, key=lambda g: (g != "RU", g))
    if not gls:
        return ("—", "none")
    return ("/".join(gls), "ok" if gls == ["RU"] else "warn")


def _latency_cell(names, exits):
    ms = [exits[n].get("latency") or 0 for n in names if n in exits and _up(exits[n])]
    worst = max(ms, default=0)
    if not worst:
        return ("—", "none")
    return ("%.0f мс" % worst, "ok" if worst < LAT_OK else "warn" if worst < LAT_WARN else "bad")


def _matrix(summary, state, now):
    locs, exits = _entries(summary.get("locations")), _entries(summary.get("exits"))
    yt, checks = summary.get("yt") or {}, state.get("checks") or {}
    bases, nodes = _layout(locs, exits)
    rows = []
    for base, by_node in bases.items():
        cells = [_entry_cell(by_node[node], locs, exits, checks, bool(exits)) if node in by_node else ("—", "none")
                 for node in [None] + nodes]
        names = list(by_node.values())
        rows.append(MatrixRow(flag_of(base), display_name(base), cells, _yt_cell(names, yt),
                              _latency_cell(names, exits)))
    states = [c[1] for r in rows for c in r.cells]
    down, cut = states.count("bad"), states.count("warn")
    if down:
        badge = ("bad", "%s %s" % (plural(down, ("вход", "входа", "входов")), _verb(down, "лежит", "лежат")))
    elif cut:
        badge = ("warn", "режут %s" % plural(cut, ("вход", "входа", "входов")))
    elif rows and not exits:
        badge = ("none", "выходы не проверены")
    elif rows:
        badge = ("ok", "все входы работают")
    else:
        badge = ("none", "нет данных")
    return MatrixModel("состояние на %s UTC" % _utc(now).strftime("%d.%m %H:%M"), badge,
                       [MAIN_COLUMN] + nodes, rows)


def _history_view(state):
    # history.* делает setdefault, а модели не должны менять state
    return {"history": state.get("history") or {"hours": {}}}


def _heatmap(summary, state, now):
    import history  # history импортирует summary: импорт здесь, чтобы не было цикла
    window = history.day_window(now)
    heat = history.heat_rows(_history_view(state), now)
    names = list(_entries(summary.get("locations"))) + list(_entries(summary.get("exits")))
    names += sorted(heat)
    rows, seen = [], set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        rows.append(HeatRow(flag_of(name), display_name(name), heat.get(name, ["nodata"] * len(window))))
    n = sum(1 for r in rows if "alert" in r.cells)
    if n:
        badge = ("warn", "%s с тревогой" % plural(n, ("строка", "строки", "строк")))
    elif all(c == "nodata" for r in rows for c in r.cells):
        badge = ("none", "нет данных")
    else:
        badge = ("ok", "без тревог")
    return HeatmapModel(period_text(now), badge, [h[-2:] for h in window], rows)


def _speed(summary, state, now):
    import history
    medians = history.latency_medians(_history_view(state), now)
    exits = _entries(summary.get("exits"))
    bases, nodes = _layout(list(exits) + sorted(n for n in medians if n not in exits))
    alt = nodes[0] if nodes else None
    rows = [SpeedRow(flag_of(base), display_name(base),
                     medians.get(by_node[None]) if None in by_node else None,
                     medians.get(by_node[alt]) if alt in by_node else None)
            for base, by_node in bases.items()]
    rows.sort(key=lambda r: -max((x for x in (r.main_ms, r.alt_ms) if x is not None), default=-1))
    checks = state.get("checks") or {}
    n = sum(1 for k, st in checks.items()
            if key_prefix(k) == "exit" and st.get("alerted") and not is_divider(k))
    if n:
        badge = ("warn", "%s в тревоге" % plural(n, ("выход", "выхода", "выходов")))
    elif not medians:
        badge = ("none", "нет данных")
    else:
        badge = ("ok", "все в норме")
    return SpeedModel(badge, alt, rows)


def build_models(summary, state, now):
    return SummaryModels(_dashboard(summary, state, now), _matrix(summary, state, now),
                         _heatmap(summary, state, now), _speed(summary, state, now))


# --- подпись A: шапка + раскрываемая цитата

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
HEADER_GROUPS = 3
TITLE_MAX = 80
_CIRCLE = {"ok": "🟢", "warn": "🟡", "bad": "🔴"}
_TAG = re.compile(r"<[^>]*>")


def visible_len(text):
    return len(html.unescape(_TAG.sub("", text)).encode("utf-16-le")) // 2


def _cut(text, n):
    return text if len(text) <= n else text[:n - 1] + "…"


def _counter_line(counts, parts, extra=None):
    """parts: (ключ, подпись); кружок — худший статус счётчиков x/y; extra не влияет на цвет."""
    shown = [(label, counts[k]) for k, label in parts if k in counts]
    items = ["%s %d/%d" % (label, x, y) for label, (x, y) in shown]
    if extra:
        items.append(extra)
    if not items:
        return None
    statuses = [ratio_status(x, y) for _, (x, y) in shown]
    worst = "bad" if "bad" in statuses else "warn" if "warn" in statuses else "ok"
    return "%s %s" % (_CIRCLE[worst], " · ".join(items))


def _header(summary, state, now):
    end = now - now % 3600
    lines = ["<b>Мониторинг · сутки</b> до %s UTC" % _utc(end).strftime("%d.%m %H:00")]
    groups = group_alerts(state.get("checks") or {})
    if groups:
        n = len(groups)
        lines.append("🔴 <b>%s %s</b>" % (_verb(n, "Висит", "Висят"),
                                           plural(n, ("тревога", "тревоги", "тревог"))))
        shown = groups if n <= HEADER_GROUPS else groups[:HEADER_GROUPS - 1]
        for g in shown:
            line = "• " + esc(_cut(g.title, TITLE_MAX))
            if g.since is not None:
                line += " · " + duration_text(now - g.since)
            lines.append(line)
        if n > len(shown):
            lines.append("• и ещё %d" % (n - len(shown)))
    else:
        lines.append("💚 Тревог нет")
    counts = subsystem_counts(summary)
    line = _counter_line(counts, [("loc", "Локации"), ("exit", "выходы"), ("hap", "HAProxy")])
    if line:
        lines.append(line)
    blips = sum(_blip_counts(state.get("blips")).values())
    line = _counter_line(counts, [("yt", "YouTube без рекламы")], ("сбоев без тревоги %d" % blips) if blips else None)
    if line:
        lines.append(line if "yt" in counts else line[2:])
    return "\n".join(lines)


def _details(summary, state, now=None):
    lines = []
    for g in group_alerts(state.get("checks") or {}):
        if len(g.keys) > 1:
            line = "%s: %s" % (esc(g.title), esc(", ".join(display_name(key_name(k)) for k in g.keys)))
            lines.append(line + (" — " + esc(g.short_detail) if g.short_detail else ""))
        else:
            lines.append("%s — %s" % (esc(g.title), esc(g.short_detail)) if g.short_detail else esc(g.title))
    locs = _entries(summary.get("locations"))
    down = [display_name(n) for n, v in locs.items() if not _up(v)]
    if down:
        lines.append("Не работает: " + esc(", ".join(down)))
    exits = _entries(summary.get("exits"))
    # последний замер в 07:00 бывает выбросом (1564 мс у Швеции при медиане 650), поэтому медиана за сутки
    medians = {}
    if now is not None:
        import history
        medians = history.latency_medians(_history_view(state), now)
    label = "Медленнее всех (медиана за сутки): " if medians else "Медленнее всех: "
    lat = (lambda n, v: medians.get(n)) if medians else (lambda n, v: v.get("latency"))
    slow = sorted(((lat(n, v) or 0, n) for n, v in exits.items() if _up(v)), reverse=True)[:3]
    slow = [(ms, n) for ms, n in slow if ms]
    if slow:
        lines.append(label + esc(", ".join("%s %.0f мс" % (display_name(n), ms) for ms, n in slow)))
    quota = summary.get("quota") or {}
    if quota:
        items = []
        for name, (used, limit) in sorted(quota.items(), key=lambda x: -x[1][0]):
            items.append("%s %.0f из %d ГиБ (%.0f%%)" % (name, used, limit, used / limit * 100) if limit else "%s %.0f ГиБ" % (name, used))
        lines.append("Трафик: " + esc(", ".join(items)))
    blips = sorted(_blip_counts(state.get("blips")).items(), key=lambda x: (-x[1], x[0]))[:5]
    if blips:
        lines.append("Сбои без тревоги: " + esc(", ".join("%s %d" % t for t in blips)))
    ys = summary.get("yt_speed") or {}
    if ys:
        lines.append("YouTube на российских: " + esc(", ".join("%s %d Мбит/с" % (n, v) for n, v in ys.items())))
    bad = [k for k, v in (summary.get("haproxy") or {}).items() if not v.startswith("UP")]
    if bad:
        lines.append("HAProxy не UP: " + esc(", ".join(bad)))
    return "\n".join(lines)


def caption_parts(summary, state, now):
    return _header(summary, state, now), _details(summary, state, now)


def _quote(prefix, lines, limit=None):
    """prefix + раскрываемая цитата; с limit строки срезаются с конца, последняя строка «…»."""
    def build(ls):
        return prefix + "<blockquote expandable>" + "\n".join(ls) + "</blockquote>"
    if limit is None or len(build(lines)) <= limit:
        return build(lines)
    lines = list(lines)
    while lines and len(build(lines + ["…"])) > limit:
        lines.pop()
    return build(lines + ["…"])


def compose_caption(header, details):
    if not details:
        return header, None
    full = header + "\n<blockquote expandable>" + details + "</blockquote>"
    if visible_len(full) <= CAPTION_LIMIT:
        return full, None
    return header, _quote("<b>Подробности</b>\n", details.split("\n"), MESSAGE_LIMIT)


def fallback_text(header, details):
    if not details:
        return header
    return _quote(header + "\n", details.split("\n"), MESSAGE_LIMIT)
