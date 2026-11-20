# Выкладка алертера со сводкой карточками

Прод: хост ctl-host, `root@203.0.113.20`. Сервис systemd `zanity-alerter`
(`ExecStart=/usr/bin/python3 /opt/zanity-alerter/alerter.py`, работает от root).
Конфиг `/etc/zanity-alerter/config.json` (читается при старте), состояние `/var/lib/zanity-alerter/state.json`.

В `/opt/zanity-alerter` сейчас лежат `alerter.py`, старые `test_*.py` и копии `alerter.py.bak-*`.
На прод едут только рабочие файлы: `alerter.py summary.py history.py cards.py demo_data.py` и каталог `assets/`
(шрифты и twemoji). Тесты на проде не нужны.

Каждый шаг ниже, который что-то меняет на проде, выполнять только после «да» владельца.

```bash
H=root@203.0.113.20
cd ~/zanity-monitoring   # корень репозитория; дальше все пути от него
```

Выкладывать только известный коммит: перед шагом 2 `git status --short` не должен показывать изменений
в отслеживаемых файлах (допустимы только неотслеживаемые `BRIEF.md`, `spike/`), а вывод `git rev-parse HEAD`
назвать владельцу вместе с просьбой «да».

## 1. Pillow (только после «да» владельца)

`NEEDRESTART_MODE=l` только перечисляет устаревшие сервисы и ничего не перезапускает: на этом хосте живут базы бота и панели.

```bash
ssh $H 'apt-get update && NEEDRESTART_MODE=l DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pil'
ssh $H 'python3 -c "import PIL; print(PIL.__version__)"'   # ожидается 10.2.0
```

## 2. Staging-копия (только после «да» владельца)

```bash
git status --short; git rev-parse HEAD   # чисто, коммит известен
ssh $H 'mkdir -p /root/zanity-alerter-cards'
rsync -av --no-owner --no-group \
  alerter/alerter.py alerter/summary.py alerter/history.py alerter/cards.py alerter/demo_data.py alerter/assets \
  $H:/root/zanity-alerter-cards/
ssh $H 'cd /root/zanity-alerter-cards && python3 -m py_compile alerter.py summary.py history.py cards.py demo_data.py'
```

`--no-owner --no-group`: иначе на сервер приедут uid 501 / gid staff с Mac.

## 3. Тест в личку владельца (только после «да» владельца)

`<OWNER_CHAT_ID>` — личный чат владельца; бот должен быть им запущен (`/start`).
Запуск от root в staging-каталоге с боевым конфигом и состоянием. CLI состояние не сохраняет (только чтение).

```bash
# живые данные: тепловая карта и скорость серые, история начнётся только после выкладки
ssh $H 'cd /root/zanity-alerter-cards && python3 alerter.py --test-summary <OWNER_CHAT_ID>'
# демо-история, в подписи есть пометка
ssh $H 'cd /root/zanity-alerter-cards && python3 alerter.py --test-summary <OWNER_CHAT_ID> --demo-history'
```

Успех: в личку пришёл альбом из 4 карточек с подписью. Одно текстовое сообщение вместо альбома означает сбой:
прочитать вывод команды («рендер карточек не удался» или «телеграм ответил на альбом …»), выкладку не начинать.
Ждать «ок» владельца на результат теста.

## 4. Выкладка (только после отдельного явного «да» на саму выкладку)

«ок» на тест из шага 3 этого не заменяет: спросить отдельно «выкладываю на прод?» и дождаться «да».

Перед заменой весь рабочий набор (`alerter.py`, модули, `assets/` — что из этого есть) и `state.json` копируются
в каталог бэкапа `/opt/zanity-alerter-backups/<STAMP>`. Метка берётся по UTC с сервера; `mkdir` без `-p` падает,
если каталог уже есть, поэтому бэкап никогда не перезаписывается. Бэкап, копирование, проверка и рестарт идут
одним вызовом под `set -e`: при любой ошибке всё останавливается до рестарта.

```bash
STAMP=$(ssh $H 'date -u +%Y%m%d-%H%M'); echo $STAMP   # записать: нужна для отката
ssh $H "set -e
B=/opt/zanity-alerter-backups/$STAMP
mkdir -p /opt/zanity-alerter-backups
mkdir \$B
cd /opt/zanity-alerter
for f in alerter.py summary.py history.py cards.py demo_data.py assets; do
  if [ -e \$f ]; then cp -a \$f \$B/; fi
done
cp -a /var/lib/zanity-alerter/state.json \$B/state.json
ls -la \$B
cd /root/zanity-alerter-cards
cp -r --no-preserve=ownership alerter.py summary.py history.py cards.py demo_data.py assets /opt/zanity-alerter/
cd /opt/zanity-alerter
chown -R root:root alerter.py summary.py history.py cards.py demo_data.py assets
python3 -m py_compile alerter.py summary.py history.py cards.py demo_data.py
python3 -c 'import alerter, cards'
systemctl restart zanity-alerter
echo DEPLOYED"
ssh $H 'systemctl status zanity-alerter --no-pager'
ssh $H 'journalctl -u zanity-alerter -n 50 --no-pager'   # есть «старт», нет «цикл упал»
```

`python3 -c 'import alerter, cards'` ловит то, чего не видит `py_compile`: недостающий модуль или Pillow.
Без строки `DEPLOYED` в выводе рестарта не было: прочитать, на какой команде остановилось.
Если упало уже после копирования в `/opt`, сервис ещё работает на старом коде в памяти, но файлы новые:
сразу сделать откат (шаг 5) из только что созданного бэкапа, чтобы следующий рестарт не поднял сломанный код.

Через ~5 минут проверить, что в состоянии появилась история:

```bash
ssh $H 'python3 -c "import json; print(\"history\" in json.load(open(\"/var/lib/zanity-alerter/state.json\")))"'   # True
```

Первый настоящий альбом уйдёт в ближайшие 07:00 UTC. Утром после него проверить итог:

```bash
ssh $H 'journalctl -u zanity-alerter --since "today 06:55" --no-pager | grep -iE "сводк|альбом|рендер карточек|цикл упал"'
```

Ожидается запись об отправленном альбоме и ни одного «рендер карточек не удался» или «телеграм ответил на альбом …»;
в чат пришли 4 карточки. В GitHub при выкладке ничего не пушится: пуш только по просьбе владельца.

## 5. Откат (только после «да» владельца)

`<STAMP>` — метка из шага 4. Набор из бэкапа сначала собирается и проверяется во временном каталоге
(компиляция и импорт), и только потом рабочие файлы в `/opt/zanity-alerter` заменяются на него. Файлы, которых
в бэкапе нет (например, модули сводки при откате на версию до карточек), удаляются. `test_*.py` и старые
`alerter.py.bak-*` не трогаются.

```bash
ssh $H "set -e
B=/opt/zanity-alerter-backups/<STAMP>
test -f \$B/alerter.py
T=\$(mktemp -d)
cp -a \$B/. \$T/
rm -f \$T/state.json
cd \$T
python3 -m py_compile *.py
python3 -c 'import alerter'
cd /opt/zanity-alerter
rm -rf summary.py history.py cards.py demo_data.py assets __pycache__
cp -a \$T/. /opt/zanity-alerter/
rm -rf \$T /opt/zanity-alerter/__pycache__
python3 -c 'import alerter'
systemctl restart zanity-alerter
echo ROLLED_BACK"
ssh $H 'journalctl -u zanity-alerter -n 50 --no-pager'
```

Без `ROLLED_BACK` рестарта не было. Если остановилось до `rm -rf` в `/opt` (бэкап не нашёлся, не скомпилировался
или не импортировался), рабочие файлы не тронуты.

Откат на любой коммит без бэкапа (например, бэкапа нужной версии нет): собрать нужный коммит из git и выложить
его шагами 2 и 4 вместо текущего.

```bash
C=<коммит>; D=$(mktemp -d); git archive $C alerter | tar -x -C $D
rsync -a --no-owner --no-group $D/alerter/alerter.py $D/alerter/summary.py $D/alerter/history.py \
  $D/alerter/cards.py $D/alerter/demo_data.py $D/alerter/assets $H:/root/zanity-alerter-cards/
```

Бэкапы первых выкладок 2026-11-11 сделаны старой схемой, одним файлом:
`/opt/zanity-alerter/alerter.py.bak-20261111-1251-cards` — версия до карточек (без модулей), и
`/var/lib/zanity-alerter/state.json.bak-20261111-1251-cards`. Откат на версию до карточек из него: положить файл
как `alerter.py` в пустой каталог `/opt/zanity-alerter-backups/20261111-1251` и выполнить блок выше с этой меткой.

Ключ `history` и поля `hist_sample`/`hist_at` внутри `checks` в `state.json` старому коду не мешают: он читает только свои ключи, оставить можно.
Убрать по желанию. Сервис на время останавливается, иначе он перезапишет файл; запускается обратно в любом случае,
даже если python упал. Запись атомарная: через временный файл и `os.replace`, как пишет сам алертер.

```bash
ssh $H 'systemctl stop zanity-alerter; python3 -c "
import json, os
p = \"/var/lib/zanity-alerter/state.json\"
with open(p, encoding=\"utf-8\") as f:
    s = json.load(f)
s.pop(\"history\", None)
for st in s.get(\"checks\", {}).values():
    for k in (\"hist_sample\", \"hist_at\"):
        st.pop(k, None)
with open(p + \".tmp\", \"w\", encoding=\"utf-8\") as f:
    json.dump(s, f, ensure_ascii=False, indent=1)
os.replace(p + \".tmp\", p)
print(\"cleaned\")
"; systemctl start zanity-alerter; systemctl is-active zanity-alerter'
```

Ожидается `cleaned` и `active`. Без `cleaned` state не изменился, сервис всё равно запущен.

Полный возврат состояния: при остановленном сервисе `cp -a /opt/zanity-alerter-backups/<STAMP>/state.json
/var/lib/zanity-alerter/state.json` (потеряются изменения состояния после выкладки).
