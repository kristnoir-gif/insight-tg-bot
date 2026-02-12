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
from analyzer import analyze_channel_web
from utils import cleanup_analysis_files
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
    get_user_pending_queue,
    get_queue_position,
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
    format_wait_time,
    is_writing_review,
    set_writing_review,
    clear_writing_review,
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
        "/compare @ch1 @ch2 — сравнить два канала\n"
        "/buy — купить полные анализы\n"
        "/balance — ваш баланс\n"
        "/queue — статус очереди",
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


@router.message(Command("queue"))
async def cmd_queue(message: types.Message) -> None:
    """Показывает анализы пользователя в очереди."""
    user = message.from_user

    pending = get_user_pending_queue(user.id)

    if not pending:
        await message.answer(
            "📭 *Очередь пуста*\n\n"
            "У вас нет анализов в очереди.\n"
            "Отправьте юзернейм канала для анализа.",
            parse_mode="Markdown",
            reply_markup=_get_main_keyboard(user.id),
        )
        return

    text = "📋 *Ваши анализы в очереди:*\n\n"

    for i, item in enumerate(pending, 1):
        position = item["position"]
        channel = item["channel_username"]
        est_time = position * 1.5  # ~1.5 мин на анализ

        priority_icon = ""
        if item["priority"] == 2:
            priority_icon = "💎 "
        elif item["priority"] == 1:
            priority_icon = "⭐ "

        text += f"{i}. {priority_icon}`{channel}` — #{position} (≈{est_time:.0f} мин)\n"

    text += "\n_Результаты придут автоматически._"

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=_get_main_keyboard(user.id),
    )


@router.message(Command("compare"))
async def cmd_compare(message: types.Message) -> None:
    """Сравнивает два канала."""
    import asyncio
    import os
    from aiogram.types import FSInputFile
    from visualization.charts import generate_comparison_chart

    if not await _check_access(message):
        return

    user = message.from_user
    register_user(user.id, user.username)

    # Парсим аргументы: /compare @ch1 @ch2 или /compare ch1 ch2 или t.me/ch1 t.me/ch2
    text = message.text or ""
    parts = text.split()[1:]  # Убираем /compare

    if len(parts) < 2:
        await message.answer(
            "❌ *Укажите два канала для сравнения*\n\n"
            "Примеры:\n"
            "`/compare @durov @telegram`\n"
            "`/compare durov telegram`\n"
            "`/compare t.me/durov t.me/telegram`",
            parse_mode="Markdown",
        )
        return

    # Извлекаем usernames
    def extract_username(s: str) -> str:
        s = s.strip().lstrip('@')
        if 't.me/' in s:
            s = s.split('t.me/')[-1]
        return s.split('?')[0].strip()

    channel1 = extract_username(parts[0])
    channel2 = extract_username(parts[1])

    if not channel1 or not channel2:
        await message.answer(
            "❌ Не удалось распознать каналы. Проверьте формат.",
            parse_mode="Markdown",
        )
        return

    if channel1.lower() == channel2.lower():
        await message.answer("❌ Укажите два разных канала для сравнения.")
        return

    # Проверяем доступ
    access = check_user_access(user.id)
    if not access.can_analyze:
        from datetime import datetime
        now = datetime.now()
        hours_until_midnight = 24 - now.hour - (1 if now.minute > 0 else 0)
        await message.answer(
            "❌ *Дневной лимит исчерпан*\n\n"
            f"Бесплатно: {access.daily_used}/{access.daily_limit} анализов в день\n"
            f"⏰ Обновление через ~{hours_until_midnight}ч\n\n"
            "💎 Или купи анализы за звёзды для моментального доступа:",
            parse_mode="Markdown",
            reply_markup=_get_buy_keyboard(),
        )
        return

    # Проверяем rate limit (считается как 1 анализ)
    can_proceed, wait_seconds = await check_and_update_rate_limit(user.id)
    if not can_proceed:
        await message.answer(f"⏳ Подождите {format_wait_time(wait_seconds)} перед следующим запросом.")
        return

    status_msg = await message.answer("⏳ Анализирую каналы... Это займёт 20-30 секунд")

    try:
        # Параллельный веб-анализ обоих каналов (lite mode)
        result1, result2 = await asyncio.gather(
            analyze_channel_web(channel1, limit=FREE_MESSAGE_LIMIT, lite_mode=True),
            analyze_channel_web(channel2, limit=FREE_MESSAGE_LIMIT, lite_mode=True),
            return_exceptions=True,
        )

        # Проверяем ошибки
        if isinstance(result1, Exception) or result1 is None:
            await status_msg.delete()
            await message.answer(f"❌ Не удалось получить данные канала `{channel1}`", parse_mode="Markdown")
            return

        if isinstance(result2, Exception) or result2 is None:
            await status_msg.delete()
            await message.answer(f"❌ Не удалось получить данные канала `{channel2}`", parse_mode="Markdown")
            return

        # Собираем статистики для радара
        stats1 = {
            'scream': result1.stats.scream_index,
            'vocab': result1.stats.unique_count,
            'length': result1.stats.avg_len,
            'reposts': result1.stats.repost_percent,
        }
        stats2 = {
            'scream': result2.stats.scream_index,
            'vocab': result2.stats.unique_count,
            'length': result2.stats.avg_len,
            'reposts': result2.stats.repost_percent,
        }

        # Генерируем радарную диаграмму
        chart_path = generate_comparison_chart(
            result1.title, result2.title, stats1, stats2
        )

        # Формируем текстовую таблицу
        def fmt_num(n):
            if isinstance(n, float):
                return f"{n:.1f}"
            return f"{n:,}".replace(',', ' ')

        # Определяем победителей
        winners = []
        if stats1['scream'] > stats2['scream']:
            winners.append(f"🎭 Эмоциональнее: @{channel1}")
        elif stats2['scream'] > stats1['scream']:
            winners.append(f"🎭 Эмоциональнее: @{channel2}")

        if stats1['vocab'] > stats2['vocab']:
            winners.append(f"📚 Богаче словарь: @{channel1}")
        elif stats2['vocab'] > stats1['vocab']:
            winners.append(f"📚 Богаче словарь: @{channel2}")

        if stats1['length'] > stats2['length']:
            winners.append(f"📏 Длиннее посты: @{channel1}")
        elif stats2['length'] > stats1['length']:
            winners.append(f"📏 Длиннее посты: @{channel2}")

        winners_text = "\n".join(winners) if winners else "🤝 Каналы примерно равны"

        # Формируем caption
        safe_title1 = html.escape(result1.title)
        safe_title2 = html.escape(result2.title)

        caption = (
            f"📊 <b>Сравнение: {safe_title1} vs {safe_title2}</b>\n\n"
            f"┌─────────────────┬──────────┬──────────┐\n"
            f"│ <b>Метрика</b>         │ <b>Ch1</b>      │ <b>Ch2</b>      │\n"
            f"├─────────────────┼──────────┼──────────┤\n"
            f"│ Scream Index    │ {fmt_num(stats1['scream']):>8} │ {fmt_num(stats2['scream']):>8} │\n"
            f"│ Словарный запас │ {fmt_num(stats1['vocab']):>8} │ {fmt_num(stats2['vocab']):>8} │\n"
            f"│ Длина постов    │ {fmt_num(stats1['length']):>8} │ {fmt_num(stats2['length']):>8} │\n"
            f"│ Репосты %       │ {fmt_num(stats1['reposts']):>8} │ {fmt_num(stats2['reposts']):>8} │\n"
            f"└─────────────────┴──────────┴──────────┘\n\n"
            f"{winners_text}"
        )

        # Отправляем результат
        if chart_path and os.path.exists(chart_path):
            await message.answer_photo(
                photo=FSInputFile(chart_path),
                caption=caption,
                parse_mode="HTML",
            )
            # Удаляем временный файл
            try:
                os.remove(chart_path)
            except OSError:
                pass
        else:
            # Если график не сгенерирован, отправляем только текст
            await message.answer(caption, parse_mode="HTML")

        # Списываем 1 анализ
        consume_analysis(user.id, access.reason)

        # Удаляем временные файлы от анализов
        for result in [result1, result2]:
            cleanup_analysis_files(result)

        logger.info(f"Сравнение каналов {channel1} vs {channel2} для user {user.id}")
        record_analysis("success")

    except Exception as e:
        logger.exception(f"Ошибка сравнения каналов {channel1} vs {channel2}")
        await notify_admin_error(
            "Ошибка сравнения каналов",
            f"Каналы: `{channel1}` vs `{channel2}`\n👤 User: {user.id}\n💥 {type(e).__name__}: {str(e)[:200]}"
        )
        await message.answer("❌ Произошла ошибка при сравнении. Попробуйте позже.")
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass


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
        reply_markup=_get_buy_keyboard(),
    )


@router.message(F.text == "❓ Помощь")
async def handle_help_button(message: types.Message) -> None:
    """Обработчик кнопки помощи."""
    await cmd_help(message)


@router.message(F.text == "💰 Баланс")
async def handle_balance_button(message: types.Message) -> None:
    """Обработчик кнопки баланса."""
    await cmd_balance(message)


@router.message(F.text == "✍️ Написать отзыв")
async def handle_review_button(message: types.Message) -> None:
    """Обработчик кнопки «Написать отзыв»."""
    set_writing_review(message.from_user.id)
    await message.answer(
        "✍️ Напишите ваш отзыв или предложение одним сообщением.\n\n"
        "Мы отправим его разработчику.\n"
        "Для отмены нажмите /cancel",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.message(F.text == "❌ Отмена")
async def handle_cancel_review(message: types.Message) -> None:
    """Обработчик отмены отзыва."""
    clear_writing_review(message.from_user.id)
    await message.answer(
        "Отменено.",
        reply_markup=_get_main_keyboard(message.from_user.id),
    )


@router.message(F.text)
async def handle_msg(message: types.Message) -> None:
    """Обработчик текстовых сообщений с юзернеймом канала."""
    if message.text.startswith('/'):
        return

    if not await _check_access(message):
        return

    user = message.from_user

    # Перехват отзыва
    if is_writing_review(user.id):
        clear_writing_review(user.id)
        from config import ADMIN_ID
        try:
            await message.bot.send_message(
                ADMIN_ID,
                f"💬 *Новый отзыв*\n\n"
                f"От: {user.id} (@{user.username or '—'})\n\n"
                f"{message.text}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Failed to forward review to admin: {e}")
        await message.answer(
            "✅ Спасибо за отзыв! Мы обязательно прочитаем.",
            reply_markup=_get_main_keyboard(user.id),
        )
        return

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
            reply_markup=_get_buy_keyboard(),
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
        time_str = format_wait_time(wait_seconds)
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

    # Определяем режим анализа: lite для бесплатных, full для платных
    use_lite_mode = is_free_user
    msg_limit = FREE_MESSAGE_LIMIT if use_lite_mode else DEFAULT_MESSAGE_LIMIT

    # Бесплатные пользователи — веб-парсинг напрямую (освобождаем Telethon для платных)
    if is_free_user and not is_private:
        channel_str = str(channel).lstrip('@').split('/')[-1].strip()

        # Проверяем что это публичный канал (не инвайт, не ID)
        if channel_str and not channel_str.startswith('+') and not channel_str.isdigit():
            status_msg = await message.answer("🛸 Создаю облако слов... Это займёт 10-15 секунд")

            try:
                result = await analyze_channel_web(channel_str, limit=msg_limit, lite_mode=True)
                error = None if result and result.cloud_path else "empty_result"
            except Exception as e:
                logger.warning(f"Web analysis failed for {channel_str}: {e}")
                result = None
                error = str(e)
        else:
            # Приватный канал или ID — нужен Telethon
            status_msg = await message.answer("🛸 Создаю облако слов... Подождите")
            result, error = await pool.analyze(
                channel,
                use_cache=True,
                user_id=user.id,
                is_private=is_private,
                lite_mode=True,
                message_limit=msg_limit
            )
    else:
        # Платные пользователи — Telethon с приоритетом
        status_msg = await message.answer("🛸 Извлекаю смыслы... Полный анализ займёт минуту")
        result, error = await pool.analyze(
            channel,
            use_cache=True,
            user_id=user.id,
            is_private=is_private,
            lite_mode=use_lite_mode,
            message_limit=msg_limit
        )

    try:
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

                log_floodwait_event(user.id, str(channel), "all_cooldown")
                record_analysis("floodwait")
                _mark_user_floodwait(user.id)

                # Уведомляем админа
                await notify_admin_flood(wait_seconds, str(channel))

                # Определяем приоритет: 2 = платный, 1 = premium, 0 = бесплатный
                if access.paid_balance > 0:
                    priority = 2
                elif access.is_premium:
                    priority = 1
                else:
                    priority = 0

                channel_key = str(channel).lstrip('@').split('/')[-1].strip().lower()
                position = add_pending_analysis(user.id, channel_key, str(channel), priority)

                # Рассчитываем примерное время ожидания
                est_time = position * 1.5  # ~1.5 мин на анализ

                priority_text = ""
                if priority == 2:
                    priority_text = "💎 Ваш запрос имеет приоритет (платный)\n\n"
                elif priority == 1:
                    priority_text = "⭐ Ваш запрос имеет приоритет (Premium)\n\n"

                await message.answer(
                    f"⏳ *Вы #{position} в очереди* (≈{est_time:.0f} мин)\n\n"
                    f"{priority_text}"
                    f"Telegram ограничил количество запросов.\n\n"
                    f"✅ *Ваш запрос `{channel}` сохранён*\n\n"
                    f"Результат придёт автоматически.\n"
                    f"Проверить статус: /queue",
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

        # Тепловая карта — только для админа (тестовый режим)
        if is_admin(user.id) and result.heatmap_path and os.path.exists(result.heatmap_path):
            media.append(InputMediaPhoto(media=FSInputFile(result.heatmap_path)))

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
                reply_markup=_get_buy_keyboard(),
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

        cleanup_analysis_files(result)

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
