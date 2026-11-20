import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watchdog import watchdog as w
from watchdog.watchdog import (apply_hints, cert_problem, http_problem, relay_probe_url, relay_problem,
                               specs_from_urls, step, webhook_problem)


T0 = datetime(2026, 11, 15, 8, 36, tzinfo=timezone.utc)
A, B = 'a', 'b'


def res(key, ok, detail='сбой', threshold=None):
    return {'key': key, 'label': key, 'ok': ok, 'detail': 'ok' if ok else detail, 'threshold': threshold}


def run(seq, threshold=3):
    state, messages = {}, []
    for i, results in enumerate(seq):
        state, msg = step(state, results, T0 + timedelta(minutes=i), threshold)
        messages.append(msg)
    return state, messages


# --- step: гистерезис по замерам

def test_alert_only_after_threshold_and_once():
    _, msgs = run([[res(A, False, 'таймаут'), res(B, True)]] * 5)
    assert [m is not None for m in msgs] == [False, False, True, False, False]
    assert '• a — таймаут' in msgs[2] and '• b' not in msgs[2]


def test_flap_below_threshold_is_silent():
    _, msgs = run([[res(A, False)], [res(A, False)], [res(A, True)], [res(A, False)], [res(A, False)], [res(A, True)]])
    assert msgs == [None] * 6


def test_recovery_is_per_check_and_counts_from_first_failure():
    seq = [[res(A, False), res(B, False)]] * 3 + [[res(A, True), res(B, False)], [res(A, True), res(B, True)]]
    state, msgs = run(seq)
    assert msgs[2].startswith('🔴') and '• a' in msgs[2] and '• b' in msgs[2]
    assert msgs[3].startswith('🟢') and '• a — простой ~3 мин' in msgs[3] and '• b' not in msgs[3]
    assert '• b — простой ~4 мин' in msgs[4]
    assert state['checks'][A] == {'fails': 0, 'alerted': False}


def test_new_problem_and_recovery_in_one_message():
    seq = [[res(A, False), res(B, True)]] * 3 + [[res(A, False), res(B, False)]] * 3 + [[res(A, True), res(B, False)]]
    _, msgs = run(seq)
    assert msgs[5].startswith('🔴') and '• b' in msgs[5]
    assert msgs[6].startswith('🟢') and '• a — простой' in msgs[6]


def test_per_check_threshold():
    _, msgs = run([[res(A, False, threshold=1)]])
    assert msgs[0] and '• a' in msgs[0]


def test_missing_result_keeps_state():
    # Telegram не ответил на getWebhookInfo — тревога не снимается и не дублируется
    state, msgs = run([[res(A, False)]] * 3 + [[]] + [[res(A, False)]])
    assert msgs[3] is None and msgs[4] is None
    assert state['checks'][A]['alerted']


def test_old_state_format_is_ignored():
    new, msg = step({'fails': {'https://x/': 2}, 'down_since': None}, [res(A, False)], T0, 3)
    assert msg is None and new['checks'][A]['fails'] == 1


# --- разбор ответов

def test_http_problem():
    spec = {'contains': '<title>ZanityVPN</title>'}
    assert http_problem(200, b'<title>ZanityVPN</title>', spec) is None
    assert 'нет' in http_problem(200, b'<title>502</title>', spec)
    assert '502 вместо 200' in http_problem(502, b'', spec)
    assert http_problem(None, b'', spec, 'не ответил за 10 с') == 'не ответил за 10 с'
    assert http_problem(302, b'', {'any_ok': True}) is None
    assert '502' in http_problem(502, b'', {'any_ok': True})


def test_cert_problem():
    assert cert_problem(T0 + timedelta(days=60), T0, 20) is None
    assert 'через 10 дн.' in cert_problem(T0 + timedelta(days=10, hours=3), T0, 20)
    assert 'не прочитан' in cert_problem(None, T0, 20)


def test_webhook_ok_with_old_error():
    info = {'url': 'https://exit-4.example.net:88/webhook', 'pending_update_count': 0,
            'last_error_date': int(T0.timestamp()) - 86400, 'last_error_message': 'Connection timed out'}
    assert webhook_problem(info, T0) is None


def test_webhook_undelivered_updates_is_the_11_15_case():
    info = {'url': 'https://exit-4.example.net:88/webhook', 'pending_update_count': 7,
            'last_error_date': int(T0.timestamp()) - 120, 'last_error_message': 'Connection timed out'}
    p = webhook_problem(info, T0)
    assert '7 апд.' in p and 'Connection timed out' in p


def test_webhook_old_error_with_inflight_update_is_fine():
    info = {'url': 'https://x/webhook', 'pending_update_count': 1, 'last_error_date': int(T0.timestamp()) - 7200}
    assert webhook_problem(info, T0) is None


def test_webhook_queue_overflow_and_missing_url():
    assert '60 апд.' in webhook_problem({'url': 'https://x/webhook', 'pending_update_count': 60}, T0)
    assert 'не задан' in webhook_problem({'url': '', 'pending_update_count': 0}, T0)


def test_relay():
    assert relay_probe_url('https://exit-4.example.net:88/webhook') == 'https://exit-4.example.net:88/health/telegram-webhook'
    assert relay_problem(200, b'{"status":"ok","mode":"webhook"}') is None
    assert '502' in relay_problem(502, b'')
    assert 'не JSON' in relay_problem(200, b'<html>caddy</html>')
    assert relay_problem(None, b'', 'не ответил за 10 с') == 'не ответил за 10 с'


def test_hint_only_when_neighbour_passed():
    specs = [{'key': 'cabinet', 'diagnose_with': 'cabinet_origin', 'hint': 'дело в front-1'}]
    rs = [res('cabinet', False, 'таймаут'), res('cabinet_origin', True)]
    apply_hints(rs, specs)
    assert rs[0]['detail'] == 'таймаут — дело в front-1'
    rs = [res('cabinet', False, 'таймаут'), res('cabinet_origin', False, 'таймаут')]
    apply_hints(rs, specs)
    assert rs[0]['detail'] == 'таймаут'


def test_legacy_urls():
    assert specs_from_urls(['https://a/'])[0]['any_ok']


def test_checks_json_is_valid():
    specs = json.loads((Path(__file__).parents[1] / 'deploy/watchdog/checks.json').read_text())['checks']
    keys = [s['key'] for s in specs]
    assert len(keys) == len(set(keys))
    for s in specs:
        assert s['type'] in ('http', 'tg_webhook') and s['label']
        assert s['type'] != 'http' or s['url'].startswith('https://')
        assert not s.get('diagnose_with') or s['diagnose_with'] in keys


# --- сеть: HTTPS-сервер не поднимаем, подменяем fetch

def test_run_http_reports_cert_and_failure(monkeypatch):
    spec = {'key': 'c', 'label': 'Кабинет', 'url': 'https://c/', 'cert_min_days': 20}
    monkeypatch.setattr(w, 'fetch', lambda url, resolve=None: (200, b'ok', T0 + timedelta(days=5)))
    out = w.run_http(spec, T0)
    assert out[0]['ok'] and not out[1]['ok'] and out[1]['key'] == 'c:cert'

    def boom(url, resolve=None):
        raise TimeoutError()
    monkeypatch.setattr(w, 'fetch', boom)
    out = w.run_http(spec, T0)
    assert len(out) == 1 and out[0]['detail'] == 'не ответил за 10 с'
