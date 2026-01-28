#!/usr/bin/env python3
"""
Интерактивный скрипт для создания Telethon сессии.
Запустите локально на своём компьютере.

Использование:
    python3 create_session_interactive.py
"""
import asyncio
import sys
from telethon import TelegramClient
from config import API_ID, API_HASH


async def create_session() -> None:
    """Интерактивное создание сессии Telethon."""
    
    print("\n" + "="*50)
    print("  СОЗДАНИЕ СЕССИИ TELETHON")
    print("="*50 + "\n")
    
    phone = input("📱 Введите номер телефона (с + и кодом страны): ").strip()
    if not phone:
        print("❌ Номер не введён")
        return
    
    session_name = input("💾 Введите имя сессии (например: user_session): ").strip()
    if not session_name:
        session_name = "user_session"
    
    print(f"\n🔄 Подключаемся к Telegram...\n")
    
    client = TelegramClient(session_name, API_ID, API_HASH)
    
    try:
        await client.start(phone=phone)
        
        me = await client.get_me()
        print(f"\n" + "="*50)
        print(f"✅ СЕССИЯ СОЗДАНА УСПЕШНО!")
        print("="*50)
        print(f"   Аккаунт: @{me.username or 'без username'}")
        print(f"   ID: {me.id}")
        print(f"   Имя: {me.first_name}")
        print(f"   Файл сессии: {session_name}.session")
        print("="*50 + "\n")
        
        await client.disconnect()
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}\n")
        await client.disconnect()
        return 1
    
    return 0


if __name__ == '__main__':
    exit_code = asyncio.run(create_session())
    sys.exit(exit_code)
