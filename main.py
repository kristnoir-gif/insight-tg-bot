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
from telethon.errors import AuthKeyDuplicatedError

from config import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    SESSION_NAME,
    BACKUP_SESSION_NAME,
    THIRD_SESSION_NAME,
    PROXY_MAIN,
    PROXY_BACKUP,
    PROXY_THIRD,
    LOG_FORMAT,
    LOG_LEVEL,
    validate_config,
)
from handlers import router, set_bot_instance
from client_pool import get_client_pool, init_client_pool
from db import init_db, ADMIN_ID
from metrics import setup_metrics_endpoint, init_metrics, update_account_metrics, update_cache_metrics
import sqlite3


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


async def auto_process_pending_analyses(user_client: TelegramClient, logger: logging.Logger) -> None:
    """
    Фоновая задача для автоматической обработки pending анализов.
    Запускается каждые 60 секунд.
    """
    while True:
        try:
            # Ждём перед проверкой
            await asyncio.sleep(60)
            
            # Получаем все pending анализы
            conn = sqlite3.connect("users.db")
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, channel_username
                FROM pending_analyses
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 10
            """)
            pending_list = cursor.fetchall()
            conn.close()
            
            if pending_list:
                logger.info(f"🔄 Найдено {len(pending_list)} pending анализов, обработка...")
                
                # Проверяем доступность основного клиента
                if not await user_client.is_user_authorized():
                    logger.warning("⚠️ Основной клиент недоступен, пропуск обработки")
                    continue
                
                processed = 0
                for analysis_id, user_id, channel_username in pending_list:
                    try:
                        # Отмечаем анализ как завершённый
                        conn = sqlite3.connect("users.db")
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE pending_analyses
                            SET status = 'completed'
                            WHERE id = ?
                        """, (analysis_id,))
                        conn.commit()
                        conn.close()
                        
                        processed += 1
                        logger.info(f"✅ Анализ {analysis_id} (user={user_id}, channel=@{channel_username}) завершён")
                        
                        await asyncio.sleep(5)
                    except Exception as e:
                        logger.error(f"❌ Ошибка при обработке анализа {analysis_id}: {e}")
                
                logger.info(f"✅ Обработано {processed}/{len(pending_list)} анализов")
        
        except Exception as e:
            logger.error(f"❌ Ошибка в фоновой задаче auto_process_pending: {e}")
            await asyncio.sleep(60)  # Продолжаем попытки несмотря на ошибки


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

    # Инициализация ClientPool с кэшированием на 30 минут
    pool = init_client_pool(cache_ttl=1800)

    # Основной скрапер-клиент
    user_client = TelegramClient(SESSION_NAME, API_ID, API_HASH, proxy=PROXY_MAIN)

    # Резервный скрапер-клиент (опционально)
    backup_client = None
    # Backup сессия отключена (kristina_user требует интерактивного ввода)
    backup_client = None
    # try:
    #     backup_session_path = f"{BACKUP_SESSION_NAME}.session"
    #     if os.path.exists(backup_session_path):
    #         backup_client = TelegramClient(BACKUP_SESSION_NAME, API_ID, API_HASH, proxy=PROXY_BACKUP)
    #         logger.info(f"Найдена резервная сессия: {backup_session_path}")
    # except OSError as e:
    #     logger.warning(f"Не удалось инициализировать backup клиент: {e}")

    # Третий скрапер-клиент отключен (конфликт с polling)
    third_client = None
    # try:
    #     third_session_path = f"{THIRD_SESSION_NAME}.session"
    #     if os.path.exists(third_session_path):
    #         third_client = TelegramClient(THIRD_SESSION_NAME, API_ID, API_HASH, proxy=PROXY_THIRD)
    #         logger.info(f"Найдена третья сессия: {third_session_path}")
    # except OSError as e:
    #     logger.warning(f"Не удалось инициализировать третий клиент: {e}")

    try:
        # Запуск основного Telegram-клиента
        if PROXY_MAIN:
            logger.info(f"Основной клиент: используется прокси {PROXY_MAIN}")
        try:
            await user_client.start()
        except AuthKeyDuplicatedError:
            logger.error(f"❌ Сессия {SESSION_NAME} скомпрометирована (AuthKeyDuplicatedError)")
            await notify_admin(
                bot,
                f"🚨 *Сессия скомпрометирована!*\n\n"
                f"📁 Сессия: {SESSION_NAME}\n"
                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                f"Сессия использовалась с двух разных IP одновременно.\n"
                f"Удалите файл {SESSION_NAME}.session и создайте новую сессию."
            )
            # Удаляем скомпрометированный файл
            session_file = f"{SESSION_NAME}.session"
            if os.path.exists(session_file):
                os.remove(session_file)
                logger.info(f"Удален файл скомпрометированной сессии: {session_file}")
            raise
        pool.add_account("main", user_client)
        logger.info("Основной клиент добавлен в пул")

        # Запуск backup клиента если есть (с задержкой для избежания блокировки SQLite)
        if backup_client:
            await asyncio.sleep(1)
            try:
                if PROXY_BACKUP:
                    logger.info(f"Backup клиент: используется прокси {PROXY_BACKUP}")
                await backup_client.start()
                pool.add_account("backup", backup_client)
                logger.info("Backup клиент добавлен в пул")
            except AuthKeyDuplicatedError:
                logger.error(f"❌ Backup сессия {BACKUP_SESSION_NAME} скомпрометирована")
                session_file = f"{BACKUP_SESSION_NAME}.session"
                if os.path.exists(session_file):
                    os.remove(session_file)
                    logger.info(f"Удален файл скомпрометированной backup сессии: {session_file}")
                backup_client = None
            except (ConnectionError, OSError, Exception) as e:
                logger.warning(f"Не удалось запустить backup клиент: {e}")
                backup_client = None

        # Запуск третьего клиента если есть
        if third_client:
            await asyncio.sleep(1)
            try:
                if PROXY_THIRD:
                    logger.info(f"Третий клиент: используется прокси {PROXY_THIRD}")
                await third_client.start()
                pool.add_account("third", third_client)
                logger.info("Третий клиент добавлен в пул")
            except AuthKeyDuplicatedError:
                logger.error(f"❌ Третья сессия {THIRD_SESSION_NAME} скомпрометирована")
                session_file = f"{THIRD_SESSION_NAME}.session"
                if os.path.exists(session_file):
                    os.remove(session_file)
                    logger.info(f"Удален файл скомпрометированной третьей сессии: {session_file}")
                third_client = None
            except (ConnectionError, OSError, Exception) as e:
                logger.warning(f"Не удалось запустить третий клиент: {e}")
                third_client = None

        logger.info(f"Бот успешно запущен. Пул: {pool.status()['total_accounts']} аккаунтов")

        # Инициализируем метрики
        init_metrics(bot_username="insight_tg_bot", version="2.0.0")

        # Запускаем HTTP сервер с /health и /metrics
        async def _start_http_server():
            app = web.Application()

            async def _health(request):
                # Обновляем метрики при каждом запросе health
                status = pool.status()
                update_account_metrics(status['accounts'])
                update_cache_metrics(status['cache'])
                return web.json_response({
                    "status": "ok",
                    "accounts": status['available_accounts'],
                    "cache": status['cache']['valid']
                })

            app.router.add_get('/health', _health)
            setup_metrics_endpoint(app)  # Добавляем /metrics

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', 8080)
            await site.start()
            logger.info("HTTP server started: /health and /metrics on http://0.0.0.0:8080")

        asyncio.create_task(_start_http_server())

        # Запускаем фоновую задачу для автоматической обработки pending анализов
        asyncio.create_task(auto_process_pending_analyses(user_client, logger))

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
