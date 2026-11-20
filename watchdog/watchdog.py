"""Внешний сторож zanity: бот, кабинет, лендинг, панель, чекер.

Запускается таймером systemd раз в минуту на другой машине (exit-1): алертер живёт на том же
сервере, что и бот, и при зависании сервера молчит вместе с ним. Только stdlib, Python 3.10+.

Окружение: BOT_TOKEN, CHAT_ID, THREAD_ID (необязательно), STATE_FILE, FAILURES_BEFORE_ALERT (3),
CHECKS_FILE — JSON со списком проверок (deploy/watchdog/checks.json). Без CHECKS_FILE берётся
CHECK_URLS через запятую: старый формат, каждый URL — «ответил 2xx/3xx».
DRY_RUN=1 — напечатать результаты и сообщение вместо отправки, состояние не писать.

Виды проверок:
  http        — url отвечает expect_status (200), в теле есть contains; resolve — ходить на этот IP
                с SNI и Host из url (так проверяется origin в обход front-1); cert_min_days — отдельная
                проверка «<key>:cert» по сертификату того же соединения; diagnose_with — ключ соседней
                проверки: если она в этом прогоне прошла, к причине дописывается hint.
  tg_webhook  — getWebhookInfo: вебхук задан и Telegram не копит недоставленные апдейты; плюс
                «<key>:relay» — GET <база url вебхука>/health/telegram-webhook через всю цепочку
                реле до бота. Пустой POST на /webhook не годится: бот на каждый пишет warning.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


TIMEOUT_SECONDS = 10
MAX_BODY = 512 * 1024
USER_AGENT = 'zanity-watchdog'
WEBHOOK_ERROR_WINDOW = 30 * 60
WEBHOOK_PENDING_MAX = 50


# --------------------------------------------------------------------------- чистая логика

def http_problem(status: int | None, body: bytes, spec: dict, error: str | None = None) -> str | None:
    """Что не так с ответом, или None."""
    if error:
        return error
    if spec.get('any_ok'):
        return None if status is not None and 200 <= status < 400 else f'ответил {status}'
    want = spec.get('expect_status', 200)
    if status != want:
        return f'ответил {status} вместо {want}'
    marker = spec.get('contains')
    if marker and marker.encode() not in body:
        return f'в ответе нет «{marker}»'
    return None


def cert_problem(not_after: datetime | None, now: datetime, min_days: int) -> str | None:
    if not_after is None:
        return 'не прочитан'
    days = (not_after - now).days
    if days < min_days:
        return f'истекает через {days} дн. (до {not_after:%Y-%m-%d})'
    return None


def webhook_problem(info: dict, now: datetime) -> str | None:
    """Разбор getWebhookInfo: недоставленные апдейты — это и есть «бот молчит» для пользователя."""
    if not info.get('url'):
        return 'вебхук не задан (deleteWebhook или бот в polling) — апдейты никуда не уходят'
    pending = info.get('pending_update_count', 0)
    error_at = info.get('last_error_date')
    if pending and error_at and now.timestamp() - error_at <= WEBHOOK_ERROR_WINDOW:
        message = info.get('last_error_message') or 'без текста'
        return f'Telegram не может доставить {pending} апд.: {message}'
    if pending >= WEBHOOK_PENDING_MAX:
        return f'в очереди Telegram {pending} апд. — бот не забирает'
    return None


def relay_probe_url(webhook_url: str) -> str:
    u = urllib.parse.urlsplit(webhook_url)
    return f'{u.scheme}://{u.netloc}/health/telegram-webhook'


def relay_problem(status: int | None, body: bytes, error: str | None = None) -> str | None:
    if error:
        return error
    if status != 200:
        return f'ответил {status} вместо 200'
    try:
        data = json.loads(body)
    except ValueError:
        return 'ответ не JSON — отвечает не бот'
    if not isinstance(data, dict) or data.get('status') != 'ok':
        return 'бот ответил не status=ok'
    return None


def apply_hints(results: list[dict], specs: list[dict]) -> None:
    """Дописать к причине подсказку, если проверка-соседка в этом прогоне прошла."""
    ok = {r['key']: r['ok'] for r in results}
    hints = {s['key']: (s['diagnose_with'], s.get('hint', '')) for s in specs if s.get('diagnose_with')}
    for r in results:
        if not r['ok'] and r['key'] in hints:
            other, hint = hints[r['key']]
            if ok.get(other) and hint:
                r['detail'] += f' — {hint}'


def step(state: dict, results: list[dict], now: datetime, threshold: int) -> tuple[dict, str | None]:
    """Новый state и текст сообщения (или None). Чистая функция.

    results: [{'key', 'label', 'ok', 'detail', 'threshold'?}]. Каждый прогон таймера — независимый
    замер: тревога после threshold неудач подряд, восстановление — с первого успеха. Проверки,
    которых в этом прогоне не было (Telegram не ответил на getWebhookInfo), остаются как были.
    """
    checks = dict(state.get('checks', {}))
    down, up = [], []
    for r in results:
        st = dict(checks.get(r['key'], {'fails': 0, 'alerted': False}))
        if r['ok']:
            if st.get('alerted'):
                minutes = int((now - datetime.fromisoformat(st['since'])).total_seconds() // 60)
                up.append(f'• {r["label"]} — простой ~{minutes} мин')
            st = {'fails': 0, 'alerted': False}
        else:
            st['fails'] = st.get('fails', 0) + 1
            if st['fails'] == 1:
                st['since'] = now.isoformat()
            if st['fails'] >= (r.get('threshold') or threshold) and not st.get('alerted'):
                st['alerted'] = True
                down.append(f'• {r["label"]} — {r["detail"]}')
            st['detail'] = r['detail']
        checks[r['key']] = st
    blocks = []
    if down:
        blocks.append('🔴 Сторож exit-1: проблема\n' + '\n'.join(down))
    if up:
        blocks.append('🟢 Сторож exit-1: восстановилось\n' + '\n'.join(up))
    return {'checks': checks}, ('\n\n'.join(blocks) or None)


def specs_from_urls(urls: list[str]) -> list[dict]:
    return [{'type': 'http', 'key': u, 'label': u, 'url': u, 'any_ok': True} for u in urls]


# --------------------------------------------------------------------------- сеть

def fetch(url: str, resolve: str | None = None) -> tuple[int, bytes, datetime | None]:
    """GET без редиректов; сертификат берётся с того же соединения."""
    u = urllib.parse.urlsplit(url)
    host, port = u.hostname, u.port or 443
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(host, port, timeout=TIMEOUT_SECONDS, context=ctx)
    try:
        if resolve:
            sock = socket.create_connection((resolve, port), timeout=TIMEOUT_SECONDS)
            conn.sock = ctx.wrap_socket(sock, server_hostname=host)
        conn.request('GET', (u.path or '/') + (f'?{u.query}' if u.query else ''),
                     headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
        response = conn.getresponse()
        body = response.read(MAX_BODY)
        cert = conn.sock.getpeercert() if conn.sock else None
        not_after = None
        if cert and cert.get('notAfter'):
            not_after = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert['notAfter']), timezone.utc)  # noqa: UP017
        return response.status, body, not_after
    finally:
        conn.close()


def short_error(exc: Exception) -> str:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return f'сертификат не прошёл проверку: {exc.verify_message}'
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return f'не ответил за {TIMEOUT_SECONDS} с'
    if isinstance(exc, ConnectionRefusedError):
        return 'соединение отклонено'
    if isinstance(exc, socket.gaierror):
        return 'имя не резолвится'
    return f'{type(exc).__name__}: {exc}'[:160]


def run_http(spec: dict, now: datetime) -> list[dict]:
    status, body, not_after, error = None, b'', None, None
    try:
        status, body, not_after = fetch(spec['url'], spec.get('resolve'))
    except Exception as exc:
        error = short_error(exc)
    problem = http_problem(status, body, spec, error)
    threshold = spec.get('failures_before_alert')
    out = [{'key': spec['key'], 'label': spec['label'], 'ok': problem is None,
            'detail': problem or 'ok', 'threshold': threshold}]
    if spec.get('cert_min_days') and error is None:
        cp = cert_problem(not_after, now, spec['cert_min_days'])
        out.append({'key': spec['key'] + ':cert', 'label': spec['label'] + ': сертификат',
                    'ok': cp is None, 'detail': cp or 'ok', 'threshold': threshold})
    return out


def run_tg_webhook(spec: dict, token: str, now: datetime) -> list[dict]:
    label, threshold = spec['label'], spec.get('failures_before_alert')
    try:
        with urllib.request.urlopen(f'https://api.telegram.org/bot{token}/getWebhookInfo',
                                    timeout=TIMEOUT_SECONDS) as response:
            info = json.loads(response.read()).get('result', {})
    except Exception as exc:
        # без ответа Telegram о вебхуке ничего не сказать — неудачей не считаем (текст без URL: в нём токен)
        print(f'getWebhookInfo не ответил: {type(exc).__name__}', file=sys.stderr)
        return []
    problem = webhook_problem(info, now)
    out = [{'key': spec['key'], 'label': label, 'ok': problem is None,
            'detail': problem or 'ok', 'threshold': threshold}]
    if info.get('url'):
        status, body, error = None, b'', None
        try:
            status, body, _ = fetch(relay_probe_url(info['url']))
        except Exception as exc:
            error = short_error(exc)
        rp = relay_problem(status, body, error)
        host = urllib.parse.urlsplit(info['url']).netloc
        out.append({'key': spec['key'] + ':relay', 'label': f'{label}: путь Telegram → {host} → бот',
                    'ok': rp is None, 'detail': rp or 'ok', 'threshold': threshold})
    return out


def send(token: str, chat_id: str, thread_id: str, text: str) -> None:
    data = {'chat_id': chat_id, 'text': text, 'disable_web_page_preview': 'true'}
    if thread_id:
        data['message_thread_id'] = thread_id
    body = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(f'https://api.telegram.org/bot{token}/sendMessage', body, timeout=TIMEOUT_SECONDS):
        pass


def load_specs(env: dict) -> list[dict]:
    if env.get('CHECKS_FILE'):
        return json.loads(Path(env['CHECKS_FILE']).read_text())['checks']
    return specs_from_urls([u.strip() for u in env.get('CHECK_URLS', '').split(',') if u.strip()])


def main() -> int:
    env = os.environ
    dry = env.get('DRY_RUN') == '1'
    specs = load_specs(env)
    if not specs or not env.get('BOT_TOKEN') or not (env.get('CHAT_ID') or dry):
        print('нужны CHECKS_FILE или CHECK_URLS, BOT_TOKEN, CHAT_ID', file=sys.stderr)
        return 2
    state_file = Path(env.get('STATE_FILE', '/var/lib/zanity-watchdog/state.json'))
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {}
    now = datetime.now(timezone.utc)  # noqa: UP017 — на exit-1 Python 3.10
    runners = {'http': lambda s: run_http(s, now), 'tg_webhook': lambda s: run_tg_webhook(s, env['BOT_TOKEN'], now)}
    # параллельно: при лежащем ctl-host таймауты по очереди не уложились бы в TimeoutStartSec юнита
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [r for rs in pool.map(lambda s: runners[s['type']](s), specs) for r in rs]
    apply_hints(results, specs)
    threshold = int(env.get('FAILURES_BEFORE_ALERT', '3'))
    new, message = step(state, results, now, threshold)
    if dry:
        for r in results:
            print(f'{"ok  " if r["ok"] else "FAIL"} {r["key"]}: {r["detail"]}')
        print('--- сообщение после этого прогона:\n' + (message or '(нет)'))
        return 0
    if message:
        try:
            send(env['BOT_TOKEN'], env['CHAT_ID'], env.get('THREAD_ID', ''), message)
        except Exception as exc:
            # без repr: у части исключений в тексте URL с токеном
            print(f'не отправил в Telegram: {type(exc).__name__} {getattr(exc, "code", "")}', file=sys.stderr)
            new = state  # этот переход повторится в следующий прогон
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(new, ensure_ascii=False))
    bad = [f'{r["key"]} ({r["detail"]})' for r in results if not r['ok']]
    if bad:
        print('не в порядке: ' + '; '.join(bad))
    return 0


if __name__ == '__main__':
    sys.exit(main())
