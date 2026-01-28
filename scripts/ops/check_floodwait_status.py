#!/usr/bin/env python3
"""Проверить статус флудвейта и доступные аккаунты."""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "users.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("\n" + "="*80)
print("🚨 СТАТИСТИКА ФЛУДВЕЙТА И АККАУНТОВ")
print("="*80 + "\n")

# 1. Флудвейт события
cursor.execute("""
    SELECT COUNT(*) as total, COUNT(DISTINCT user_id) as unique_users
    FROM floodwait_events
""")

total_events, unique_users = cursor.fetchone() or (0, 0)

print(f"📊 ФЛУДВЕЙТ СОБЫТИЯ:")
print(f"   Всего событий: {total_events}")
print(f"   Уникальных пользователей: {unique_users}")

# Последние события
cursor.execute("""
    SELECT user_id, channel_key, created_at
    FROM floodwait_events
    ORDER BY created_at DESC
    LIMIT 10
""")

events = cursor.fetchall()
if events:
    print(f"\n   Последние 10 событий:")
    for uid, channel, created_at in events:
        print(f"      • User {uid}: @{channel} ({created_at[:19]})")

# 2. Статистика за последние 24 часа
one_day_ago = (datetime.now() - timedelta(days=1)).isoformat()
cursor.execute("""
    SELECT COUNT(*) FROM floodwait_events WHERE created_at > ?
""", (one_day_ago,))

events_24h = cursor.fetchone()[0]
print(f"\n   За последние 24 часа: {events_24h} событий")

# 3. Аккаунты
print(f"\n" + "="*80)
print(f"🔧 АККАУНТЫ СКРАПЕРОВ:")
print(f"="*80)

# Проверяем наличие сессий
import os
session_files = [
    ("/root/bot_tg/ltdnt_session.session", "ltdnt_session (основной)"),
    ("/root/bot_tg/211766470_telethon.session", "211766470_telethon (резервный)"),
    ("/root/bot_tg/kristina_user.session", "kristina_user (третий)"),
]

print("\n📋 ФАЙЛЫ СЕССИЙ:")
for session_path, name in session_files:
    if os.path.exists(session_path):
        size = os.path.getsize(session_path)
        print(f"   ✅ {name}: {size/1024:.1f} KB")
    else:
        print(f"   ❌ {name}: НЕ НАЙДЕН")

# 4. Смотрим конфиг прокси
print(f"\n📡 ПРОКСИ В КОНФИГЕ:")
from pathlib import Path
env_path = Path(__file__).parent / ".env"

if env_path.exists():
    with open(env_path, 'r') as f:
        for line in f:
            if line.startswith("PROXY"):
                # Скрываем IP
                if "=" in line:
                    key, val = line.split("=", 1)
                    if val.strip():
                        print(f"   {key.strip()}: {'НАСТРОЕНО' if val.strip() != '' else 'ОТКЛЮЧЕНО'}")
                    else:
                        print(f"   {key.strip()}: ОТКЛЮЧЕНО")
else:
    print("   .env не найден")

print(f"\n" + "="*80)
conn.close()
print()
