"""
Обработчики пользовательских команд: /start, /help, /balance, анализ каналов.
"""
import os
import logging
import html
from datetime import datetime

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaPhoto

from client_pool import get_client_pool
from metrics import record_analysis
from config import DEFAULT_MESSAGE_LIMIT, FREE_MESSAGE_LIMIT
from db import (
    register_user,
    check_user_access,
    consume_analysis,
    is_admin,
    log_channel_analysis,
    log_floodwait_event,
    add_pending_analysis,
)
from handlers.common import (
    _check_access,
    _check_rate_limit,
    _update_rate_limit,
    check_and_update_rate_limit,
    _mark_user_floodwait,
    _get_emotional_tone,
    _get_main_keyboard,
    _get_buy_keyboard,
    _user_got_floodwait,
    notify_admin_flood,
    notify_admin_error,
)

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    """Обработчик команды /start."""
    if not await _check_access(message):
        return

    user = message.from_user
    register_user(user.id, user.username)

    await message.answer(
        "📊 *Добро пожаловать в Insight Bot!*\n\n"
        "Я анализирую публичные Telegram-каналы и выворачиваю их смыслы наизнанку.\n\n"
        "*Как пользоваться:*\n"
        "Отправьте юзернейм: `polozhnyak`\n"
        "Или ссылку: `t.me/polozhnyak`\n\n"
        "🆓 *Бесплатно:*\n"
        "📊 Облако ключевых слов\n"
        "📈 Топ-15 слов канала\n\n"
        "💎 *Полный анализ (за ⭐):*\n"
        "🤬 Мат-облако\n"
        "😊 Облако позитива\n"
        "😡 Облако агрессии\n"
        "🗓 Активность по дням недели\n"
        "🕐 Время публикаций\n"
        "👤 Упоминаемые личности\n"
        "💬 Популярные фразы\n"
        "😀 Топ эмодзи\n"
        "🔮 Дихотомия языка — метафизика vs быт",
        parse_mode="Markdown",
        reply_markup=_get_main_keyboard(user.id),
    )


@router.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    """Обработчик команды /help."""
    if not await _check_access(message):
        return

    await message.answer(
        "📖 *Как пользоваться ботом*\n\n"
        "*Анализ канала:*\n"
        "Отправьте юзернейм: `polozhnyak`\n"
        "Или ссылку: `t.me/polozhnyak`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🆓 *Бесплатный анализ:*\n"
        "📊 Облако ключевых слов\n"
        "📈 Топ-15 слов канала\n"
        "📏 Базовая статистика\n\n"
        "💎 *Полный анализ (за ⭐):*\n"
        "Всё из бесплатного, плюс:\n"
        "🤬 Мат-облако\n"
        "😊 Облако позитива\n"
        "😡 Облако агрессии\n"
        "🗓 Активность по дням\n"
        "🕐 Время публикаций\n"
        "👤 Упоминаемые личности\n"
        "💬 Популярные фразы\n"
        "😀 Топ-20 эмодзи\n"
        "🔮 Дихотомия языка — метафизика vs быт\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Команды:*\n"
        "/buy — купить полные анализы\n"
        "/balance — ваш баланс",
        parse_mode="Markdown",
        reply_markup=_get_main_keyboard(message.from_user.id),
    )


@router.message(Command("balance"))
async def cmd_balance(message: types.Message) -> None:
    """Показывает текущий платный баланс и статус premium."""
    user = message.from_user

    status = check_user_access(user.id)

    if status.is_premium:
        premium_text = f"Да, Premium до {status.premium_until.strftime('%d.%m.%Y')}" if status.premium_until else "Да (безлимитный)"
    else:
        premium_text = "Нет"

    text = (
        f"📋 *Статус пользователя*\n\n"
        f"💳 Платный баланс: {status.paid_balance}\n"
        f"⭐ Premium: {premium_text}\n"
        f"📅 Бесплатно сегодня: {status.daily_used}/{status.daily_limit}\n"
    )

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=_get_main_keyboard(user.id),
    )


@router.message(F.text == "⚡ Полный анализ")
async def handle_priority_access_button(message: types.Message) -> None:
    """Обработчик кнопки полного анализа."""
    user = message.from_user
    await message.answer(
        "💎 *Полный анализ канала*\n\n"
        "🆓 *Бесплатно вы получаете:*\n"
        "• Облако ключевых слов\n"
        "• Топ-15 слов\n\n"
        "💎 *В полном анализе:*\n"
        "• Всё из бесплатного\n"
        "• Анализ тональности (позитив/негатив)\n"
        "• Мат-облако\n"
        "• Активность по дням недели\n"
        "• Время публикаций\n"
        "• Упоминаемые личности\n"
        "• Популярные фразы\n"
        "• Топ-20 эмодзи\n\n"
        "Купите полные анализы:",
        parse_mode="Markdown",
        reply_markup=_get_buy_keyboard(user.id),
    )


@router.message(F.text == "❓ Помощь")
async def handle_help_button(message: types.Message) -> None:
    """Обработчик кнопки помощи."""
    await cmd_help(message)


@router.message(F.text == "💰 Баланс")
async def handle_balance_button(message: types.Message) -> None:
    """Обработчик кнопки баланса."""
    await cmd_balance(message)


@router.message(F.text)
async def handle_msg(message: types.Message) -> None:
    """Обработчик текстовых сообщений с юзернеймом канала."""
    if message.text.startswith('/'):
        return

    if not await _check_access(message):
        return

    user = message.from_user

    # Регистрируем пользователя
    register_user(user.id, user.username)

    # Проверяем если это приватный канал (начинается с +)
    is_private_channel = message.text.startswith('https://t.me/+')

    # Извлекаем username/hash из текста
    if is_private_channel:
        # Для приватных: https://t.me/+glL4HD1_l584ODAy
        try:
            username = message.text.split('https://t.me/+')[-1].split('?')[0].strip()
            if not username or '/' in username:
                await message.answer("❌ Неправильная ссылка на приватный канал. Используйте формат: https://t.me/+xxxxx")
                return
            username = '+' + username
        except Exception:
            await message.answer("❌ Ошибка обработки ссылки на приватный канал.")
            return
    else:
        # Для публичных: @channel_name или https://t.me/channel_name
        username = message.text.replace('@', '').split('/')[-1].strip()

        if not username:
            await message.answer("❌ Пожалуйста, укажите юзернейм или ссылку на канал.")
            return

    logger.info(f"Запрос анализа канала: {username} от пользователя {user.id}" + (" (ПРИВАТНЫЙ КАНАЛ)" if is_private_channel else ""))

    # Выполняем анализ
    await _perform_analysis(message, username, is_private_channel)


async def _perform_analysis(message: types.Message, channel: str | int, is_private: bool = False) -> None:
    """
    Выполняет анализ канала через ClientPool и отправляет результаты.
    """
    from db import was_analyzed_recently, get_cached_analysis

    pool = get_client_pool()
    user = message.from_user

    # Проверяем что пул инициализирован
    if pool.status()["total_accounts"] == 0:
        await message.answer("❌ Бот не готов к работе. Попробуйте позже.")
        logger.error("ClientPool пуст — нет аккаунтов")
        return

    # Проверяем доступ пользователя
    access = check_user_access(user.id)
    if not access.can_analyze:
        now = datetime.now()
        hours_until_midnight = 24 - now.hour - (1 if now.minute > 0 else 0)
        await message.answer(
            "❌ *Дневной лимит исчерпан*\n\n"
            f"Бесплатно: {access.daily_used}/{access.daily_limit} анализов в день\n"
            f"⏰ Обновление через ~{hours_until_midnight}ч\n\n"
            "💎 Или купи анализы за звёзды для моментального доступа:",
            parse_mode="Markdown",
            reply_markup=_get_buy_keyboard(user.id),
        )
        return

    # Определяем тип пользователя для priority queue
    is_paid_user = access.paid_balance > 0 or access.is_premium or is_admin(user.id)
    is_free_user = not is_paid_user

    # SMART CACHING для бесплатных пользователей
    if is_free_user:
        channel_key = str(channel).lstrip('@').split('/')[-1].strip().lower()
        was_recent, last_analyzed = was_analyzed_recently(channel_key, hours=6)

        if was_recent:
            cached = get_cached_analysis(channel_key)
            if cached:
                logger.info(f"Free user {user.id} получил кэшированный анализ {channel_key} (last analyzed: {last_analyzed})")

    # Проверяем rate limit (защита от спама) — атомарная проверка + обновление
    can_proceed, wait_seconds = await check_and_update_rate_limit(user.id)
    if not can_proceed:
        wait_minutes = wait_seconds // 60
        wait_sec_remainder = wait_seconds % 60
        if wait_minutes > 0:
            time_str = f"{wait_minutes} мин {wait_sec_remainder} сек"
        else:
            time_str = f"{wait_seconds} сек"

        if user.id in _user_got_floodwait:
            await message.answer(
                f"⏳ *Пожалуйста, подождите*\n\n"
                f"Ваш предыдущий запрос не удалось выполнить из-за ограничений Telegram.\n\n"
                f"⚠️ Повторные запросы увеличивают время ожидания для всех!\n\n"
                f"🕐 Попробуйте снова через {time_str}.",
                parse_mode="Markdown",
            )
        else:
            await message.answer(f"⏳ Подождите {time_str} перед следующим запросом.")
        return

    # PRIORITY QUEUE: Проверка доступности аккаунтов для бесплатных пользователей
    if is_free_user:
        pool_status = pool.status()
        main_account_available = False

        for acc_info in pool_status.get('accounts', []):
            if acc_info.get('name') == 'main':
                if acc_info.get('available') and not acc_info.get('busy'):
                    main_account_available = True
                break

        if not main_account_available:
            await message.answer(
                "⏳ *Бесплатная очередь перегружена*\n\n"
                "Основной аккаунт временно недоступен из-за ограничений Telegram.\n\n"
                "🔄 Попробуйте позже или воспользуйтесь платным экспресс-анализом для моментальной обработки через приоритетные аккаунты!",
                parse_mode="Markdown",
                reply_markup=_get_buy_keyboard(user.id),
            )
            log_floodwait_event(user.id, str(channel), "free_queue_overloaded")
            return

    # Определяем режим анализа: lite для бесплатных, full для платных
    use_lite_mode = is_free_user
    msg_limit = FREE_MESSAGE_LIMIT if use_lite_mode else DEFAULT_MESSAGE_LIMIT

    if use_lite_mode:
        status_msg = await message.answer("🛸 Создаю облако слов... Подождите")
    else:
        status_msg = await message.answer("🛸 Извлекаю смыслы... Полный анализ займёт минуту")

    try:
        # Выполняем анализ через ClientPool
        result, error = await pool.analyze(
            channel,
            use_cache=True,
            user_id=user.id,
            is_private=is_private,
            lite_mode=use_lite_mode,
            message_limit=msg_limit
        )

        if error:
            # Обрабатываем разные типы ошибок
            if error.startswith("web_fallback_failed:"):
                parts = error.split(":", 2)
                fail_channel = parts[1] if len(parts) > 1 else str(channel)
                fail_reason = parts[2] if len(parts) > 2 else "unknown"
                await notify_admin_error(
                    "Веб-фоллбэк не сработал",
                    f"📺 Канал: `{fail_channel}`\n👤 User: {user.id}\n"
                    f"❌ Все аккаунты недоступны И веб-парсинг упал\n💥 `{fail_reason}`"
                )
                await message.answer(
                    f"⏳ *Бот временно перегружен*\n\n"
                    f"Все аккаунты заняты и резервный способ тоже не сработал.\n\n"
                    f"🕐 Попробуйте снова через несколько минут.",
                    parse_mode="Markdown",
                )
                await status_msg.delete()
                return

            elif error.startswith("all_cooldown:"):
                wait_seconds = int(error.split(":")[1])
                wait_minutes = max(1, wait_seconds // 60)

                log_floodwait_event(user.id, str(channel), "all_cooldown")
                record_analysis("floodwait")
                _mark_user_floodwait(user.id)

                # Уведомляем админа
                await notify_admin_flood(wait_seconds, str(channel))

                channel_key = str(channel).lstrip('@').split('/')[-1].strip().lower()
                add_pending_analysis(user.id, channel_key, str(channel))

                await message.answer(
                    f"⏳ *Бот временно перегружен*\n\n"
                    f"Telegram ограничил количество запросов.\n\n"
                    f"✅ *Ваш запрос `{channel}` сохранён и будет выполнен автоматически*\n\n"
                    f"🕐 Результат придёт в течение ~{wait_minutes} мин.\n"
                    f"Ожидайте — повторно отправлять не нужно.",
                    parse_mode="Markdown",
                )
                await status_msg.delete()
                return

            elif "не канал" in error or "аккаунт пользователя" in error:
                await message.answer(
                    "👤 *Это аккаунт пользователя, а не канал*\n\n"
                    "Бот анализирует только каналы и группы.\n"
                    "Отправьте юзернейм канала или ссылку на него.",
                    parse_mode="Markdown",
                )
            elif "Could not find" in error or "Cannot find" in error or "No user has" in error:
                await message.answer(
                    "❌ *Канал не найден*\n\n"
                    "Проверьте правильность юзернейма.\n"
                    "Отправьте юзернейм без @ или ссылку на канал.",
                    parse_mode="Markdown",
                )
            elif "ограничен для анализа" in error or "restricted" in error.lower() or "api access" in error.lower():
                await notify_admin_error(
                    "Канал ограничен",
                    f"📺 Канал: `{channel}`\n👤 User: {user.id} (@{user.username or '?'})\n❌ {error[:200]}"
                )
                await message.answer(
                    "🚫 *Канал недоступен для анализа*\n\n"
                    f"К сожалению, канал `{channel}` имеет ограничения доступа в Telegram API.\n\n"
                    "Это может быть:\n"
                    "• 🤖 Канал, управляемый ботом\n"
                    "• 🔒 Канал со специальными настройками безопасности\n"
                    "• 🔐 Служебный или закрытый канал\n\n"
                    "⚠️ *К сожалению, Telegram не позволяет анализировать такие каналы.*\n\n"
                    "💡 *Рекомендация:*\n"
                    "Попробуйте анализировать другой публичный канал. "
                    "Обычно это любой открытый канал без специальных ограничений.",
                    parse_mode="Markdown",
                )
            elif "private" in error.lower() or "приватн" in error.lower():
                if is_private:
                    await message.answer(
                        "🔒 *Нет доступа к приватному каналу*\n\n"
                        "Возможные причины:\n"
                        "• Неправильная ссылка-приглашение\n"
                        "• Истекло время действия ссылки\n"
                        "• Отсутствует доступ в канал\n\n"
                        "Убедитесь, что ссылка-приглашение ещё действительна.",
                        parse_mode="Markdown",
                    )
                else:
                    await message.answer(
                        "🔒 *Канал приватный*\n\n"
                        "Бот может анализировать только публичные каналы или приватные через ссылку-приглашение.\n\n"
                        "Отправьте ссылку вида: https://t.me/+xxxxx",
                        parse_mode="Markdown",
                    )
            elif error == "empty_result":
                await message.answer("❌ Канал пуст или недоступен.")
                record_analysis("error")
            else:
                logger.error(f"❌ Ошибка анализа {channel} для user {user.id}: {error}")
                await notify_admin_error(
                    "Ошибка анализа",
                    f"📺 Канал: `{channel}`\n👤 User: {user.id} (@{user.username or '?'})\n❌ {error[:200]}"
                )
                await message.answer("❌ Ошибка анализа канала. Попробуйте позже.")
                record_analysis("error")

            await status_msg.delete()
            return

        if result is None or result.cloud_path is None:
            await message.answer("❌ Ошибка или канал пуст.")
            await status_msg.delete()
            return

        # Получаем эмоциональный тон
        emotional_tone = _get_emotional_tone(result.stats.scream_index)

        # Формируем caption в зависимости от режима
        safe_title = html.escape(result.title)
        if use_lite_mode:
            caption = (
                f"📊 <b>{safe_title}</b>\n\n"
                f"📚 Уникальных слов: {result.stats.unique_count}\n"
                f"📏 Средняя длина поста: {result.stats.avg_len} слов\n"
                f"🎭 Эмоциональный тон: {emotional_tone}\n\n"
                f"<i>Это превью. Полный анализ доступен за ⭐</i>"
            )
        else:
            caption = (
                f"📊 Канал: {safe_title}\n\n"
                f"📚 Уникальных слов: {result.stats.unique_count}\n"
                f"📏 Средняя длина поста: {result.stats.avg_len} слов\n"
                f"🎭 Эмоциональный тон: {emotional_tone}\n"
                f"👤 Упомянуто личностей: {result.stats.unique_names_count} "
                f"({result.stats.total_names_mentions} упоминаний)"
            )

        # Собираем медиагруппу
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
            await message.answer("Не удалось сформировать изображения для анализа. Попробуйте ещё раз.")
            return

        # Гарантируем, что caption есть на первом элементе
        if not media[0].caption:
            media[0].caption = caption
            media[0].parse_mode = "HTML"

        await message.answer_media_group(media=media)

        # Списываем анализ только после успешной отправки
        consume_analysis(user.id, access.reason)

        # Для lite mode — предложение купить полный анализ
        if use_lite_mode:
            await message.answer(
                "💎 <b>Хотите полный анализ?</b>\n\n"
                "В полной версии:\n"
                "• Анализ тональности (позитив/агрессия)\n"
                "• Мат-облако\n"
                "• Активность по дням и часам\n"
                "• Упоминаемые личности\n"
                "• Популярные фразы\n"
                "• Топ эмодзи\n\n"
                "Купите анализы за ⭐ и получите полный отчёт!",
                parse_mode="HTML",
                reply_markup=_get_buy_keyboard(user.id),
            )
        else:
            # Отдельное сообщение с эмодзи (только для полного анализа)
            if result.top_emojis:
                emoji_text = f"🔥 Топ-20 эмодзи канала {result.title}\n\n"
                for emo, count in result.top_emojis:
                    emoji_text += f"{emo} x {count}\n"
                await message.answer(emoji_text)

        mode_str = "lite" if use_lite_mode else "full"
        logger.info(f"Анализ канала {channel} ({mode_str}) успешно отправлен пользователю {user.id}")
        record_analysis("success")

        # Записываем в статистику каналов
        log_channel_analysis(str(channel), result.title, result.subscribers, analyzed_by=user.id)

        # Удаление временных файлов (только если не кэшированный результат)
        for path in result.get_all_paths():
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                logger.warning(f"Не удалось удалить файл {path}: {e}")

    except Exception as e:
        logger.exception(f"Неожиданная ошибка при анализе канала {channel}")
        await notify_admin_error(
            "Критическая ошибка анализа",
            f"📺 Канал: `{channel}`\n👤 User: {user.id}\n💥 `{type(e).__name__}: {str(e)[:200]}`"
        )
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

    finally:
        try:
            await status_msg.delete()
        except TelegramBadRequest:
            pass
