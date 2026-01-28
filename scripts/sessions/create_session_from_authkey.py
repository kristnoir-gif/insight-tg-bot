#!/usr/bin/env python3
"""Создание Telethon сессии из auth_key и DC ID"""
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

# Данные аккаунта
SESSION_FILE = "211766470_telethon.session"
PHONE = "+16067153072"
AUTH_KEY_HEX = "5915d4015ab224469a4dd558dc0208d669d31f96c90dac95f6abd521b322500cff450f0367e2d71740f27dfae7ff2e007e61cf66eebeb8d0c1b40c08bad31a95bcc4636fec118151f29a961a680c5b1f5245120cbd2fd444e2aebc35562aa129360b9f33b10e01687b1ac9f684abb765dd1c27ee52e95c998e97e1af81121f268754b4d9ce873c9202251d6dee97c8e71b4ae8bf39af716d3fa90de0d04c4367d4dd39ab5e51fb527e1391f9cebeb98895a716b170934b847d9100fe81ce65b510bf2d432a904651b3f31667dba4fc3387792bda343d12ffe4e276864f085c3b609efcf348e819996ef40a912110b1decb17d6a076d3e570ead91f4ac9805481"
DC_ID = 1
USER_ID = 8511185686

# DC серверы Telegram
DC_SERVERS = {
    1: ("149.154.175.54", 443),
    2: ("149.154.167.51", 443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.92", 443),
    5: ("91.108.56.130", 443),
}

print(f"\n{'='*70}")
print(f"🔧 СОЗДАНИЕ TELETHON СЕССИИ ИЗ AUTH KEY")
print(f"{'='*70}\n")

# Удаляем старую сессию если есть
if os.path.exists(SESSION_FILE):
    os.remove(SESSION_FILE)
    print(f"🗑️  Удалена старая сессия: {SESSION_FILE}")

# Конвертируем hex в bytes
auth_key_bytes = bytes.fromhex(AUTH_KEY_HEX)
server_address, port = DC_SERVERS[DC_ID]

print(f"📊 Данные аккаунта:")
print(f"   • User ID:      {USER_ID}")
print(f"   • Телефон:      {PHONE}")
print(f"   • DC ID:        {DC_ID}")
print(f"   • Сервер:       {server_address}:{port}")
print(f"   • Auth Key:     {len(auth_key_bytes)} байт")

# Создаем SQLite базу данных для сессии
try:
    conn = sqlite3.connect(SESSION_FILE)
    cursor = conn.cursor()
    
    # Создаем таблицу version
    cursor.execute("CREATE TABLE version (version INTEGER PRIMARY KEY)")
    cursor.execute("INSERT INTO version VALUES (9)")  # Версия Telethon
    
    # Создаем таблицу sessions
    cursor.execute("""
        CREATE TABLE sessions (
            dc_id INTEGER PRIMARY KEY,
            server_address TEXT,
            port INTEGER,
            auth_key BLOB,
            takeout_id INTEGER
        )
    """)
    
    # Вставляем данные сессии
    cursor.execute("""
        INSERT INTO sessions (dc_id, server_address, port, auth_key, takeout_id)
        VALUES (?, ?, ?, ?, ?)
    """, (DC_ID, server_address, port, auth_key_bytes, None))
    
    # Создаем таблицу entities
    cursor.execute("""
        CREATE TABLE entities (
            id INTEGER PRIMARY KEY,
            hash INTEGER NOT NULL,
            username TEXT,
            phone INTEGER,
            name TEXT,
            date INTEGER
        )
    """)
    
    # Создаем таблицу sent_files
    cursor.execute("""
        CREATE TABLE sent_files (
            md5_digest BLOB,
            file_size INTEGER,
            type INTEGER,
            id INTEGER,
            hash INTEGER,
            PRIMARY KEY (md5_digest, file_size, type)
        )
    """)
    
    # Создаем таблицу update_state
    cursor.execute("""
        CREATE TABLE update_state (
            id INTEGER PRIMARY KEY,
            pts INTEGER,
            qts INTEGER,
            date INTEGER,
            seq INTEGER,
            unread_count INTEGER
        )
    """)
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ SQLite база создана")
    print(f"✅ Таблицы: version, sessions, entities, sent_files, update_state")
    
    # Проверяем что файл создан
    if os.path.exists(SESSION_FILE):
        file_size = os.path.getsize(SESSION_FILE)
        print(f"✅ Файл сохранен: {SESSION_FILE} ({file_size} байт)")
    
    print(f"\n{'='*70}")
    print(f"✅ СЕССИЯ УСПЕШНО СОЗДАНА!")
    print(f"{'='*70}")
    print(f"\nТеперь можно протестировать подключение:")
    print(f"python3 diagnose_session.py\n")
    
except Exception as e:
    print(f"\n❌ ОШИБКА: {e}\n")
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
    exit(1)
