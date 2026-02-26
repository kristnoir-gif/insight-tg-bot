#!/bin/bash
# Скачивает актуальную users.db с сервера на локальную машину
# Использование: ./scripts/pull_backup.sh

set -euo pipefail

SERVER="144.31.221.196"
REMOTE_DB="/opt/bot_tg/users.db"
LOCAL_BACKUPS="/Users/kristina/kris_/bot_tg/backups"
DATE=$(date +%Y-%m-%d_%H%M)
BOT_TOKEN="${TG_BOT_TOKEN:-}"
ADMIN_CHAT_ID="${TG_ADMIN_ID:-}"

notify_tg() {
    local msg="$1"
    if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d chat_id="$ADMIN_CHAT_ID" \
            -d text="$msg" \
            -d parse_mode=Markdown > /dev/null 2>&1 || true
    fi
}

mkdir -p "$LOCAL_BACKUPS"

# Безопасный бэкап через sqlite3 на сервере, затем скачивание
if ! ssh root@$SERVER "sqlite3 $REMOTE_DB '.backup /tmp/users_backup.db'"; then
    notify_tg "🚨 *Бэкап провален*: sqlite3 backup не удался на сервере"
    echo "ERROR: sqlite3 backup failed on server" >&2
    exit 1
fi

if ! scp root@$SERVER:/tmp/users_backup.db "$LOCAL_BACKUPS/users_$DATE.db"; then
    notify_tg "🚨 *Бэкап провален*: scp не удался"
    echo "ERROR: scp failed" >&2
    exit 1
fi

cp "$LOCAL_BACKUPS/users_$DATE.db" "$LOCAL_BACKUPS/users_latest.db"

SIZE=$(du -h "$LOCAL_BACKUPS/users_$DATE.db" | cut -f1)
echo "Backup saved: $LOCAL_BACKUPS/users_$DATE.db ($SIZE)"
notify_tg "✅ *Бэкап БД*: $SIZE ($DATE)"

# Удаляем бэкапы старше 30 дней
find "$LOCAL_BACKUPS" -name 'users_2*.db' -mtime +30 -delete
