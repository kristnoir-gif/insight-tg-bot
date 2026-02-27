#!/bin/bash
# Проверяет целостность последнего бэкапа БД
# Использование: ./scripts/verify_backup.sh [путь_к_бд]
# По умолчанию проверяет backups/users_latest.db

set -euo pipefail

DB_PATH="${1:-/Users/kristina/kris_/bot_tg/backups/users_latest.db}"
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

# Проверяем что файл существует
if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: файл не найден: $DB_PATH" >&2
    notify_tg "🚨 *Верификация бэкапа*: файл не найден"
    exit 1
fi

# Размер файла
SIZE=$(du -h "$DB_PATH" | cut -f1)
SIZE_BYTES=$(wc -c < "$DB_PATH" | tr -d ' ')

if [ "$SIZE_BYTES" -lt 1024 ]; then
    echo "ERROR: бэкап слишком маленький ($SIZE)" >&2
    notify_tg "🚨 *Верификация бэкапа*: файл слишком маленький ($SIZE)"
    exit 1
fi

# integrity_check
INTEGRITY=$(sqlite3 "$DB_PATH" "PRAGMA integrity_check;" 2>&1)
if [ "$INTEGRITY" != "ok" ]; then
    echo "ERROR: integrity_check провалился: $INTEGRITY" >&2
    notify_tg "🚨 *Верификация бэкапа*: integrity_check failed"
    exit 1
fi

# Проверяем наличие таблиц
TABLES=$(sqlite3 "$DB_PATH" ".tables" 2>&1)
REQUIRED=("users" "payments" "pending_analyses" "channel_stats")
MISSING=()
for t in "${REQUIRED[@]}"; do
    if ! echo "$TABLES" | grep -qw "$t"; then
        MISSING+=("$t")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "ERROR: отсутствуют таблицы: ${MISSING[*]}" >&2
    notify_tg "🚨 *Верификация бэкапа*: нет таблиц: ${MISSING[*]}"
    exit 1
fi

# Подсчёт записей
USERS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM users;" 2>&1)
PAYMENTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM payments;" 2>&1)
CHANNELS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM channel_stats;" 2>&1)

echo "=== Верификация бэкапа ==="
echo "Файл:    $DB_PATH ($SIZE)"
echo "Целостность: OK"
echo "Таблицы: OK (${#REQUIRED[@]}/${#REQUIRED[@]})"
echo "---"
echo "Users:    $USERS"
echo "Payments: $PAYMENTS"
echo "Channels: $CHANNELS"
echo "=== OK ==="

notify_tg "✅ *Бэкап верифицирован*: $SIZE | $USERS users, $PAYMENTS payments"
