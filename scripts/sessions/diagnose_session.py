#!/usr/bin/env python3
"""Диагностика сессии 211766470_telethon"""
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError
import os
from dotenv import load_dotenv
import asyncio
import sqlite3

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "211766470_telethon"

async def diagnose():
    print(f"\n{'='*70}")
    print(f"🔍 ДИАГНОСТИКА СЕССИИ: {SESSION_NAME}")
    print(f"{'='*70}\n")
    
    # Проверка файла
    session_file = f"{SESSION_NAME}.session"
    if not os.path.exists(session_file):
        print(f"❌ Файл не найден: {session_file}")
        return
    
    file_size = os.path.getsize(session_file)
    print(f"📁 Файл найден: {session_file}")
    print(f"   Размер: {file_size:,} байт")
    
    # Проверка SQLite содержимого
    print(f"\n📊 Содержимое SQLite:")
    try:
        conn = sqlite3.connect(session_file)
        cursor = conn.cursor()
        
        # Таблицы
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cursor.fetchall()]
        print(f"   Таблицы: {', '.join(tables)}")
        
        # Данные сессии
        cursor.execute("SELECT dc_id, server_address, port, auth_key IS NOT NULL FROM sessions")
        row = cursor.fetchone()
        if row:
            dc_id, server, port, has_key = row
            print(f"   DC ID: {dc_id}")
            print(f"   Сервер: {server}:{port}")
            print(f"   Auth Key: {'✅ Есть' if has_key else '❌ Нет'}")
        else:
            print(f"   ⚠️  Нет записей в таблице sessions")
        
        # Entities
        cursor.execute("SELECT COUNT(*) FROM entities")
        entities_count = cursor.fetchone()[0]
        print(f"   Entities: {entities_count}")
        
        conn.close()
    except Exception as e:
        print(f"   ❌ Ошибка чтения SQLite: {e}")
    
    # Попытка подключения через Telethon
    print(f"\n🔌 Попытка подключения через Telethon:")
    print(f"   API_ID: {API_ID}")
    print(f"   API_HASH: {API_HASH[:10]}...")
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    try:
        print(f"\n   → Подключаемся...")
        await client.connect()
        print(f"   ✅ Соединение установлено")
        
        print(f"\n   → Проверяем авторизацию...")
        is_authorized = await client.is_user_authorized()
        
        if is_authorized:
            print(f"   ✅ СЕССИЯ АВТОРИЗОВАНА!")
            me = await client.get_me()
            print(f"\n{'='*70}")
            print(f"✅ АККАУНТ АКТИВЕН:")
            print(f"{'='*70}")
            print(f"   • ID:       {me.id}")
            print(f"   • Username: @{me.username if me.username else 'нет'}")
            print(f"   • Имя:      {me.first_name or ''} {me.last_name or ''}")
            print(f"   • Телефон:  {me.phone}")
            print(f"{'='*70}\n")
        else:
            print(f"   ❌ СЕССИЯ НЕ АВТОРИЗОВАНА")
            print(f"\n💡 ПРИЧИНЫ:")
            print(f"   1. Сессия создана с другими API_ID/API_HASH")
            print(f"   2. Аккаунт был разлогинен (Terminate Session в Telegram)")
            print(f"   3. Сессия устарела (auth key истек)")
            print(f"   4. Сессия повреждена")
            
            print(f"\n🔧 РЕШЕНИЕ:")
            print(f"   Нужно пересоздать сессию с номером телефона +16067153072")
            print(f"   Команда: python3 create_211766470_session.py")
        
        await client.disconnect()
        print(f"   ✅ Отключились от Telegram\n")
        
    except Exception as e:
        print(f"   ❌ ОШИБКА: {type(e).__name__}: {e}\n")
        try:
            await client.disconnect()
        except:
            pass

if __name__ == "__main__":
    asyncio.run(diagnose())
