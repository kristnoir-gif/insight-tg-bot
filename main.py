"""
Точка входа приложения.
Инициализация и запуск бота.
"""
import asyncio
import logging
import os
import signal
import socket
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
from handlers.common import cleanup_rate_limits, notify_admin
from client_pool import get_client_pool, init_client_pool
from config import ADMIN_ID, ADMIN_IDS, CACHE_TTL_FULL, PENDING_CHECK_INTERVAL, PENDING_BATCH_SIZE, FREE_MESSAGE_LIMIT, DEFAULT_MESSAGE_LIMIT
from db import init_db, check_user_access, consume_analysis, update_pending_status, remove_pending_analysis, get_db_connection, cleanup_old_records, DB_PATH, get_next_pending_batch, reset_processing_to_pending
from metrics import setup_metrics_endpoint, init_metrics, update_account_metrics, update_cache_metrics
from utils import format_number, format_bot_description, get_bot_stats, cleanup_analysis_files


def setup_logging() -> None:
    """Настройка логирования."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )


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
                stats = get_bot_stats()
                total_users = stats["total_users"]
                total_channels = stats["total_channels"]
                total_analyses = stats["total_analyses"]
            except Exception as db_error:
                logger.error(f"Ошибка доступа к БД при обновлении описания: {db_error}", exc_info=True)
                await asyncio.sleep(60)
                continue

            short_desc = format_bot_description(total_users, total_channels, total_analyses)
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


async def periodic_cleanup_rate_limits(logger: logging.Logger) -> None:
    """Фоновая задача: очистка устаревших записей рейт-лимитов каждые 10 минут."""
    while True:
        try:
            await asyncio.sleep(600)  # 10 минут
            removed = cleanup_rate_limits()
            if removed > 0:
                logger.info(f"Очищено {removed} устаревших записей рейт-лимитов")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка очистки рейт-лимитов: {e}")
            await asyncio.sleep(60)


async def periodic_cleanup_disk_cache(logger: logging.Logger) -> None:
    """Фоновая задача: удаление файлов дискового кэша старше 7 дней, каждые 6 часов."""
    import shutil
    from pathlib import Path
    from time import time as time_now

    cache_dir = Path("cache")
    max_age_seconds = 7 * 24 * 3600  # 7 дней

    while True:
        try:
            await asyncio.sleep(6 * 3600)  # 6 часов
            if not cache_dir.exists():
                continue

            now = time_now()
            removed = 0
            for entry in cache_dir.iterdir():
                if entry.is_dir():
                    # Проверяем возраст по meta.json или mtime директории
                    try:
                        mtime = entry.stat().st_mtime
                        if now - mtime > max_age_seconds:
                            shutil.rmtree(entry)
                            removed += 1
                    except OSError:
                        pass

            if removed > 0:
                logger.info(f"Очищено {removed} устаревших записей дискового кэша")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка очистки дискового кэша: {e}")
            await asyncio.sleep(60)


async def periodic_cleanup_old_db_records(logger: logging.Logger) -> None:
    """Фоновая задача: удаление старых floodwait_events (>30 дней), каждые 24 часа."""
    while True:
        try:
            await asyncio.sleep(24 * 3600)  # 24 часа
            deleted = cleanup_old_records(days=30)
            if deleted > 0:
                logger.info(f"Очищено {deleted} старых записей floodwait_events из БД")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка очистки старых записей БД: {e}")
            await asyncio.sleep(60)


async def _send_analysis_result(bot: Bot, user_id: int, result, use_lite: bool, channel: str) -> None:
    """Отправляет результат анализа пользователю напрямую через bot API."""
    from aiogram.types import InputMediaPhoto, FSInputFile
    import html as html_module

    safe_title = html_module.escape(result.title or str(channel))

    if use_lite:
        caption = (
            f"📊 <b>{safe_title}</b>\n\n"
            f"📚 Уникальных слов: {result.stats.unique_count}\n"
            f"📏 Средняя длина поста: {result.stats.avg_len} слов\n\n"
            f"<i>Это превью. Полный анализ доступен за ⭐</i>"
        )
    else:
        caption = (
            f"📊 Канал: {safe_title}\n\n"
            f"📚 Уникальных слов: {result.stats.unique_count}\n"
            f"📏 Средняя длина поста: {result.stats.avg_len} слов\n"
            f"👤 Упомянуто личностей: {result.stats.unique_names_count} "
            f"({result.stats.total_names_mentions} упоминаний)"
        )

    media = []
    if result.cloud_path and os.path.exists(result.cloud_path):
        media.append(InputMediaPhoto(media=FSInputFile(result.cloud_path), caption=caption, parse_mode="HTML"))

    optional_paths = [
        result.graph_path, result.mats_path, result.positive_path,
        result.aggressive_path, result.weekday_path, result.hour_path,
        result.names_path, result.phrases_path, result.dichotomy_path,
    ]
    for path in optional_paths:
        if path and os.path.exists(path):
            media.append(InputMediaPhoto(media=FSInputFile(path)))

    if not media:
        await bot.send_message(user_id, f"Анализ {channel} завершён, но не удалось сформировать изображения.")
        return

    from handlers.common import send_media_group_chunked
    await send_media_group_chunked(None, media, bot=bot, chat_id=user_id)

    if use_lite:
        await bot.send_message(
            user_id,
            f"✅ Ваш анализ `{channel}` готов!\n\n"
            "💎 Хотите полный анализ? Напишите /buy",
            parse_mode="Markdown",
        )
    elif result.top_emojis:
        emoji_text = f"🔥 Топ-20 эмодзи канала {result.title}\n\n"
        for emo, count in result.top_emojis:
            emoji_text += f"{emo} x {count}\n"
        await bot.send_message(user_id, emoji_text)

    cleanup_analysis_files(result)


async def auto_process_pending_analyses(bot: Bot, logger: logging.Logger) -> None:
    """
    Фоновая задача: автоматически выполняет pending анализы.

    Особенности:
    - Проверка каждые 30 секунд (настраивается в PENDING_CHECK_INTERVAL)
    - Обработка до 5 анализов за раз (PENDING_BATCH_SIZE)
    - Приоритеты: платные (2) → premium (1) → бесплатные (0)
    - Уведомление пользователя о начале обработки
    """
    from aiogram.exceptions import TelegramForbiddenError

    while True:
        try:
            await asyncio.sleep(PENDING_CHECK_INTERVAL)

            pool = get_client_pool()
            pool_status = pool.status()
            available = pool_status.get('available_accounts', 0)

            if available == 0:
                continue  # Нет свободных аккаунтов — ждём

            # Берём pending с учётом приоритетов
            pending_list = get_next_pending_batch(limit=PENDING_BATCH_SIZE)

            if not pending_list:
                continue

            logger.info(f"🔄 Auto-retry: найдено {len(pending_list)} pending анализов (available accounts: {available})")

            # Обрабатываем анализы
            tasks = []
            for analysis_id, user_id, channel_key, channel_username, priority in pending_list:
                # Ставим статус 'processing' чтобы не взять повторно
                update_pending_status(analysis_id, 'processing')
                tasks.append(
                    _process_single_pending(
                        bot, pool, logger,
                        analysis_id, user_id, channel_key, channel_username, priority
                    )
                )

            # Выполняем параллельно (но не больше чем доступно аккаунтов)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except asyncio.CancelledError:
            logger.info("auto_process_pending_analyses cancelled")
            break
        except Exception as e:
            logger.error(f"auto_process_pending error: {e}")
            await asyncio.sleep(60)


async def _process_single_pending(
    bot: Bot,
    pool,
    logger: logging.Logger,
    analysis_id: int,
    user_id: int,
    channel_key: str,
    channel_username: str,
    priority: int
) -> None:
    """Обрабатывает один pending анализ."""
    from aiogram.exceptions import TelegramForbiddenError

    try:
        # Проверяем доступ пользователя
        access = check_user_access(user_id)
        if not access.can_analyze:
            update_pending_status(analysis_id, 'skipped')
            return

        # Определяем режим
        is_paid = access.paid_balance > 0 or access.is_premium or user_id in ADMIN_IDS
        use_lite = not is_paid
        msg_limit = FREE_MESSAGE_LIMIT if use_lite else DEFAULT_MESSAGE_LIMIT

        # Уведомляем пользователя о начале обработки
        try:
            await bot.send_message(
                user_id,
                f"🚀 Ваш анализ `{channel_username}` начался!",
                parse_mode="Markdown"
            )
        except TelegramForbiddenError:
            # Пользователь заблокировал бота
            remove_pending_analysis(analysis_id)
            logger.info(f"User {user_id} blocked bot, removing pending")
            return
        except Exception as notify_error:
            logger.warning(f"Failed to notify user {user_id}: {notify_error}")

        # Выполняем анализ
        result, error = await pool.analyze(
            channel_username, use_cache=True,
            user_id=user_id, lite_mode=use_lite,
            message_limit=msg_limit,
        )

        if error:
            if error.startswith("all_cooldown:"):
                # Снова cooldown — вернуть в pending
                update_pending_status(analysis_id, 'pending')
                logger.info(f"Auto-retry: {channel_username} returned to pending (cooldown)")
            else:
                update_pending_status(analysis_id, 'failed')
                logger.warning(f"Auto-retry failed: {channel_username}: {error}")
            return

        # Отправляем результат пользователю
        await _send_analysis_result(bot, user_id, result, use_lite, channel_username)
        consume_analysis(user_id, access.reason)
        remove_pending_analysis(analysis_id)

        priority_label = {2: "paid", 1: "premium", 0: "free"}.get(priority, "unknown")
        logger.info(f"✅ Auto-retry: {channel_username} → user {user_id} (priority={priority_label})")

    except TelegramForbiddenError:
        # Пользователь заблокировал бота
        remove_pending_analysis(analysis_id)
        logger.info(f"User {user_id} blocked bot, removing pending")
    except Exception as e:
        update_pending_status(analysis_id, 'pending')
        logger.error(f"Auto-retry error for {channel_username}: {e}")


def _sd_notify(state: str) -> None:
    """Отправляет уведомление systemd через sd_notify протокол."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        sock.sendto(state.encode(), addr)
        sock.close()
    except OSError:
        pass


async def _watchdog_loop(logger: logging.Logger) -> None:
    """Фоновая задача: отправка WATCHDOG=1 каждые 50 секунд (WatchdogSec=120)."""
    while True:
        try:
            await asyncio.sleep(50)
            _sd_notify("WATCHDOG=1")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Watchdog loop error: {e}")
            await asyncio.sleep(10)


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
    pool = init_client_pool(cache_ttl=CACHE_TTL_FULL)

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

    # Трекинг фоновых задач
    background_tasks: list[asyncio.Task] = []
    shutdown_event = asyncio.Event()

    def _schedule_task(coro, name: str = "") -> asyncio.Task:
        """Создаёт фоновую задачу и добавляет в список для трекинга."""
        task = asyncio.create_task(coro, name=name)
        background_tasks.append(task)
        return task

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
            await notify_admin(error_msg)
            raise RuntimeError("Нет доступных Telethon клиентов. Бот не может работать без них.")

        # Уведомляем админа о проблемных сессиях
        if failed_sessions:
            await notify_admin(
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

                # Проверяем доступность БД
                db_ok = False
                try:
                    with get_db_connection() as conn:
                        conn.execute("SELECT 1")
                        db_ok = True
                except Exception:
                    pass

                # Проверяем наличие доступных аккаунтов
                has_accounts = status['available_accounts'] > 0

                # Определяем общий статус
                if db_ok and has_accounts:
                    health_status = "ok"
                elif db_ok:
                    health_status = "degraded"  # БД работает, но нет аккаунтов
                else:
                    health_status = "unhealthy"

                response = {
                    "status": health_status,
                    "db": "ok" if db_ok else "error",
                    "accounts": status['available_accounts'],
                    "total_accounts": status['total_accounts'],
                    "cache": status['cache']['valid']
                }

                # Возвращаем 503 если unhealthy
                status_code = 200 if health_status != "unhealthy" else 503
                return web.json_response(response, status=status_code)

            app.router.add_get('/health', _health)
            setup_metrics_endpoint(app)  # Добавляем /metrics

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', 8080)
            await site.start()
            logger.info("HTTP server started: /health and /metrics on http://0.0.0.0:8080")

        _schedule_task(_start_http_server(), "http_server")

        # Запускаем фоновые задачи
        _schedule_task(auto_process_pending_analyses(bot, logger), "auto_pending")
        _schedule_task(update_bot_description(bot, logger), "bot_description")
        _schedule_task(periodic_cleanup_rate_limits(logger), "cleanup_rate_limits")
        _schedule_task(periodic_cleanup_disk_cache(logger), "cleanup_disk_cache")
        _schedule_task(periodic_cleanup_old_db_records(logger), "cleanup_old_records")
        _schedule_task(_watchdog_loop(logger), "watchdog")
        _sd_notify("READY=1")

        # Signal handlers для graceful shutdown
        loop = asyncio.get_running_loop()

        def _handle_signal(sig: signal.Signals) -> None:
            logger.info(f"Получен сигнал {sig.name}, начинаю graceful shutdown...")
            shutdown_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _handle_signal, sig)

        # Обновляем описание сразу при старте
        try:
            stats = get_bot_stats()
            total_users = stats["total_users"]
            total_channels = stats["total_channels"]
            total_analyses = stats["total_analyses"]

            short_desc = format_bot_description(total_users, total_channels, total_analyses)
            await bot.set_my_short_description(short_description=short_desc)
            logger.info(f"✅ Описание бота установлено: {total_users} users, {total_channels} channels, {total_analyses} analyses")
        except TelegramAPIError as api_error:
            logger.error(f"Ошибка Telegram API: {api_error}", exc_info=True)
        except Exception as e:
            logger.error(f"Неожиданная ошибка при установке описания бота: {e}", exc_info=True)

        # Уведомляем админа о запуске
        await notify_admin(f"✅ Бот запущен\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")

        # Запуск polling в отдельной задаче для возможности graceful shutdown
        polling_task = asyncio.create_task(
            dp.start_polling(bot, skip_updates=True), name="polling"
        )

        # Ждём сигнала завершения или завершения polling
        done, _ = await asyncio.wait(
            [polling_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Graceful shutdown
        if shutdown_event.is_set():
            logger.info("Graceful shutdown: останавливаю polling...")
            await dp.stop_polling()
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
        # Уведомляем админа о падении
        error_text = traceback.format_exc()[-500:]  # Последние 500 символов
        await notify_admin(
            f"🚨 *Бот упал!*\n\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"```\n{error_text}\n```"
        )
        raise

    finally:
        _sd_notify("STOPPING=1")

        # Отменяем все фоновые задачи
        for task in background_tasks:
            if not task.done():
                task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
            logger.info(f"Отменено {len(background_tasks)} фоновых задач")

        # Сбрасываем processing → pending
        reset_count = reset_processing_to_pending()
        if reset_count > 0:
            logger.info(f"Сброшено {reset_count} processing анализов в pending")

        # Уведомляем админа об остановке
        await notify_admin(f"⏹ Бот остановлен\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")

        for client in active_clients:
            try:
                await client.disconnect()
            except Exception:
                pass
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == '__main__':
    asyncio.run(main())
