#!/usr/bin/env python3
"""Создание сессии 211766470_telethon"""
from telethon import TelegramClient
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "211766470_telethon"

async def create_session():
    print(f"\n🔐 Создание сессии: {SESSION_NAME}")
    print("="*60)
    
    phone = "+16067153072"
    print(f"📱 Телефон: {phone}")
    
    # Удаляем старую сессию
    if os.path.exists(f"{SESSION_NAME}.session"):
        os.remove(f"{SESSION_NAME}.session")
        print(f"🗑️  Старая сессия удалена")
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    await client.connect()
    
    print(f"\n📨 Отправляю код на {phone}...")
    await client.send_code_request(phone)
    
    print("\n✉️ Код отправлен в Telegram!")
    print("Введите код подтверждения:")
    code = input("Код: ").strip()
    
    try:
        await client.sign_in(phone, code)
        print("✅ Авторизация с кодом успешна!")
    except Exception as e:
        if "password" in str(e).lower() or "2FA" in str(e):
            print("\n🔒 Требуется пароль 2FA (двухфакторная аутентификация):")
            password = input("Пароль 2FA: ").strip()
            await client.sign_in(password=password)
            print("✅ Авторизация с 2FA успешна!")
        else:
            raise
    
    me = await client.get_me()
    print(f"\n{'='*60}")
    print(f"✅ СЕССИЯ СОЗДАНА УСПЕШНО!")
    print(f"{'='*60}")
    print(f"   • ID:       {me.id}")
    print(f"   • Username: @{me.username if me.username else 'не установлен'}")
    print(f"   • Имя:      {me.first_name or ''} {me.last_name or ''}")
    print(f"   • Телефон:  {me.phone}")
    print(f"   • Файл:     {SESSION_NAME}.session")
    print(f"{'='*60}\n")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(create_session())
