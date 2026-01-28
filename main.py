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


async def update_bot_description(bot: Bot, logger: logging.Logger) -> None:
    """
    Фоновая задача для обновления описания бота с количеством пользователей.
    Запускается каждый час.
    """
    while True:
        try:
            await asyncio.sleep(3600)  # Каждый час

            # Получаем статистику
            try:
                conn = sqlite3.connect("users.db", timeout=5.0)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users")
                total_users = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM channel_stats")
                total_channels = cursor.fetchone()[0]
                cursor.execute("SELECT SUM(analysis_count) FROM channel_stats")
                result = cursor.fetchone()
                total_analyses = result[0] if result and result[0] else 0
                conn.close()
            except sqlite3.Error as db_error:
                logger.error(f"Ошибка доступа к БД при обновлении описания: {db_error}", exc_info=True)
                await asyncio.sleep(60)
                continue

            # Форматируем числа
            def format_number(n: int) -> str:
                if n >= 1000:
                    return f"{n/1000:.1f}K".replace(".0K", "K")
                return str(n)

            # Обновляем short_description (показывается в шапке)
            short_desc = (
                f"📊 Анализ Telegram-каналов\n"
                f"👥 {format_number(total_users)} пользователей\n"
                f"📈 {format_number(total_channels)} каналов | {format_number(total_analyses)} анализов"
            )

            await bot.set_my_short_description(short_description=short_desc)
            logger.info(f"✅ Описание бота обновлено: {total_users} users, {total_channels} channels, {total_analyses} analyses")

        except asyncio.CancelledError:
            logger.info("Фоновая задача обновления описания отменена")
            break
        except TelegramAPIError as api_error:
            logger.error(f"Ошибка Telegram API при обновлении описания: {api_error}", exc_info=True)
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Неожиданная ошибка обновления описания бота: {e}", exc_info=True)
            await asyncio.sleep(60)


async def auto_process_pending_analyses(bot: Bot, logger: logging.Logger) -> None:
    """
    Фоновая задача для уведомления пользователей о pending анализах.
    Запускается каждые 5 минут. Уведомляет пользователей, что они могут повторить запрос.
    """
    while True:
        try:
            # Ждём 5 минут перед проверкой
            await asyncio.sleep(300)

            # Получаем старые pending анализы (старше 10 минут)
            conn = sqlite3.connect("users.db")
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, channel_username
                FROM pending_analyses
                WHERE status = 'pending'
                AND created_at < datetime('now', '-10 minutes')
                ORDER BY created_at ASC
                LIMIT 5
            """)
            pending_list = cursor.fetchall()
            conn.close()

            if not pending_list:
                continue

            logger.info(f"🔄 Найдено {len(pending_list)} старых pending анализов")

            # Проверяем доступность клиента для анализа
            pool = get_client_pool()
            pool_status = pool.status()
            has_available_account = pool_status.get('available_accounts', 0) > 0

            for analysis_id, user_id, channel_username in pending_list:
                try:
                    if has_available_account:
                        # Уведомляем пользователя что можно повторить запрос
                        await bot.send_message(
                            user_id,
                            f"✅ *Бот снова доступен!*\n\n"
                            f"Ваш запрос на анализ `{channel_username}` не был выполнен ранее.\n"
                            f"Отправьте название канала ещё раз для анализа.",
                            parse_mode="Markdown"
                        )

                    # Удаляем из очереди (пользователь должен сам повторить)
                    conn = sqlite3.connect("users.db")
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE pending_analyses
                        SET status = 'notified'
                        WHERE id = ?
                    """, (analysis_id,))
                    conn.commit()
                    conn.close()

                    logger.info(f"📨 Уведомлён user={user_id} о канале @{channel_username}")
                    await asyncio.sleep(2)  # Пауза между уведомлениями

                except TelegramAPIError as e:
                    logger.warning(f"Не удалось уведомить {user_id}: {e}")
                except Exception as e:
                    logger.error(f"❌ Ошибка при обработке анализа {analysis_id}: {e}")

        except Exception as e:
            logger.error(f"❌ Ошибка в фоновой задаче auto_process_pending: {e}")
            await asyncio.sleep(60)


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

    # Инициализация ClientPool с кэшированием на 2 часа (снижение FloodWait)
    pool = init_client_pool(cache_ttl=7200)

    # Список клиентов для отключения в finally
    active_clients: list[TelegramClient] = []
    failed_sessions: list[str] = []

    async def try_start_client(
        session_name: str,
        proxy: dict | None,
        account_name: str
    ) -> TelegramClient | None:
        """Пытается запустить Telethon клиент. Возвращает клиент или None при ошибке."""
        session_path = f"{session_name}.session"
        if not os.path.exists(session_path):
            logger.info(f"Сессия {session_name} не найдена, пропускаем")
            return None

        try:
            client = TelegramClient(session_name, API_ID, API_HASH, proxy=proxy)
            if proxy:
                logger.info(f"{account_name} клиент: используется прокси")
            # Используем raise_self_error=False чтобы не требовать интерактивного ввода
            await client.connect()
            if not await client.is_user_authorized():
                logger.error(f"❌ Сессия {session_name} не авторизована (требуется переавторизация)")
                failed_sessions.append(session_name)
                await client.disconnect()
                return None
            pool.add_account(account_name, client)
            active_clients.append(client)
            logger.info(f"✅ {account_name} клиент ({session_name}) добавлен в пул")
            return client
        except EOFError:
            logger.error(f"❌ Сессия {session_name} требует повторной авторизации")
            failed_sessions.append(session_name)
            return None
        except AuthKeyDuplicatedError:
            logger.error(f"❌ Сессия {session_name} скомпрометирована (AuthKeyDuplicatedError)")
            failed_sessions.append(session_name)
            # Удаляем скомпрометированный файл
            if os.path.exists(session_path):
                os.remove(session_path)
                logger.info(f"Удален файл скомпрометированной сессии: {session_path}")
            return None
        except (ConnectionError, OSError, Exception) as e:
            logger.warning(f"❌ Не удалось запустить {account_name} клиент ({session_name}): {e}")
            return None

    try:
        # Запускаем все клиенты с небольшими задержками
        await try_start_client(SESSION_NAME, PROXY_MAIN, "main")
        await asyncio.sleep(0.5)
        await try_start_client(BACKUP_SESSION_NAME, PROXY_BACKUP, "backup")
        await asyncio.sleep(0.5)
        await try_start_client(THIRD_SESSION_NAME, PROXY_THIRD, "third")

        # Проверяем что хотя бы один клиент запустился
        if pool.status()['total_accounts'] == 0:
            error_msg = (
                f"🚨 *Все сессии невалидны!*\n\n"
                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                f"Невалидные сессии: {', '.join(failed_sessions) if failed_sessions else 'нет файлов сессий'}\n\n"
                f"Запустите `python create_session.py <имя>` на сервере."
            )
            await notify_admin(bot, error_msg)
            raise RuntimeError("Нет доступных Telethon клиентов. Бот не может работать без них.")

        # Уведомляем админа о проблемных сессиях
        if failed_sessions:
            await notify_admin(
                bot,
                f"⚠️ *Некоторые сессии невалидны*\n\n"
                f"📁 Проблемные: `{', '.join(failed_sessions)}`\n"
                f"✅ Работают: {pool.status()['total_accounts']} аккаунтов\n\n"
                f"Бот продолжает работу с оставшимися сессиями."
            )

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

        # Запускаем фоновую задачу для уведомления о pending анализах
        asyncio.create_task(auto_process_pending_analyses(bot, logger))

        # Запускаем фоновую задачу для обновления описания бота
        asyncio.create_task(update_bot_description(bot, logger))

        # Обновляем описание сразу при старте
        try:
            conn = sqlite3.connect("users.db", timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM channel_stats")
            total_channels = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(analysis_count) FROM channel_stats")
            result = cursor.fetchone()
            total_analyses = result[0] if result and result[0] else 0
            conn.close()

            # Форматируем числа (3000 → "3K")
            def format_number(n: int) -> str:
                if n >= 1000:
                    return f"{n/1000:.1f}K".replace(".0K", "K")
                return str(n)

            short_desc = (
                f"📊 Анализ Telegram-каналов\n"
                f"👥 {format_number(total_users)} пользователей\n"
                f"📈 {format_number(total_channels)} каналов | {format_number(total_analyses)} анализов"
            )
            await bot.set_my_short_description(short_description=short_desc)
            logger.info(f"✅ Описание бота установлено: {total_users} users, {total_channels} channels, {total_analyses} analyses")
        except sqlite3.Error as db_error:
            logger.error(f"Ошибка БД при установке описания: {db_error}", exc_info=True)
        except TelegramAPIError as api_error:
            logger.error(f"Ошибка Telegram API: {api_error}", exc_info=True)
        except Exception as e:
            logger.error(f"Неожиданная ошибка при установке описания бота: {e}", exc_info=True)

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
        for client in active_clients:
            try:
                await client.disconnect()
            except Exception:
                pass
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == '__main__':
    asyncio.run(main())
