"""
Точка входа приложения.
Инициализация и запуск бота.
"""
import asyncio
import logging
import os
import sys
import traceback
from datetime import datetime

from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from telethon import TelegramClient

from config import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    SESSION_NAME,
    BACKUP_SESSION_NAME,
    THIRD_SESSION_NAME,
    LOG_FORMAT,
    LOG_LEVEL,
    validate_config,
)
from handlers import router, set_user_client, set_backup_client, set_third_client, set_bot_instance
from db import init_db, ADMIN_ID


def setup_logging() -> None:
    """Настройка логирования."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )


async def notify_admin(bot: Bot, message: str) -> None:
    """Отправляет уведомление админу."""
    try:
        await bot.send_message(ADMIN_ID, message)
    except TelegramAPIError as e:
        logging.error(f"Не удалось отправить уведомление админу: {e}")


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
    set_bot_instance(bot)  # Для уведомлений из очереди

    # Основной скрапер-клиент
    user_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    # Резервный скрапер-клиент (опционально)
    backup_client = None
    try:
        backup_session_path = f"{BACKUP_SESSION_NAME}.session"
        if os.path.exists(backup_session_path):
            backup_client = TelegramClient(BACKUP_SESSION_NAME, API_ID, API_HASH)
            logger.info(f"Найдена резервная сессия: {backup_session_path}")
    except OSError as e:
        logger.warning(f"Не удалось инициализировать backup клиент: {e}")

    # Третий скрапер-клиент (опционально)
    third_client = None
    try:
        third_session_path = f"{THIRD_SESSION_NAME}.session"
        if os.path.exists(third_session_path):
            third_client = TelegramClient(THIRD_SESSION_NAME, API_ID, API_HASH)
            logger.info(f"Найдена третья сессия: {third_session_path}")
    except OSError as e:
        logger.warning(f"Не удалось инициализировать третий клиент: {e}")

    try:
        # Запуск основного Telegram-клиента
        await user_client.start()
        set_user_client(user_client)

        # Запуск backup клиента если есть (с задержкой для избежания блокировки SQLite)
        if backup_client:
            await asyncio.sleep(1)
            try:
                await backup_client.start()
                set_backup_client(backup_client)
                logger.info("Backup клиент запущен успешно")
            except (ConnectionError, OSError, Exception) as e:
                logger.warning(f"Не удалось запустить backup клиент: {e}")
                backup_client = None

        # Запуск третьего клиента если есть
        if third_client:
            await asyncio.sleep(1)
            try:
                await third_client.start()
                set_third_client(third_client)
                logger.info("Третий клиент запущен успешно")
            except (ConnectionError, OSError, Exception) as e:
                logger.warning(f"Не удалось запустить третий клиент: {e}")
                third_client = None

        logger.info("Бот успешно запущен")

        # Запускаем простой HTTP health endpoint в фоне
        async def _start_health():
            app = web.Application()

            async def _health(request):
                return web.json_response({"status": "ok"})

            app.router.add_get('/health', _health)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', 8080)
            await site.start()
            logger.info("Health endpoint started on http://0.0.0.0:8080/health")

        asyncio.create_task(_start_health())

        # Уведомляем админа о запуске
        await notify_admin(bot, f"✅ Бот запущен\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")

        # Запуск polling
        await dp.start_polling(bot, skip_updates=True)

    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
        # Уведомляем админа о падении
        error_text = traceback.format_exc()[-500:]  # Последние 500 символов
        await notify_admin(
            bot,
            f"🚨 *Бот упал!*\n\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"```\n{error_text}\n```"
        )
        raise

    finally:
        await user_client.disconnect()
        if backup_client:
            await backup_client.disconnect()
        if third_client:
            await third_client.disconnect()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == '__main__':
    asyncio.run(main())
