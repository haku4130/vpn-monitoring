# Внешний сторож

Раз в минуту с другой машины (сейчас exit-1) проверяет то, что видят пользователи и Telegram:

- **бот принимает апдейты**: `getWebhookInfo` (вебхук задан, Telegram не копит недоставленные апдейты)
  и GET `<база url вебхука>/health/telegram-webhook` через всю цепочку реле (сейчас exit-4:88 → exit-1:8443 → ctl-host);
- бот на origin (`bot.example.net/health`), панель, чекер;
- кабинет `/` и API `/api/cabinet/branding/favicon` — через front-1 (как у пользователей) и на origin ctl-host
  в обход front-1; если origin жив, а путь через front-1 нет, в тревоге так и написано;
- лендинг через front-1 и Worker `origin.example.com`;
- сертификаты кабинета (front-1 и origin) и лендинга — не меньше 20 дней.

Проверки — в `deploy/watchdog/checks.json`, виды описаны в начале `watchdog.py`. Каждый прогон — замер:
после `FAILURES_BEFORE_ALERT` (3) неудач подряд пишет в Telegram, с первого успеха — «восстановилось» и сколько
длился простой. Всё, что сломалось за прогон, — одним сообщением.

Алертер на том же сервере, что и бот, при зависании сервера молчит, поэтому сторож стоит отдельно. Обратный
случай (умер exit-1, а он и звено цепочки вебхука) прикрывает алертер: `web_checks` в его конфиге.

## Выкладка

```bash
H=exit-1
scp watchdog/watchdog.py deploy/watchdog/checks.json $H:/tmp/
ssh $H 'sudo install -m 644 /tmp/watchdog.py /opt/zanity-watchdog/watchdog.py && sudo install -m 644 /tmp/checks.json /opt/zanity-watchdog/checks.json'
# /etc/zanity-watchdog.env: BOT_TOKEN, CHAT_ID, THREAD_ID, FAILURES_BEFORE_ALERT, STATE_FILE, CHECKS_FILE=/opt/zanity-watchdog/checks.json
```

Проверка без отправки и без записи состояния:

```bash
ssh exit-1 'sudo bash -c "set -a; . /etc/zanity-watchdog.env; set +a; DRY_RUN=1 python3 /opt/zanity-watchdog/watchdog.py"'
```

Первичная установка юнитов: `deploy/watchdog/zanity-watchdog.{service,timer}` в `/etc/systemd/system/`,
`systemctl daemon-reload && systemctl enable --now zanity-watchdog.timer`.

Откат: вернуть `watchdog.py` из бэкапа и убрать `CHECKS_FILE` из env (старый `CHECK_URLS` код понимает);
выключить совсем — `systemctl disable --now zanity-watchdog.timer`.
