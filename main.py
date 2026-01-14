"""
Точка входа приложения.
Инициализация и запуск бота.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from telethon import TelegramClient

from config import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    SESSION_NAME,
    LOG_FORMAT,
    LOG_LEVEL,
    validate_config,
)
from handlers import router, set_user_client
from db import init_db


def setup_logging() -> None:
    """Настройка логирования."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )


async def main() -> None:
    """Главная функция запуска бота."""
    setup_logging()
    logger = logging.getLogger(__name__)

    if not validate_config():
        logger.error("Конфигурация невалидна. Проверьте .env файл.")
        sys.exit(1)

    # Инициализация базы данных
    init_db()

    # Инициализация клиентов
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    user_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    try:
        # Запуск Telegram-клиента
        await user_client.start()
        set_user_client(user_client)

        logger.info("Бот успешно запущен")

        # Запуск polling
        await dp.start_polling(bot, skip_updates=True)

    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
        raise

    finally:
        await user_client.disconnect()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == '__main__':
    asyncio.run(main())
