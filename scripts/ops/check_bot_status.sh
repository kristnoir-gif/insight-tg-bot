#!/bin/bash

# Проверка статуса бота на сервере
# Использование: ./check_bot_status.sh [server_ip]

SERVER="${1:-your_server_ip}"
echo "🔍 Проверка бота на сервере..."

# Проверяем health endpoint
echo -e "\n📊 Health endpoint:"
curl -s "http://${SERVER}:8080/health" | python3 -m json.tool 2>/dev/null || echo "❌ Недоступен"

# Проверяем metrics endpoint
echo -e "\n📈 Metrics (первые 10 строк):"
curl -s "http://${SERVER}:8080/metrics" | head -10 || echo "❌ Недоступен"

echo -e "\n✅ Проверка завершена"
