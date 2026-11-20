"""Демо-фикстура: прод на 11.11.2026 ~07:00 UTC. Для тестов, превью и демо-альбома."""
import history
from summary import is_divider

DIVIDER_NAME = "👇 🚧 Специальные локации 🚧 👇"
RU = "🇷🇺 Россия"

# имя, адрес, задержка ip-чекера, задержка download-чекера (None — выход не проверяется)
ENTRIES = [
    ("🇩🇪 Германия", "203.0.113.10:3442", 62, 180),
    ("🇪🇺 [AUTO] Европа", "203.0.113.10:3445", 71, 210),
    ("🇫🇮 #1 Финляндия", "203.0.113.10:3447", 48, 120),
    ("🇫🇮 #2 Финляндия", "203.0.113.10:3446", 53, 140),
    ("🇬🇧 Великобритания", "203.0.113.10:3443", 96, 546),
    ("🇳🇱 Нидерланды", "exit-1.example.net:443", 58, 190),
    ("🇳🇱 Нидерланды (с рекламой)", "exit-1.example.net:3443", 60, 200),
    (RU, "203.0.113.10:3444", 21, None),
    ("🇸🇪 Швеция", "203.0.113.10:3459", 77, 260),
    (DIVIDER_NAME, "exit-1.example.net:3443", 60, 200),
    ("🔎 🇩🇪 Германия · node-b", "203.0.113.10:3442", 84, 230),
    ("🔎 🇫🇮 #1 Финляндия · node-b", "203.0.113.10:3447", 69, 170),
    ("🔎 🇫🇮 #2 Финляндия · node-b", "203.0.113.10:3446", 73, 448),
    ("🔎 🇬🇧 Великобритания · node-b", "203.0.113.10:3443", 118, 330),
    ("🔎 🇳🇱 Нидерланды · node-b", "203.0.113.10:3455", 91, 397),
    ("🔎 🇸🇪 Швеция · node-b", "203.0.113.10:3459", 99, 310),
]

YT_RU = ("🇳🇱 Нидерланды", "🇳🇱 Нидерланды (с рекламой)")
YT_BAD = "YouTube видит страну FI (нужна RU) — будет реклама"
HAPROXY = ["be_smtp/exit-4", "be_smtp/exit-3", "be_smtp/exit-1", "be_socks/exit-4", "be_socks/exit-3", "be_socks/exit-1"]

BLIPS = {
    "loc:🔎 🇳🇱 Нидерланды · node-b": 4, "loc:🔎 🇬🇧 Великобритания · node-b": 3, "loc:🇬🇧 Великобритания": 3,
    "exit:🔎 🇸🇪 Швеция · node-b": 1, "exit:🔎 🇩🇪 Германия · node-b": 1, "exit:🇬🇧 Великобритания": 1,
    "exit:🔎 🇬🇧 Великобритания · node-b": 1,
}

# история суток: индекс часа окна (0 = 07:00 вчера) -> число сбоев; ALERTS — часы в тревоге
FAILS = {
    "loc:🇬🇧 Великобритания": {3: 1, 11: 2, 17: 1},
    "exit:🇬🇧 Великобритания": {11: 1},
    "loc:🔎 🇬🇧 Великобритания · node-b": {7: 1, 14: 1},
    "loc:🔎 🇳🇱 Нидерланды · node-b": {4: 1, 12: 3, 19: 1},
    "loc:🇸🇪 Швеция": {10: 1},
    "exit:🔎 🇸🇪 Швеция · node-b": {15: 2},
    "exit:🔎 🇩🇪 Германия · node-b": {20: 1},
}
ALERTS = {
    "loc:🔎 🇳🇱 Нидерланды · node-b": (1, 2, 8, 9),
    "loc:🔎 🇬🇧 Великобритания · node-b": (1, 2, 5),
    "exit:🔎 🇸🇪 Швеция · node-b": (22,),
}
NODATA = {"loc:" + RU: (0, 1)}


def demo_summary():
    locations, exits, yt = {}, {}, {}
    for name, addr, loc_ms, exit_ms in ENTRIES:
        locations[(name, addr)] = {"status": 1.0, "latency": float(loc_ms)}
        if exit_ms is not None:
            exits[(name, addr)] = {"status": 1.0, "latency": float(exit_ms)}
            if not is_divider(name):
                yt[name] = "RU" if name in YT_RU else "FI"
    return {
        "locations": locations,
        "exits": exits,
        "haproxy": {b: "UP" for b in HAPROXY},
        "quota": {"exit-1": (1210, None), "exit-2": (640, None), "exit-3": (355, None), "exit-4": (170, None),
                  "exit-6": (90, None), "node-a": (35, None)},
        "yt": yt,
        "yt_speed": {},
    }


def demo_state(now):
    s = demo_summary()
    checks = {}
    for (name, _), _v in s["locations"].items():
        checks["loc:" + name] = {"fails": 0, "alerted": False}
    for (name, _), _v in s["exits"].items():
        checks["exit:" + name] = {"fails": 0, "alerted": False}
    for b in HAPROXY:
        checks["hap:" + b] = {"fails": 0, "alerted": False, "last_detail": "статус UP"}
    for name, gl in s["yt"].items():
        if gl == "RU":
            checks["yt:" + name] = {"fails": 0, "alerted": False, "last_detail": "YouTube снова видит RU"}
        else:
            checks["yt:" + name] = {"fails": 2, "alerted": True, "alerted_at": now - 35640, "last_detail": YT_BAD}
    checks["quota_src:exit-5"] = {"fails": 3, "alerted": True, "alerted_at": now - 305280,
                               "last_detail": "нода не отдаёт счётчики"}
    return {"checks": checks, "blips": dict(BLIPS)}


def _jitter(i, k):
    """Детерминированный разброс задержки в пределах ±10%."""
    return ((i * 4 + k) * 37 % 21 - 10) / 100


def demo_history(state, now):
    s = demo_summary()
    keys = ["loc:" + n for n, _ in s["locations"]] + ["exit:" + n for n, _ in s["exits"]]
    exit_ms = {"exit:" + n: v["latency"] for (n, _), v in s["exits"].items()}
    base = now - now % history.HOUR
    for i in range(24):
        ts = base - (24 - i) * history.HOUR + 300
        for key in keys:
            if is_divider(key) or i in NODATA.get(key, ()):
                continue
            alerted = i in ALERTS.get(key, ())
            fails = FAILS.get(key, {}).get(i, 2 if alerted else 0)
            history.touch(state, ts, key, alerted)
            for _ in range(fails):
                history.add_fail(state, ts, key)
            if key in exit_ms and not alerted:
                for k in range(4):
                    history.add_latency(state, ts + k * 900, key, round(exit_ms[key] * (1 + _jitter(i, k))))
