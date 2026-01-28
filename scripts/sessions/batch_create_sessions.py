#!/usr/bin/env python3
"""
Создание сессий для известных аккаунтов.
Отредактируйте ACCOUNTS и запустите на локальной машине.
"""
import asyncio
from pathlib import Path
from telethon import TelegramClient
from config import API_ID, API_HASH


# ОТРЕДАКТИРУЙТЕ ЭТОТ СЛОВАРЬ с вашими номерами телефонов и именами сессий
ACCOUNTS = {
    "211766470_telethon": "+16067153072",   # Номер 1
    "kristina_user": "+995599658203",       # Номер 2
}


async def create_session_for_account(phone: str, session_name: str) -> bool:
    """Создаёт одну сессию для аккаунта."""
    
    session_file = Path(session_name + ".session")
    if session_file.exists():
        print(f"⏭️  {session_name}: файл сессии уже существует, пропускаем")
        return True
    
    print(f"\n🔄 Создаём сессию для {session_name} ({phone})...")
    
    client = TelegramClient(session_name, API_ID, API_HASH)
    
    try:
        await client.start(phone=phone)
        
        me = await client.get_me()
        print(f"✅ {session_name}:")
        print(f"   @{me.username or 'без username'} (ID: {me.id})")
        
        await client.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ {session_name}: Ошибка - {e}")
        return False


async def main():
    """Создаёт все сессии."""
    
    print("\n" + "="*60)
    print("  СОЗДАНИЕ СЕССИЙ TELETHON")
    print("="*60)
    
    if not ACCOUNTS:
        print("\n⚠️  ACCOUNTS пуст! Отредактируйте скрипт и добавьте:")
        print("   ACCOUNTS = {")
        print('       "session_name": "+79999999999",')
        print("   }")
        return
    
    results = []
    for session_name, phone in ACCOUNTS.items():
        success = await create_session_for_account(phone, session_name)
        results.append((session_name, success))
    
    print(f"\n" + "="*60)
    print("  РЕЗУЛЬТАТЫ")
    print("="*60)
    for session_name, success in results:
        status = "✅" if success else "❌"
        print(f"{status} {session_name}")
    print("="*60 + "\n")


if __name__ == '__main__':
    asyncio.run(main())
