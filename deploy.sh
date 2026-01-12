#!/bin/bash

# Конфигурация сервера
SERVER="144.31.221.168"
USER="root"
PASS="v7nx4gI82IlEOTmc"
REMOTE_PATH="/opt/bot_tg"
SERVICE_NAME="tg-bot"

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Деплой на VPS ===${NC}"

# Проверка наличия sshpass
if ! command -v sshpass &> /dev/null; then
    echo -e "${RED}Ошибка: sshpass не установлен${NC}"
    echo "Установите: brew install hudochenkov/sshpass/sshpass"
    exit 1
fi

# 1. Синхронизация файлов
echo -e "${YELLOW}[1/3] Синхронизация файлов...${NC}"
sshpass -p "$PASS" rsync -avz --delete \
    --exclude '.env' \
    --exclude '*.session' \
    --exclude '*.session-journal' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude '.gitignore' \
    --exclude '*.png' \
    --exclude '.claude' \
    ./ "$USER@$SERVER:$REMOTE_PATH/"

if [ $? -ne 0 ]; then
    echo -e "${RED}Ошибка синхронизации файлов${NC}"
    exit 1
fi
echo -e "${GREEN}Файлы синхронизированы${NC}"

# 2. Перезапуск сервиса
echo -e "${YELLOW}[2/3] Перезапуск сервиса...${NC}"
sshpass -p "$PASS" ssh "$USER@$SERVER" "systemctl restart $SERVICE_NAME"

if [ $? -ne 0 ]; then
    echo -e "${RED}Ошибка перезапуска сервиса${NC}"
    exit 1
fi
echo -e "${GREEN}Сервис перезапущен${NC}"

# 3. Проверка статуса
echo -e "${YELLOW}[3/3] Проверка статуса...${NC}"
sshpass -p "$PASS" ssh "$USER@$SERVER" "systemctl status $SERVICE_NAME --no-pager -l"

echo -e "${GREEN}=== Деплой завершён ===${NC}"
