#!/usr/bin/env python3
"""zanity-alerter — следит за тем, что реально работает, и пишет в админ-чат.

Источники:
  * xray-checker (метод ip)       — локация вообще живая, проверяется через сам конфиг;
  * xray-checker (метод download) — проба уходит на ru-blocked домен, то есть реально
    через европейский выход: ловит и мёртвый выход, и порезанную полосу;
  * HAProxy на node-b               — пулы socks/smtp, через которые живут телеграм и почта.

Телеграм на node-b недоступен напрямую, поэтому отправка идёт curl-ом через тот же socks,
что и у бота. Токен и чат берём из .env бота, чтобы не плодить копии секретов.
"""

import argparse
import copy
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone

import history
from summary import (esc, pretty, duration_text, format_events, is_divider, key_name,
                     build_models, caption_parts, compose_caption, fallback_text)

CONFIG_PATH = os.environ.get("ALERTER_CONFIG", "/etc/zanity-alerter/config.json")
STATE_PATH = os.environ.get("ALERTER_STATE", "/var/lib/zanity-alerter/state.json")

METRIC_RE = re.compile(r"^(\w+)\{(.*)\}\s+([0-9.eE+-]+)$")
LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def log(msg):
    print("%s %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        log("не смог прочитать %s: %s" % (path, e))
        return default


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def env_value(path, key):
    """Достаём одну переменную из .env, не выполняя файл: он не парсится шеллом."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except Exception as e:
        log("не смог прочитать %s: %s" % (path, e))
    return None


# --------------------------------------------------------------------------- telegram

def _send_error(e, what=""):
    # текст исключения subprocess (TimeoutExpired) содержит cmd с токеном бота в URL — только тип
    return "ошибка отправки %s(%s)" % (what, type(e).__name__)


def tg_target(cfg, chat=None, thread=True):
    """(токен, чат, прокси в socks5h, thread_id); чат по умолчанию из .env бота, thread — из конфига."""
    token = env_value(cfg["bot_env"], "BOT_TOKEN")
    chat = chat or env_value(cfg["bot_env"], cfg.get("chat_key", "ADMIN_NOTIFICATIONS_CHAT_ID"))
    proxy = env_value(cfg["bot_env"], "PROXY_URL")
    if proxy and proxy.startswith("socks5://"):
        # socks5h: имя резолвит выход. С socks5 curl резолвит сам, а у eth0 node-b есть IPv6 без маршрута
        # (dhcp6) — уходит AAAA, и туннель отвечает «network unreachable» (сводка 2026-10-07 не дошла).
        proxy = "socks5h://" + proxy[len("socks5://"):]
    thread_id = cfg.get("message_thread_id") if thread else None
    return token, chat, proxy, (str(thread_id) if thread_id else None)


def send_telegram(cfg, text, chat=None, thread=True):
    token, chat, proxy, thread_id = tg_target(cfg, chat, thread)
    if not token or not chat:
        log("нет токена или чата — сообщение не отправлено")
        return False
    cmd = ["curl", "-s", "-m", "25", "-o", "/dev/null", "-w", "%{http_code}"]
    if proxy:
        cmd += ["--proxy", proxy]
    cmd += [
        "https://api.telegram.org/bot%s/sendMessage" % token,
        "--data-urlencode", "chat_id=%s" % chat,
        "--data-urlencode", "text=%s" % text,
        "--data-urlencode", "parse_mode=HTML",
        "--data-urlencode", "disable_web_page_preview=true",
    ]
    if thread_id:
        cmd += ["--data-urlencode", "message_thread_id=%s" % thread_id]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=40).stdout.strip()
    except Exception as e:
        log(_send_error(e))
        return False
    if out != "200":
        log("телеграм ответил %s" % out)
        return False
    return True


def album_cmd(token, chat, proxy, thread_id, caption, paths):
    media = []
    for i in range(len(paths)):
        item = {"type": "photo", "media": "attach://c%d" % i}
        if i == 0:
            item["caption"] = caption
            item["parse_mode"] = "HTML"
        media.append(item)
    cmd = ["curl", "-s", "-m", "60", "-o", "/dev/null", "-w", "%{http_code}"]
    if proxy:
        cmd += ["--proxy", proxy]
    cmd += [
        "https://api.telegram.org/bot%s/sendMediaGroup" % token,
        "--form-string", "chat_id=%s" % chat,
        "--form-string", "media=%s" % json.dumps(media, ensure_ascii=False),
    ]
    if thread_id:
        cmd += ["--form-string", "message_thread_id=%s" % thread_id]
    for i, p in enumerate(paths):
        cmd += ["-F", "c%d=@%s" % (i, p)]
    return cmd


def send_album(cfg, pngs, caption, chat=None, thread=True):
    token, chat, proxy, thread_id = tg_target(cfg, chat, thread)
    if not token or not chat:
        log("нет токена или чата — альбом не отправлен")
        return False
    try:
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i, data in enumerate(pngs):
                path = os.path.join(d, "card%d.png" % i)
                with open(path, "wb") as f:
                    f.write(data)
                paths.append(path)
            out = subprocess.run(album_cmd(token, chat, proxy, thread_id, caption, paths),
                                 capture_output=True, text=True, timeout=90).stdout.strip()
    except Exception as e:
        log(_send_error(e, "альбома "))
        return False
    if out != "200":
        log("телеграм ответил на альбом %s" % out)
        return False
    return True


def _render_cards(models):
    import cards  # Pillow может отсутствовать на проде: тогда ImportError уйдёт в текстовый запасной путь
    return cards.render_all(models)


DEMO_MARKS = {(True, False): "демо: данные из фикстуры", (False, True): "демо: история из фикстуры",
              (True, True): "демо: данные и история из фикстуры"}


def mark_demo(header, data=False, history=False):
    mark = DEMO_MARKS.get((bool(data), bool(history)))
    if not mark:
        return header
    first, sep, rest = header.partition("\n")
    return first + "\n<i>" + mark + "</i>" + (sep + rest if sep else "")


def send_summary(cfg, summary, state, now, chat=None, thread=True, render=None, demo=None):
    try:
        header, details = caption_parts(summary, state, now)
        if demo:
            header = mark_demo(header, *demo)
        caption, extra = compose_caption(header, details)
    except Exception as e:
        log("не смог собрать подпись сводки: %r" % e)
        return send_telegram(cfg, "<b>Мониторинг · сутки</b>\nСводку собрать не удалось: " + esc(repr(e)[:300]),
                             chat=chat, thread=thread)
    try:
        pngs = (render or _render_cards)(build_models(summary, state, now))
    except Exception as e:
        log("рендер карточек не удался, шлю текстом: %r" % e)
        pngs = None
    if pngs and send_album(cfg, pngs, caption, chat=chat, thread=thread):
        if extra and not send_telegram(cfg, extra, chat=chat, thread=thread):
            log("альбом ушёл, а сообщение «Подробности» нет")
        return True
    return send_telegram(cfg, fallback_text(header, details), chat=chat, thread=thread)


# --------------------------------------------------------------------------- сбор данных

def docker_ip(name):
    try:
        out = subprocess.run(
            ["docker", "inspect", name, "--format",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}"],
            capture_output=True, text=True, timeout=20).stdout.split()
        return out[0] if out else None
    except Exception:
        return None


def scrape(source):
    """Возвращает {(name, address): {"status": 0/1, "latency": ms}} или None при недоступности."""
    host = source.get("host")
    if not host and source.get("container"):
        host = docker_ip(source["container"])
    if not host:
        return None
    url = "http://%s:%s/metrics" % (host, source.get("port", 2112))
    cmd = ["curl", "-s", "-m", "20", "--noproxy", "*"]
    if source.get("username"):
        cmd += ["-u", "%s:%s" % (source["username"], source.get("password", ""))]
    cmd += [url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        log("scrape %s: %s" % (source["name"], e))
        return None
    if r.returncode != 0 or not r.stdout:
        return None

    out = {}
    for line in r.stdout.splitlines():
        m = METRIC_RE.match(line.strip())
        if not m:
            continue
        metric, labels_raw, value = m.groups()
        if metric not in ("xray_proxy_status", "xray_proxy_latency_ms"):
            continue
        labels = dict(LABEL_RE.findall(labels_raw))
        key = (labels.get("name", "?"), labels.get("address", "?"))
        entry = out.setdefault(key, {})
        entry["status" if metric == "xray_proxy_status" else "latency"] = float(value)
    return out or None


CHECKER_LINE_RE = re.compile(r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d (\[ERROR\] )?(.+?) \| (.*)$")


def entry_label(addr, labels):
    """node-e.example.net:3442 → «node-a (node-e.example.net:3442)»: в подписке старые имена, а сервер другой."""
    host = addr.rsplit(":", 1)[0]
    name = (labels or {}).get(host)
    return "%s (%s)" % (name, addr) if name else addr


def parse_checker_errors(text):
    """{локация: текст последней ошибки}; успешный замер после ошибки её снимает."""
    errors = {}
    for line in text.splitlines():
        m = CHECKER_LINE_RE.match(line.strip())
        if not m:
            continue
        is_error, name, rest = m.groups()
        if is_error:
            errors[name] = rest
        elif rest.startswith("Success"):
            errors.pop(name, None)
    return errors


def checker_problem(line, timeout, need):
    """Человеческая причина неудачи по строке лога чекера. Чистая функция — test_checker_text.py."""
    within = ("за %d с" % timeout) if timeout else "за отведённое время"
    if not line:
        return "не отдал %d КБ %s (причина в логе чекера не найдена)" % ((need or 0) // 1024, within)
    m = re.search(r"Download error after (\d+) bytes", line)
    if m and need:
        return "отдал %d из %d КБ %s — режут полосу" % (int(m.group(1)) // 1024, need // 1024, within)
    if "awaiting headers" in line:
        return "не ответил %s — нет даже первого байта (не полоса, а задержка или обрыв)" % within
    if line.rstrip().endswith("EOF"):
        return "соединение оборвалось (EOF)"
    if "connection refused" in line:
        return "соединение отклонено (connection refused)"
    if "connection reset" in line:
        return "соединение сброшено (connection reset)"
    err = line.split('": ', 1)[-1].strip()
    return "ошибка: " + (err[:117] + "…" if len(err) > 118 else err)


def checker_errors(source):
    """Последние ошибки чекера из его лога; None, если лог не прочитать."""
    container = source.get("log_container")
    if not container:
        return None
    try:
        r = subprocess.run(["docker", "logs", "--since", source.get("log_since", "40m"), container],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:
        log("лог %s: %s" % (container, e))
        return None
    return parse_checker_errors(r.stdout + r.stderr)


def haproxy_backends(cfg):
    """Возвращает {'be_socks/exit-1': 'UP', ...} или None, если сокет недоступен."""
    sock_path = cfg.get("haproxy_socket")
    if not sock_path or not os.path.exists(sock_path):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(sock_path)
        s.sendall(b"show stat\n")
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
        s.close()
        raw = b"".join(chunks).decode("utf-8", "replace")
    except Exception as e:
        log("haproxy: %s" % e)
        return None

    out = {}
    for line in raw.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split(",")
        if len(f) < 18:
            continue
        pxname, svname, status = f[0], f[1], f[17]
        if svname in ("FRONTEND", "BACKEND") or pxname not in cfg.get("haproxy_pools", []):
            continue
        out["%s/%s" % (pxname, svname)] = status
    return out or None


# --------------------------------------------------------------------------- квоты трафика

def fetch_counters(node, cfg):
    """Ходит на ноду ключом с forced command: оттуда возвращаются только счётчики."""
    cmd = ["ssh", "-i", cfg["quota_key"], "-p", str(node.get("port", 22)),
           "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
           "-o", "StrictHostKeyChecking=yes", "-T",
           "root@%s" % node["host"]]
    # одна повторная попытка: анти-DDoS хостера (EXIT-5, 2026-11-20) сбрасывает первое соединение после паузы
    for attempt in range(2):
        if attempt:
            time.sleep(2)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        except Exception as e:
            log("счётчики %s: %s" % (node["name"], e))
            continue
        if r.returncode == 0:
            data = _parse_counters(r.stdout)
            if data:
                return data
    return None


def _parse_counters(stdout):
    data = {"ifaces": {}}
    for line in stdout.splitlines():
        p = line.split()
        if len(p) == 2 and p[0] == "uptime":
            data["uptime"] = int(p[1])
        elif len(p) == 5 and p[1] == "rx" and p[3] == "tx":
            data["ifaces"][p[0]] = [int(p[2]), int(p[4])]
    return data if data["ifaces"] else None


def period_key(cycle_day):
    """Идентификатор расчётного периода: он начинается cycle_day числа."""
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    if now.day < cycle_day:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return "%04d-%02d-%02d" % (year, month, cycle_day)


GIB = 1073741824


def quota_cycle(cfg, state, events, summary):
    nodes = cfg.get("quota_nodes") or []
    if not nodes or not cfg.get("quota_key"):
        return
    now = time.time()
    if now - state.get("quota_last_poll", 0) < cfg.get("quota_poll_seconds", 600):
        return
    state["quota_last_poll"] = now
    store = state.setdefault("quota", {})

    for node in nodes:
        name = node["name"]
        cur = fetch_counters(node, cfg)
        evaluate("quota_src:%s" % name, cur is not None,
                 "нода не отдаёт счётчики", state, cfg, events)
        if not cur:
            continue

        st = store.setdefault(name, {"used": 0, "period": None, "last": None, "notified": []})
        period = period_key(node.get("cycle_day", 1))
        if st["period"] != period:
            st.update({"period": period, "used": 0, "notified": []})

        prev = st.get("last")
        if prev:
            # перезагрузка или переполнение счётчика: текущее значение и есть прирост
            rebooted = cur.get("uptime", 0) < prev.get("uptime", 0)
            mode = node.get("count_mode", "rxtx")
            delta = 0
            for ifc, (rx, tx) in cur["ifaces"].items():
                prx, ptx = prev["ifaces"].get(ifc, [0, 0])
                d_rx = rx if (rebooted or rx < prx) else rx - prx
                d_tx = tx if (rebooted or tx < ptx) else tx - ptx
                delta += d_rx + d_tx if mode == "rxtx" else (
                    max(d_rx, d_tx) if mode == "max" else d_tx)
            st["used"] += delta
        st["last"] = cur

        limit = node.get("limit_gib")
        used_gib = st["used"] / GIB
        summary.setdefault("quota", {})[name] = (used_gib, limit)
        if not limit:
            continue
        pct = used_gib / limit * 100
        for th in sorted(node.get("warn_percent", [80, 95, 100])):
            if pct >= th and th not in st["notified"]:
                st["notified"].append(th)
                events.append(("warn" if th < 100 else "down", "quota:%s" % name,
                               "израсходовано %.0f%% (%.0f из %d ГиБ), период с %s"
                               % (pct, used_gib, limit, st["period"])))


# --------------------------------------------------------------------------- регион YouTube (реклама)

GL_RE = re.compile(r'"GL":"([A-Z]{2})"')


def yt_region_targets(ports, skip_pattern=None):
    """Локации для проверки GL: без «👇 … 👇» (заголовки дублируют обычные локации) и без
    подходящих под yt_region.skip_pattern — выделенные «(личный)» не основные выходы, реклама там не тревога."""
    return [(p, n) for p, n in ports
            if "\U0001f447" not in n and not (skip_pattern and re.search(skip_pattern, n))]


def yt_region_cycle(cfg, state, events, summary):
    """Раз в poll_seconds смотрит, какой страной YouTube видит каждую локацию.

    Рекламы нет, пока YouTube считает пользователя российским (GL=RU): на локациях через node-e
    YouTube идёт напрямую с российского IP, а exit-1/EXIT-5 Google просто числит российскими —
    это держится только на его геобазе. Не загрузилось — не неудача: доступность ловят чекеры.
    """
    yt = cfg.get("yt_region")
    if not yt:
        return
    now = time.time()
    if now - state.get("yt_last_poll", 0) < yt.get("poll_seconds", 10800):
        summary["yt"] = state.get("yt_last", {})
        return
    state["yt_last_poll"] = now
    container = yt.get("container", cfg["sources"]["ip"]["container"])
    try:
        raw = subprocess.run(["docker", "exec", container, "cat", "/app/xray_config.json"],
                             capture_output=True, text=True, timeout=30).stdout
        ports = [(i["port"], i["tag"].rsplit("_vless", 1)[0]) for i in json.loads(raw)["inbounds"]]
    except Exception as e:
        log("yt: не прочитал конфиг чекера: %r" % e)
        return
    expected = yt.get("expected", "RU")
    targets = yt_region_targets(ports, yt.get("skip_pattern"))
    for _, name in set(ports) - set(targets):
        # тревога, открытая до исключения, иначе висела бы вечно
        state["checks"].pop("yt:%s" % name, None)
    seen = {}
    for port, name in targets:
        cmd = ("curl -s -m 15 -H 'Accept-Language: en' -x socks5h://127.0.0.1:%d https://www.youtube.com/"
               " | grep -oE '\"GL\":\"[A-Z]{2}\"' | head -1" % port)
        try:
            out = subprocess.run(["docker", "exec", container, "sh", "-c", cmd],
                                 capture_output=True, text=True, timeout=40).stdout
        except Exception:
            out = ""
        m = GL_RE.search(out)
        if not m:
            continue
        gl = seen[name] = m.group(1)
        detail = ("YouTube видит страну %s (нужна %s) — будет реклама" % (gl, expected)
                  if gl != expected else "YouTube снова видит %s" % expected)
        evaluate("yt:%s" % name, gl == expected, detail, state, cfg, events,
                 threshold=yt.get("failures_before_alert", 2))
    summary["yt"] = state["yt_last"] = seen
    log("yt: %s" % ", ".join("%s=%s" % kv for kv in seen.items()))


YT_PLAYER_RE = re.compile(r"/s/player/[A-Za-z0-9_-]+/[A-Za-z0-9_./-]*?/base\.js")


def yt_speed_targets(locations, skip, no_yt=()):
    """Российские локации — те, чей адрес в exit_check_skip_addresses, кроме yt_speed_skip_addresses
    (там YouTube не обещаем: прямой выход с node-b, где его режет хостинг). Чистая функция."""
    return sorted({n for (n, a) in locations if a in skip and a not in no_yt and "\U0001f447" not in n})


def yt_speed_problem(code, size, need):
    """Что не так с загрузкой с YouTube, или None. Чистая функция — покрыта test_yt_speed.py."""
    if code in ("", "000"):
        return "YouTube не открылся"
    if code not in ("200", "206"):
        return "YouTube ответил %s" % code
    if size < need:
        return "YouTube отдал %d из %d КБ за отведённое время — режут полосу" % (size // 1024, need // 1024)
    return None


def yt_speed_log_line(targets, speeds):
    """Строка лога за цикл; пустой список целей — не сбой, а «проверять нечего»."""
    if not targets:
        return "yt_speed: нет российских локаций с YouTube — проверять нечего"
    return "yt_speed: %s" % (", ".join("%s=%s" % kv for kv in speeds.items()) or "нет удачных замеров")


def yt_speed_cycle(cfg, state, events, summary):
    """Раз в poll_seconds: на российских локациях YouTube открывается и не порезан.

    Заблокированный в РФ зонд выхода им недоступен (exit_check_skip_addresses), а держат их ради
    YouTube без рекламы. ТСПУ режет YouTube по SNI, поэтому через каждую локацию качаем с
    www.youtube.com кусок скрипта плеера: не уложился в timeout — полосу режут. Сам ролик
    (googlevideo) так не взять: API плеера с IP датацентров просит войти в аккаунт.
    """
    ys = cfg.get("yt_speed")
    locs = summary.get("locations")
    if not ys or not locs:
        return
    now = time.time()
    if now - state.get("yt_speed_last_poll", 0) < ys.get("poll_seconds", 600):
        summary["yt_speed"] = state.get("yt_speed_last", {})
        return
    state["yt_speed_last_poll"] = now
    container = ys.get("container", cfg["sources"]["ip"]["container"])
    try:
        raw = subprocess.run(["docker", "exec", container, "cat", "/app/xray_config.json"],
                             capture_output=True, text=True, timeout=30).stdout
        ports = {i["tag"].rsplit("_vless", 1)[0]: i["port"] for i in json.loads(raw)["inbounds"]}
    except Exception as e:
        log("yt_speed: не прочитал конфиг чекера: %r" % e)
        return
    need = ys.get("bytes", 1048576)
    timeout = ys.get("timeout_seconds", 5)
    threshold = ys.get("failures_before_alert", 2)
    speeds = {}
    targets = [n for n in yt_speed_targets(locs, set(cfg.get("exit_check_skip_addresses", [])),
                                           set(cfg.get("yt_speed_skip_addresses", []))) if n in ports]
    for name in targets:
        if name not in ports:
            continue
        proxy = "socks5h://127.0.0.1:%d" % ports[name]
        try:
            # путь к плееру меняется с каждой выкладкой YouTube — берём со страницы через ту же локацию
            page = subprocess.run(["docker", "exec", container, "curl", "-s", "-m", "15", "-H", "Accept-Language: en",
                                   "-x", proxy, "https://www.youtube.com/"],
                                  capture_output=True, text=True, timeout=30).stdout
        except Exception:
            page = ""
        m = YT_PLAYER_RE.search(page)
        if not m:
            if len(page) > 100000:
                # страница пришла, а плеера в ней нет — сломалась сама проба, а не локация
                evaluate("source:yt_speed", False, "на youtube.com не нашёлся путь к плееру", state, cfg, events)
                return
            evaluate("ytspeed:%s" % name, False, "YouTube не открылся", state, cfg, events, threshold=threshold)
            continue
        evaluate("source:yt_speed", True, "", state, cfg, events)
        try:
            out = subprocess.run(["docker", "exec", container, "curl", "-s", "-o", "/dev/null", "-m", str(timeout),
                                  "-r", "0-%d" % (need - 1), "-x", proxy,
                                  "-w", "%{http_code} %{size_download} %{time_total}",
                                  "https://www.youtube.com" + m.group(0)],
                                 capture_output=True, text=True, timeout=timeout + 15).stdout.split()
        except Exception:
            out = []
        code, size, took = out if len(out) == 3 else ("", "0", "0")
        size, took = int(float(size)), float(took)
        problem = yt_speed_problem(code, size, need)
        if problem is None and took:
            speeds[name] = round(size * 8 / took / 1e6)
        evaluate("ytspeed:%s" % name, problem is None, problem or "YouTube снова качает", state, cfg, events,
                 threshold=threshold)
    summary["yt_speed"] = state["yt_speed_last"] = speeds
    log(yt_speed_log_line(targets, speeds))


def mask_problem(ips, expected_ip, not_after, now, min_days, cert_matches=True):
    """Что не так с маскировкой selfsteal-домена, или None. Чистая функция — покрыта test_mask.py."""
    if not ips:
        return "домен не резолвится"
    if expected_ip not in ips:
        return "домен ведёт на %s, а не на %s" % (", ".join(ips), expected_ip)
    if not_after is None:
        return "сертификат не прочитан"
    if not cert_matches:
        return "сертификат не на домен — Reality отдаёт чужой сайт?"
    days = (not_after - now).days
    if days < min_days:
        return "сертификат истекает через %d дн. — продление не прошло?" % days
    return None


def mask_cycle(cfg, state, events, summary):
    """Раз в poll_seconds: selfsteal-домен ведёт на ноду и её Reality отдаёт живой сертификат.

    Домен — чужой бесплатный поддомен (FreeDNS), его могут закрыть в любой момент. Клиентам это
    не мешает (address у них другой), но маскировка тихо деградирует — об этом и тревога.
    """
    mk = cfg.get("selfsteal_mask")
    if not mk:
        return
    now = time.time()
    if now - state.get("mask_last_poll", 0) < mk.get("poll_seconds", 21600):
        return
    state["mask_last_poll"] = now
    for c in mk.get("checks", []):
        try:
            ips = sorted({a[4][0] for a in socket.getaddrinfo(c["domain"], 443, socket.AF_INET)})
        except OSError:
            ips = []
        host, port = c["probe"].rsplit(":", 1)
        not_after = None
        cert_matches = True
        try:
            pem = subprocess.run(["openssl", "s_client", "-connect", "%s:%s" % (host, port),
                                  "-servername", c["domain"]], input="", capture_output=True,
                                 text=True, timeout=20).stdout
            end = subprocess.run(["openssl", "x509", "-noout", "-enddate"], input=pem,
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            if end.startswith("notAfter="):
                not_after = datetime.strptime(end[9:], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                chk = subprocess.run(["openssl", "x509", "-noout", "-checkhost", c["domain"]], input=pem,
                                     capture_output=True, text=True, timeout=10).stdout
                cert_matches = "does match certificate" in chk and "does NOT match" not in chk
        except Exception as e:
            log("mask: проба %s упала: %r" % (c["probe"], e))
        problem = mask_problem(ips, c["expected_ip"], not_after, datetime.now(timezone.utc), c.get("min_days", 20),
                               cert_matches)
        evaluate("mask:%s" % c["name"], problem is None,
                 problem or "%s ведёт на ноду, сертификат в порядке" % c["domain"],
                 state, cfg, events, threshold=mk.get("failures_before_alert", 2))
        log("mask: %s %s" % (c["name"], problem or "ok"))


def cdn_problem(topo_ips, probes, now, min_days):
    """Что не так с доменом подписки за Yandex CDN, или None. Чистая функция — покрыта test_cdn.py.

    probes — {IP домена: (HTTP-код, notAfter сертификата)}. Совпадение с топологией не требуется:
    она прыгает между эджами пула (198.51.100.1 ↔ .2), а любой эдж отдаёт ресурс по SNI.
    """
    if not probes:
        return "домен не резолвится"
    hint = " — поменять A-запись на эдж из топологии: %s" % ", ".join(topo_ips) if topo_ips else ""
    for ip, (code, _) in sorted(probes.items()):
        if code != 200:
            return "подписка через эдж %s отвечает %s%s" % (ip, code or "таймаутом", hint)
    for ip, (_, not_after) in sorted(probes.items()):
        if not_after is None:
            return "сертификат эджа %s не прочитан" % ip
        days = (not_after - now).days
        if days < min_days:
            return "сертификат CDN истекает через %d дн. — продлить вручную (HTTP-проверка)" % days
    return None


def _ipv4(name):
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(name, 443, socket.AF_INET)})
    except OSError:
        return []


def cdn_cycle(cfg, state, events, summary):
    """Раз в poll_seconds: каждый адрес домена подписки отдаёт её через эдж Yandex CDN.

    У sub.example.org (FreeDNS, CNAME запрещён) A-запись прибита к IP эджа. Тревога — когда этот
    эдж перестал отдавать подписку; расхождение с топологией только пишется в лог.
    """
    cc = cfg.get("cdn_subscription")
    if not cc:
        return
    now = time.time()
    if now - state.get("cdn_last_poll", 0) < cc.get("poll_seconds", 600):
        return
    state["cdn_last_poll"] = now
    topo = _ipv4(cc["topology"])
    for c in cc.get("checks", []):
        d = c["domain"]
        probes = {}
        for ip in _ipv4(d):
            code, not_after = 0, None
            try:
                out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "20", "-w", "%{http_code}",
                                      "-A", "Happ/4.12.0", "--resolve", "%s:443:%s" % (d, ip),
                                      "https://%s%s" % (d, cc["path"])],
                                     capture_output=True, text=True, timeout=30).stdout
                code = int(out or 0)
                pem = subprocess.run(["openssl", "s_client", "-connect", "%s:443" % ip, "-servername", d],
                                     input="", capture_output=True, text=True, timeout=20).stdout
                end = subprocess.run(["openssl", "x509", "-noout", "-enddate"], input=pem,
                                     capture_output=True, text=True, timeout=10).stdout.strip()
                if end.startswith("notAfter="):
                    not_after = datetime.strptime(end[9:], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            except Exception as e:
                log("cdn: проба %s через %s упала: %r" % (d, ip, e))
            probes[ip] = (code, not_after)
        problem = cdn_problem(topo, probes, datetime.now(timezone.utc), c.get("min_days", 20))
        evaluate("cdn:%s" % d, problem is None,
                 problem or "%s отдаёт подписку через эдж CDN" % d,
                 state, cfg, events, threshold=cc.get("failures_before_alert", 2))
        drift = "" if not topo or set(probes) & set(topo) else " (A %s, топология %s)" % (
            ", ".join(sorted(probes)), ", ".join(topo))
        log("cdn: %s %s%s" % (d, problem or "ok", drift))


CURL_ERRORS = {6: "имя не резолвится", 7: "соединение отклонено", 28: "не ответил за отведённое время",
               35: "TLS не установился", 52: "пустой ответ", 56: "обрыв соединения",
               60: "сертификат не прошёл проверку", 97: "socks-прокси не соединил"}


def web_problem(curl_exit, code, body, spec):
    """Что не так с ответом web-проверки, или None. Чистая функция — покрыта test_web.py."""
    if curl_exit:
        return CURL_ERRORS.get(curl_exit, "curl завершился с кодом %d" % curl_exit)
    want = spec.get("expect_status", 200)
    if code != want:
        return "ответил %s вместо %s" % (code, want)
    marker = spec.get("contains")
    if marker and marker not in body:
        return "в ответе нет «%s»" % marker
    return None


def web_url(spec, cfg):
    """URL проверки; у пути вебхука база берётся из WEBHOOK_URL бота, чтобы проверка шла за переездом реле."""
    if spec.get("webhook_from_env"):
        base = env_value(cfg["bot_env"], spec["webhook_from_env"])
        if not base:
            return None
        u = urllib.parse.urlsplit(base.split("#")[0].strip().strip('"'))
        return "%s://%s%s" % (u.scheme, u.netloc, spec.get("path", "/"))
    return spec["url"]


def web_cycle(cfg, state, events, summary):
    """Кабинет и лендинг из РФ (с ctl-host через front-1) и путь вебхука Telegram через socks бота.

    Внешний сторож на exit-1 видит те же адреса снаружи РФ, но не видит бана front-1 из РФ, а при смерти
    exit-1 молчит сам — хотя exit-1 стоит в цепочке вебхука (exit-4:88 → exit-1:8443 → ctl-host).
    """
    wc = cfg.get("web_checks")
    if not wc:
        return
    now = time.time()
    if now - state.get("web_last_poll", 0) < wc.get("poll_seconds", 0):
        return
    state["web_last_poll"] = now
    proxy = tg_target(cfg)[2]
    for spec in wc.get("checks", []):
        url = web_url(spec, cfg)
        if not url:
            log("web: %s — нет %s в .env бота" % (spec["label"], spec["webhook_from_env"]))
            continue
        cmd = ["curl", "-s", "-m", str(wc.get("timeout_seconds", 15)), "-A", "zanity-alerter",
               "-w", "\n%{http_code}"]
        if spec.get("proxy") and proxy:
            cmd += ["--proxy", proxy]
        try:
            out = subprocess.run(cmd + [url], capture_output=True, timeout=40)
            body, _, code = out.stdout.decode("utf-8", "replace").rpartition("\n")
            problem = web_problem(out.returncode, int(code or 0), body, spec)
        except Exception as e:
            problem = "проба упала: %s" % type(e).__name__
        evaluate("web:%s" % spec["label"], problem is None, problem or "открывается",
                 state, cfg, events, threshold=wc.get("failures_before_alert", 3))
        log("web: %s %s" % (spec["label"], problem or "ok"))


def cdn_via_targets(ports, names):
    """[(port, name)] локаций чекера из via_locations, в порядке конфига. Чистая функция."""
    by_name = {n: p for p, n in ports}
    return [(by_name[n], n) for n in names if n in by_name]


def cdn_via_cmd(targets, domains, path, timeout):
    """Одна оболочка в контейнере чекера, все curl разом: молчащий эдж стоит timeout, а не N×timeout."""
    jobs = ["(c=$(curl -s -o /dev/null -m %d -w '%%{http_code}' -A Happ/4.12.0 -x socks5h://127.0.0.1:%d"
            " https://%s%s); echo \"%d %s $c\") &" % (timeout, port, d, path, port, d)
            for port, _ in targets for d in domains]
    return " ".join(jobs) + " wait"


def parse_cdn_via(out):
    """{(port, domain): код}; 000 и мусор — 0. Чистая функция."""
    res = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0].isdigit():
            res[(int(parts[0]), parts[1])] = int(parts[2]) if parts[2].isdigit() else 0
    return res


def cdn_via_cycle(cfg, cc, state, events, now):
    """Раз в via_poll_seconds: подписка за CDN отдаётся через локации из via_locations.

    Прямая проверка ходит с ctl-host (РФ). 18.11 эдж часами молчал для зарубежных выходов
    (exit-1/exit-2/exit-3/exit-6), а с российских адресов отвечал — обновление с включённым VPN не шло, а
    тревоги не было. Здесь тот же запрос идёт через socks-порт чекера, то есть с IP выхода.
    """
    names = cc.get("via_locations") or []
    if not names or now - state.get("cdn_via_last_poll", 0) < cc.get("via_poll_seconds", 900):
        return
    state["cdn_via_last_poll"] = now
    container = cc.get("via_container", cfg["sources"]["ip"]["container"])
    try:
        raw = subprocess.run(["docker", "exec", container, "cat", "/app/xray_config.json"],
                             capture_output=True, text=True, timeout=30).stdout
        ports = [(i["port"], i["tag"].rsplit("_vless", 1)[0]) for i in json.loads(raw)["inbounds"]]
    except Exception as e:
        log("cdn_via: не прочитал конфиг чекера: %r" % e)
        return
    targets = cdn_via_targets(ports, names)
    missing = sorted(set(names) - {n for _, n in targets})
    if missing:
        log("cdn_via: в чекере нет локаций %s" % ", ".join(missing))
    domains = [c["domain"] for c in cc.get("checks", [])]
    timeout = cc.get("via_timeout_seconds", 15)
    try:
        out = subprocess.run(["docker", "exec", container, "sh", "-c",
                              cdn_via_cmd(targets, domains, cc["path"], timeout)],
                             capture_output=True, text=True, timeout=timeout + 30).stdout
    except Exception as e:
        log("cdn_via: проба упала: %r" % e)
        return
    codes = parse_cdn_via(out)
    if targets and not codes:
        log("cdn_via: проба ничего не вернула — пропускаю цикл")  # чекер лёг: не повод для N тревог
        return
    keep = set()
    for port, name in targets:
        for d in domains:
            key = "cdn_via:%s · %s" % (name, d)
            keep.add(key)
            code = codes.get((port, d), 0)
            evaluate(key, code == 200,
                     "подписка через эту локацию отдаётся" if code == 200 else
                     "эдж CDN не отдаёт подписку — с включённым VPN через этот выход она не обновится",
                     state, cfg, events, threshold=cc.get("failures_before_alert", 2))
    for key in [k for k in state["checks"] if k.startswith("cdn_via:") and k not in keep]:
        state["checks"].pop(key)  # локацию убрали из конфига — тревога не должна висеть вечно
    log("cdn_via: %s" % ", ".join("%s/%s=%s" % (p, d, c) for (p, d), c in sorted(codes.items())))


# --------------------------------------------------------------------------- логика тревог

def _tracked(key):
    """Историю ведём для локаций и выходов, кроме строк-разделителей."""
    return key.startswith(("loc:", "exit:")) and not is_divider(key_name(key))


def is_new_sample(st, sample, source, cfg, now):
    period = source.get("interval_seconds", 300) + cfg.get("interval_seconds", 120) / 2
    return sample != st.get("sample") or now - st.get("counted_at", 0) >= period


def evaluate(key, ok, detail, state, cfg, events, threshold=None, now=None):
    """Гистерезис: тревога только после N неудач подряд, восстановление — сразу."""
    st = state["checks"].setdefault(key, {"fails": 0, "alerted": False})
    if threshold is None:
        threshold = cfg.get("failures_before_alert", 3)
    if ok:
        if st["alerted"]:
            events.append(("up", key, detail))
            st["alerted"] = False
        elif st["fails"]:
            # одиночный сбой, до тревоги не дошло — запоминаем для суточной сводки
            blips = state.setdefault("blips", {})
            blips[key] = blips.get(key, 0) + 1
        st["fails"] = 0
    else:
        st["fails"] += 1
        if _tracked(key):
            history.add_fail(state, now or time.time(), key)
        if st["fails"] >= threshold and not st["alerted"]:
            events.append(("down", key, detail))
            st["alerted"] = True
            st["alerted_at"] = time.time()
    st["last_detail"] = detail


def evaluate_sample(key, v, detail, source, state, cfg, events, now=None):
    """То же, что evaluate, но неудачи считаются по замерам чекера, а не по опросам.

    Алертер опрашивает раз в interval_seconds (120 с), а чекер обновляет метрику раз в
    interval_seconds источника (300/900 с), поэтому один и тот же неудачный замер
    читается несколько раз подряд. Новым замер считаем, если пара (status, latency)
    изменилась или прошёл полный период чекера — иначе стабильно лежащая локация
    (status=0, latency=0 каждый раз) не набрала бы второй неудачи никогда.
    """
    ok = v.get("status", 0) >= 1
    sample = [v.get("status", 0), v.get("latency", 0)]
    st = state["checks"].setdefault(key, {"fails": 0, "alerted": False})
    now = now or time.time()
    if ok:
        evaluate(key, True, detail, state, cfg, events)
    else:
        if is_new_sample(st, sample, source, cfg, now):
            st["counted_at"] = now
            evaluate(key, False, detail, state, cfg, events,
                     threshold=source.get("failures_before_alert"), now=now)
    st["sample"] = sample


def run_cycle(cfg, state):
    events = []
    summary = {}
    now = time.time()

    # --- локации: жива ли вообще
    labels = cfg.get("entry_labels")
    ip_src = cfg["sources"]["ip"]
    ip_data = scrape(ip_src)
    evaluate("source:ip", ip_data is not None, "чекер %s недоступен" % ip_src["name"], state, cfg, events)
    if ip_data:
        summary["locations"] = ip_data
        down = [n for (n, a), v in ip_data.items() if v.get("status", 0) < 1]
        mass = len(down) >= max(2, int(len(ip_data) * cfg.get("mass_outage_ratio", 0.5)))
        ip_errors = checker_errors(ip_src) if down else None
        for (name, addr), v in ip_data.items():
            ok = v.get("status", 0) >= 1
            # при массовом падении не спамим по каждой локации — отдельное сообщение ниже
            if mass and not ok:
                st = state["checks"].setdefault("loc:%s" % name, {"fails": 0, "alerted": False})
                st["fails"] += 1
                sample = [v.get("status", 0), v.get("latency", 0)]
                # новизну для истории ведём отдельно: sample/counted_at трогать нельзя,
                # иначе сдвинется тревога по локации, которая лежит и после массового падения
                seen = {"sample": st.get("hist_sample", st.get("sample")),
                        "counted_at": st.get("hist_at", st.get("counted_at", 0))}
                if is_new_sample(seen, sample, ip_src, cfg, now):
                    st["hist_at"] = now
                    if _tracked("loc:%s" % name):
                        history.add_fail(state, now, "loc:%s" % name)
                st["hist_sample"] = sample
                continue
            detail = entry_label(addr, labels)
            if not ok and ip_errors is not None:
                detail += " — " + checker_problem(ip_errors.get(name), ip_src.get("timeout_seconds"), None)
            evaluate_sample("loc:%s" % name, v, detail, ip_src, state, cfg, events, now)
            for f in ("hist_sample", "hist_at"):
                state["checks"]["loc:%s" % name].pop(f, None)
        evaluate("mass_outage", not mass, "лежит %d из %d локаций" % (len(down), len(ip_data)),
                 state, cfg, events)
        mass_alerted = state["checks"]["mass_outage"]["alerted"]
        for (name, addr), v in ip_data.items():
            key = "loc:%s" % name
            if not _tracked(key):
                continue
            lying = mass and v.get("status", 0) < 1
            alerted = state["checks"][key]["alerted"] or (lying and mass_alerted)
            history.touch(state, now, key, alerted)

    # --- выход за границу: жив ли и не порезан ли
    ex_src = cfg["sources"].get("exit")
    if ex_src:
        ex_data = scrape(ex_src)
        evaluate("source:exit", ex_data is not None, "чекер %s недоступен" % ex_src["name"],
                 state, cfg, events)
        if ex_data:
            skip = set(cfg.get("exit_check_skip_addresses", []))
            summary["exits"] = {k: v for k, v in ex_data.items() if k[1] not in skip}
            # latency у download-метода — это время до первого байта, а не скорость,
            # поэтому троттлинг ловится не порогом по мс, а тем, что чекер не успел
            # вычитать 1 МБ за PROXY_DOWNLOAD_TIMEOUT и вернул status=0. Чем именно
            # кончилась проба, видно только в логе чекера: его и разбираем.
            failing = [n for (n, a), v in ex_data.items() if a not in skip and v.get("status", 0) < 1]
            ex_errors = (checker_errors(ex_src) or {}) if failing else {}
            for (name, addr), v in ex_data.items():
                if addr in skip:
                    continue
                detail = entry_label(addr, labels)
                if v.get("status", 0) < 1:
                    detail += " — " + checker_problem(ex_errors.get(name), ex_src.get("timeout_seconds"),
                                                      ex_src.get("min_bytes", 1048576))
                key = "exit:%s" % name
                sample = [v.get("status", 0), v.get("latency", 0)]
                is_new = sample != state["checks"].get(key, {}).get("sample")
                evaluate_sample(key, v, detail, ex_src, state, cfg, events, now)
                if _tracked(key):
                    history.touch(state, now, key, state["checks"][key]["alerted"])
                    if is_new and v.get("status", 0) >= 1:
                        history.add_latency(state, now, key, v.get("latency", 0))

    # --- HAProxy: телеграм и почта кабинета
    hap = haproxy_backends(cfg)
    evaluate("source:haproxy", hap is not None, "сокет HAProxy недоступен", state, cfg, events)
    if hap:
        summary["haproxy"] = hap
        for backend, status in hap.items():
            evaluate("hap:%s" % backend, status.startswith("UP"), "статус %s" % status,
                     state, cfg, events)
        for pool in cfg.get("haproxy_pools", []):
            members = {k: v for k, v in hap.items() if k.startswith(pool + "/")}
            if members and all(not v.startswith("UP") for v in members.values()):
                evaluate("hap_pool:%s" % pool, False, "весь пул лежит", state, cfg, events)
            else:
                evaluate("hap_pool:%s" % pool, True, "", state, cfg, events)

    # --- квоты трафика на нодах
    quota_cycle(cfg, state, events, summary)

    # --- регион YouTube: нет ли рекламы
    yt_region_cycle(cfg, state, events, summary)

    # --- российские локации: YouTube открывается и не порезан
    yt_speed_cycle(cfg, state, events, summary)

    # --- маскировка selfsteal: домен на месте, сертификат живой
    mask_cycle(cfg, state, events, summary)

    # --- подписка через Yandex CDN: A-запись на текущем эдже, сертификат живой
    cdn_cycle(cfg, state, events, summary)
    cdn_via_cycle(cfg, cfg.get("cdn_subscription") or {}, state, events, time.time())

    # --- кабинет, лендинг и путь вебхука бота — с этой машины, то есть из РФ
    web_cycle(cfg, state, events, summary)

    history.prune(state, now)
    return events, summary


def heartbeat_step(cfg, state, summary, now):
    today = datetime.fromtimestamp(now, timezone.utc)
    hb_hour = cfg.get("heartbeat_hour_utc")
    day = today.strftime("%Y-%m-%d")
    if hb_hour is None or state.get("last_heartbeat") == day or today.hour != hb_hour:
        return
    try:
        sent = send_summary(cfg, summary, state, now)
    except Exception as e:
        log("сводка упала: %r" % e)
        return
    if sent:
        state["last_heartbeat"] = day
        state["blips"] = {}


def cli_prepare(args, now):
    """(cfg, summary, state) для CLI-режимов; состояние — копия, на диск не пишется."""
    import demo_data
    cfg = {}
    if args.test_summary is not None or not args.demo:
        cfg = load_json(CONFIG_PATH, None)
        if not cfg:
            log("нет конфига %s" % CONFIG_PATH)
            return None
    if args.demo:
        summary, state = demo_data.demo_summary(), demo_data.demo_state(now)
    else:
        state = copy.deepcopy(load_json(STATE_PATH, {"checks": {}, "last_heartbeat": None}))
        state.setdefault("checks", {})
        _, summary = run_cycle(cfg, state)
    if args.demo_history:
        state["history"] = {}
        demo_data.demo_history(state, now)
    return cfg, summary, state


def cli(args):
    now = time.time()
    prepared = cli_prepare(args, now)
    if prepared is None:
        return 1
    cfg, summary, state = prepared
    marks = (args.demo, args.demo_history)
    if args.render is not None:
        header, details = caption_parts(summary, state, now)
        caption, extra = compose_caption(mark_demo(header, *marks), details)
        try:
            pngs = _render_cards(build_models(summary, state, now))
        except Exception as e:
            log("рендер карточек не удался: %r" % e)
            return 1
        if len(pngs) != len(CARD_FILES):
            log("рендер вернул %d карточек вместо %d" % (len(pngs), len(CARD_FILES)))
            return 1
        os.makedirs(args.render, exist_ok=True)
        for name, png in zip(CARD_FILES, pngs):
            with open(os.path.join(args.render, name), "wb") as f:
                f.write(png)
        with open(os.path.join(args.render, "caption.html"), "w", encoding="utf-8") as f:
            f.write(caption + ("\n\n" + extra if extra else ""))
        log("превью записано в %s" % args.render)
        return 0
    ok = send_summary(cfg, summary, state, now, chat=args.test_summary, thread=False, demo=marks)
    return 0 if ok else 1


CARD_FILES = ("1_dashboard.png", "2_matrix.png", "3_heatmap.png", "4_speed.png")


def main(argv=None):
    ap = argparse.ArgumentParser(description="алертер zanity; без флагов — рабочий цикл")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--render", metavar="DIR", help="записать 4 PNG и caption.html в DIR")
    mode.add_argument("--test-summary", metavar="CHAT_ID", help="отправить сводку в этот чат без треда")
    ap.add_argument("--demo", action="store_true", help="фикстура вместо конфига и проб")
    ap.add_argument("--demo-history", action="store_true", help="история из фикстуры")
    args = ap.parse_args(argv)
    for flag in ("render", "test_summary"):
        if getattr(args, flag) is not None and not getattr(args, flag).strip():
            ap.error("--%s: пустое значение" % flag.replace("_", "-"))
    if args.render is not None or args.test_summary is not None:
        return cli(args)
    if args.demo or args.demo_history:
        ap.error("--demo и --demo-history нужны вместе с --render или --test-summary")
    cfg = load_json(CONFIG_PATH, None)
    if not cfg:
        log("нет конфига %s" % CONFIG_PATH)
        return 1
    state = load_json(STATE_PATH, {"checks": {}, "last_heartbeat": None})
    state.setdefault("checks", {})

    interval = cfg.get("interval_seconds", 60)
    log("старт, интервал %d с" % interval)

    while True:
        started = time.time()
        try:
            events, summary = run_cycle(cfg, state)
            text = format_events(events)
            if text:
                if send_telegram(cfg, text):
                    log("отправлено событий: %d" % len(events))
                else:
                    # не гасим флаги, если отправить не удалось — повторим на следующем круге
                    for kind, key, _ in events:
                        st = state["checks"].get(key)
                        if st and kind == "down":
                            st["alerted"] = False

            heartbeat_step(cfg, state, summary, time.time())

            save_state(state)
        except Exception as e:
            log("цикл упал: %r" % e)

        time.sleep(max(5, interval - (time.time() - started)))


if __name__ == "__main__":
    sys.exit(main())
