"""
Скрипт для создания сессии Telethon.
Запустите локально для авторизации нового аккаунта.

Использование:
    python create_session.py ltdnt_session
"""
import asyncio
import sys
from telethon import TelegramClient
from config import API_ID, API_HASH


async def create_session(session_name: str) -> None:
    """Создаёт сессию Telethon для указанного аккаунта."""
    print(f"\n=== Создание сессии: {session_name} ===\n")

    client = TelegramClient(session_name, API_ID, API_HASH)

    await client.start()

    me = await client.get_me()
    print(f"\n✅ Сессия создана успешно!")
    print(f"   Аккаунт: @{me.username or 'без username'}")
    print(f"   ID: {me.id}")
    print(f"   Файл: {session_name}.session")

    await client.disconnect()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python create_session.py <имя_сессии>")
        print("Пример: python create_session.py ltdnt_session")
        sys.exit(1)

    session_name = sys.argv[1]
    asyncio.run(create_session(session_name))
