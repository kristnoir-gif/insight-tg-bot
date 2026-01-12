from telethon.sync import TelegramClient

# Вставьте ваши данные
API_ID = 34404218 
API_HASH = '26f2cb869a2293037cc21c796750e616'

with TelegramClient('web_session', API_ID, API_HASH) as client:
    print("Ура! Вы успешно авторизованы.")+