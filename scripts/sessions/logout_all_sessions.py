#!/usr/bin/env python3
"""
Завершает все активные сессии бота (выход из Telegram).
Это решает проблему "Conflict: terminated by other getUpdates request".
"""
import asyncio
from pathlib import Path
from telethon import TelegramClient
from config import API_ID, API_HASH


async def logout_session(session_name: str) -> bool:
    """Выполняет logout для сессии."""
    session_file = Path(session_name + ".session")
    
    if not session_file.exists():
        print(f"⏭️  {session_name}: файл не найден")
        return True
    
    print(f"\n🔄 Выполняем logout для {session_name}...")
    
    client = TelegramClient(session_name, API_ID, API_HASH)
    
    try:
        await client.connect()
        await client.log_out()
        print(f"✅ {session_name}: успешный выход из Telegram")
        await client.disconnect()
        return True
        
    except Exception as e:
        print(f"⚠️  {session_name}: {e}")
        await client.disconnect()
        return False


async def main():
    """Выполняет logout для всех сессий."""
    
    print("\n" + "="*60)
    print("  ЗАВЕРШЕНИЕ СЕССИЙ TELETHON")
    print("="*60)
    
    sessions = [
        "211766470_telethon",
        "kristina_user",
        "ltdnt_session",
    ]
    
    results = []
    for session_name in sessions:
        success = await logout_session(session_name)
        results.append((session_name, success))
    
    print(f"\n" + "="*60)
    print("  РЕЗУЛЬТАТЫ")
    print("="*60)
    for session_name, success in results:
        status = "✅" if success else "⚠️"
        print(f"{status} {session_name}")
    print("="*60 + "\n")


if __name__ == '__main__':
    asyncio.run(main())
