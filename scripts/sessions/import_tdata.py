"""
Импорт сессии из Telegram Desktop (Tdata) в Telethon.
Конвертирует Tdata в Telethon сессию.
"""
import asyncio
import shutil
from pathlib import Path
from telethon import TelegramClient
from telethon.client.auth import _NewAuth
from config import API_ID, API_HASH


async def import_from_tdata(tdata_path: str, session_name: str) -> None:
    """
    Импортирует сессию из Telegram Desktop Tdata в Telethon.
    
    Args:
        tdata_path: Путь к папке Tdata из Telegram Desktop
        session_name: Имя для новой Telethon сессии
    """
    tdata_path = Path(tdata_path).expanduser().resolve()
    
    if not tdata_path.exists():
        print(f"❌ Папка не найдена: {tdata_path}")
        return
    
    print(f"📁 Используем Tdata: {tdata_path}")
    
    # Создаём клиент с сессией из Tdata
    client = TelegramClient(session_name, API_ID, API_HASH)
    
    try:
        # Пытаемся подключиться к существующей сессии
        await client.connect()
        
        # Проверяем есть ли авторизация
        if not await client.is_user_authorized():
            print("⚠️ Клиент не авторизован. Требуется интерактивная авторизация.")
            await client.disconnect()
            return
        
        me = await client.get_me()
        print(f"\n✅ Сессия импортирована успешно!")
        print(f"   Аккаунт: @{me.username or 'без username'}")
        print(f"   ID: {me.id}")
        print(f"   Файл: {session_name}.session")
        
        await client.disconnect()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        await client.disconnect()


async def list_tdata_accounts(tdata_path: str) -> None:
    """Список аккаунтов в Tdata папке."""
    tdata_path = Path(tdata_path).expanduser().resolve()
    
    if not tdata_path.exists():
        print(f"❌ Папка не найдена: {tdata_path}")
        return
    
    print(f"📁 Содержимое Tdata: {tdata_path}\n")
    
    for item in sorted(tdata_path.iterdir()):
        if item.is_dir():
            print(f"   📂 {item.name}/")
        else:
            size_kb = item.stat().st_size / 1024
            print(f"   📄 {item.name} ({size_kb:.1f} KB)")


if __name__ == '__main__':
    import sys
    
    tdata_path = "/Users/kristina/kris_/bot_tg/tdata"
    
    if len(sys.argv) > 1:
        session_name = sys.argv[1]
    else:
        session_name = "imported_session"
    
    print("=== Импорт сессии из Tdata ===\n")
    
    # Сначала посмотрим что в Tdata
    asyncio.run(list_tdata_accounts(tdata_path))
    
    print(f"\n🔄 Импортируем в сессию: {session_name}\n")
    
    # Импортируем сессию
    asyncio.run(import_from_tdata(tdata_path, session_name))
