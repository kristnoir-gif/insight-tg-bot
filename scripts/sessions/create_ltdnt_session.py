#!/usr/bin/env python3
"""Создание сессии ltdnt_session"""
from telethon import TelegramClient
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = "ltdnt_session"
PHONE = "+79819125603"

async def create_session():
    print(f"\n🔐 Создание сессии: {SESSION_NAME}")
    print(f"📱 Телефон: {PHONE}")
    print("="*60)
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    await client.connect()
    
    if not await client.is_user_authorized():
        print(f"\n📨 Отправляю код на {PHONE}...")
        await client.send_code_request(PHONE)
        
        print("\n✉️ Код отправлен в Telegram!")
        print("Введите код подтверждения:")
        code = input("Код: ").strip()
        
        try:
            await client.sign_in(PHONE, code)
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
