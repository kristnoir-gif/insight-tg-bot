#!/usr/bin/env bash
set -euo pipefail

# Скрипт собирает информацию о сервисе `tg-bot` и выводит редактированную версию .env
# Запускать на сервере, где размещено приложение (например: /opt/bot_tg).
# Вывод можно скопировать и прислать сюда для анализа (замаскируйте секреты при желании).

echo "== SERVICE STATUS =="
systemctl status tg-bot.service --no-pager -l || true

echo "\n== JOURNAL LAST 200 LINES =="
journalctl -u tg-bot.service -n 200 --no-pager -o cat || true

echo "\n== JOURNAL SINCE 1 HOUR AGO =="
journalctl -u tg-bot.service --since "1 hour ago" --no-pager -o cat || true

echo "\n== APP DIRECTORY LIST (/opt/bot_tg) =="
ls -la /opt/bot_tg || true

echo "\n== .env (REDACTED) =="
if [ -f /opt/bot_tg/.env ]; then
  # Показываем до 200 строк, заменяем значения на REDACTED
  sed -n '1,200p' /opt/bot_tg/.env | sed -E 's/^(\s*[^#=]+\s*=\s*).*/\1REDACTED/' || true
else
  echo ".env not found at /opt/bot_tg/.env"
fi

echo "\n== END OF REPORT =="
