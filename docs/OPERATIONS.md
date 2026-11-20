# Эксплуатация (прод)

Мониторинг zanity VPN: алертер на ctl-host и внешний сторож на exit-1.

> Публичный снимок рабочего репозитория. IP-адреса, домены и имена хостов заменены на примеры
> (RFC 5737, `example.*`, `ctl-host`), поэтому конфиги в `deploy/` — образцы, а не боевые значения.

| Что | Где на проде | Здесь |
|---|---|---|
| Алертер (`zanity-alerter.service`) | ctl-host: `/opt/zanity-alerter/alerter.py`, конфиг `/etc/zanity-alerter/config.json`, состояние `/var/lib/zanity-alerter/state.json` | `alerter/`, `deploy/alerter/` |
| xray-checker с download-зондом | ctl-host: `/opt/zanity-monitoring/docker-compose.yml` | `deploy/monitoring/` |
| Внешний сторож (`zanity-watchdog.timer`) | exit-1: `/opt/zanity-watchdog/watchdog.py`, env `/etc/zanity-watchdog.env` | `watchdog/`, `deploy/watchdog/` |

Секреты в репо не хранятся: в `config.example.json` и `docker-compose.yml` они заменены на `__REDACTED__`,
настоящие значения есть только на серверах. Токен бота и `PROXY_URL` алертер берёт из `.env` бота (`bot_env`).

## Тесты

```bash
uv run pytest
```

Прод: Python 3.12 на ctl-host, 3.10 на exit-1, поэтому код совместим с 3.10 и сторонних зависимостей на проде нет.

## Превью сводки

Локально, без конфига и проб (фикстура, PNG и `caption.html` в каталоге):

```bash
uv run python alerter/alerter.py --render /tmp/preview --demo --demo-history
```

Тест в личку на проде, от root в staging-каталоге (боевое состояние не пишется, тред не используется):

```bash
python3 alerter.py --test-summary <chat_id> [--demo-history]
```

## Выкладка алертера

Только с явного согласия владельца. Перед заменой — бэкап рядом (`alerter.py.bak-YYYYMMDD-<метка>`),
конфиг читается при старте, поэтому после правки — `systemctl restart zanity-alerter`.

Пошаговая инструкция выкладки сводки карточками и откат: [deploy/alerter/DEPLOY.md](../deploy/alerter/DEPLOY.md).
