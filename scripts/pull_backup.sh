#!/bin/bash
# Скачивает актуальную users.db с сервера на локальную машину
# Использование: ./scripts/pull_backup.sh

SERVER="144.31.221.196"
REMOTE_DB="/opt/bot_tg/users.db"
LOCAL_BACKUPS="/Users/kristina/kris_/bot_tg/backups"
DATE=$(date +%Y-%m-%d_%H%M)

mkdir -p "$LOCAL_BACKUPS"

# Безопасный бэкап через sqlite3 на сервере, затем скачивание
ssh root@$SERVER "sqlite3 $REMOTE_DB '.backup /tmp/users_backup.db'" && \
scp root@$SERVER:/tmp/users_backup.db "$LOCAL_BACKUPS/users_$DATE.db" && \
cp "$LOCAL_BACKUPS/users_$DATE.db" "$LOCAL_BACKUPS/users_latest.db" && \
echo "Backup saved: $LOCAL_BACKUPS/users_$DATE.db ($(du -h "$LOCAL_BACKUPS/users_$DATE.db" | cut -f1))"

# Удаляем бэкапы старше 30 дней
find "$LOCAL_BACKUPS" -name 'users_2*.db' -mtime +30 -delete
