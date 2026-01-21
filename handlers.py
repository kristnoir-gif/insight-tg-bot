"""
Обработчики команд и сообщений Telegram-бота.
"""
import os
import logging
import time
import asyncio
from collections import defaultdict

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    Message,
)
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from analyzer import analyze_channel, AnalysisError
from db import (
    register_user, log_request, get_stats, is_admin, get_all_user_ids,
    check_user_access, consume_analysis, add_paid_balance, set_premium,
    log_channel_analysis, get_top_channels, FREE_DAILY_LIMIT,
)

logger = logging.getLogger(__name__)

# Режим приватного доступа (только для админа)
PRIVATE_MODE = False

# Белый список пользователей (username без @)
ALLOWED_USERS = {"ltdnt"}

# Настройки платежей (Telegram Stars)
PACK_3_PRICE = 20  # Stars за 3 анализа
PACK_10_PRICE = 75  # Stars за 10 анализов
PACK_WEEKLY_PRICE = 250  # Stars за неделю безлимита

# Rate limiting (защита от спама)
RATE_LIMIT_SECONDS = 60  # Минимальный интервал между запросами (было 30)
_user_last_request: dict[int, float] = defaultdict(float)

# Очередь запросов (ограничение параллельных анализов)
MAX_CONCURRENT_ANALYSES = 1  # 1 анализ для снижения нагрузки на API
AVERAGE_ANALYSIS_TIME = 120  # Секунд на один анализ (для расчёта времени ожидания)
_analysis_semaphore: asyncio.Semaphore | None = None
_queue_position: int = 0  # Счётчик ожидающих в очереди
_bot_instance: Bot | None = None  # Для отправки уведомлений из очереди


def set_bot_instance(bot: Bot) -> None:
    """Устанавливает экземпляр бота для отправки уведомлений."""
    global _bot_instance
    _bot_instance = bot


def _get_semaphore() -> asyncio.Semaphore:
    """Возвращает или создаёт семафор для очереди."""
    global _analysis_semaphore
    if _analysis_semaphore is None:
        _analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)
    return _analysis_semaphore


async def notify_admin_flood(wait_seconds: int, channel: str) -> None:
    """Уведомляет админа о FloodWait."""
    from db import ADMIN_ID
    if _bot_instance:
        try:
            await _bot_instance.send_message(
                ADMIN_ID,
                f"🚨 *FloodWait!*\n\n"
                f"Канал: `{channel}`\n"
                f"Ожидание: {wait_seconds} сек ({wait_seconds // 60} мин)\n\n"
                f"Рекомендация: подождать или использовать другой аккаунт.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить админа о FloodWait: {e}")


def _check_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    Проверяет rate limit для пользователя.

    Returns:
        (можно_продолжить, секунд_до_разблокировки)
    """
    if is_admin(user_id):
        return True, 0

    now = time.time()
    last_request = _user_last_request[user_id]
    elapsed = now - last_request

    if elapsed < RATE_LIMIT_SECONDS:
        remaining = int(RATE_LIMIT_SECONDS - elapsed)
        return False, remaining

    return True, 0


def _update_rate_limit(user_id: int) -> None:
    """Обновляет время последнего запроса."""
    _user_last_request[user_id] = time.time()


async def _check_access(message: types.Message) -> bool:
    """Проверяет доступ пользователя. Возвращает True если доступ разрешён."""
    if not PRIVATE_MODE:
        return True
    if is_admin(message.from_user.id):
        return True
    # Проверяем username в белом списке
    if message.from_user.username and message.from_user.username.lower() in ALLOWED_USERS:
        return True
    await message.answer("🔒 Бот находится в режиме тестирования. Доступ ограничен.")
    return False


def _get_emotional_tone(scream_index: float) -> str:
    """
    Преобразует числовой индекс крика в описательный эмоциональный тон.

    Args:
        scream_index: Числовой индекс (0-10+).

    Returns:
        Описание эмоционального тона.
    """
    if scream_index <= 1.5:
        return "😌 Спокойный"
    elif scream_index <= 4.0:
        return "😐 Умеренный"
    elif scream_index <= 7.0:
        return "😤 Экспрессивный"
    else:
        return "🔥 Взрывной"

router = Router()

# Ссылки на Telegram-клиенты (устанавливаются при запуске)
_user_client: TelegramClient | None = None
_backup_client: TelegramClient | None = None


def set_user_client(client: TelegramClient) -> None:
    """Устанавливает основной клиент Telegram для анализа."""
    global _user_client
    _user_client = client


def set_backup_client(client: TelegramClient) -> None:
    """Устанавливает резервный клиент Telegram для анализа."""
    global _backup_client
    _backup_client = client


def _get_main_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт основную клавиатуру."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="💎 Купить анализы"),
                KeyboardButton(text="❓ Помощь")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def _get_buy_keyboard() -> InlineKeyboardMarkup:
    """Создаёт inline-клавиатуру с вариантами покупки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🎯 3 анализа — {PACK_3_PRICE} ⭐",
                    callback_data="buy_pack_3"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📦 10 анализов — {PACK_10_PRICE} ⭐",
                    callback_data="buy_pack_10"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔥 Безлимит на неделю — {PACK_WEEKLY_PRICE} ⭐",
                    callback_data="buy_weekly"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❤️ Мне нравится бот — 1 ⭐",
                    callback_data="donate"
                )
            ],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    """Обработчик команды /start."""
    if not await _check_access(message):
        return

    user = message.from_user
    logger.info(f"Пользователь {user.id} запустил бота")

    # Регистрируем пользователя в БД
    register_user(user.id, user.username)

    await message.answer(
        "📊 *Добро пожаловать в Insight Bot!*\n\n"
        "Я анализирую публичные Telegram-каналы и выворачиваю их смыслы наизнанку.\n\n"
        "*Как пользоваться:*\n"
        "• Отправьте юзернейм: `polozhnyak`\n"
        "• Или ссылку: `t.me/polozhnyak`\n\n"
        "*Что вы получите:*\n"
        "📊 Облако ключевых слов\n"
        "📈 Топ-15 слов канала\n"
        "🎭 Анализ тональности\n"
        "🗓 Активность по дням недели\n"
        "🕐 Время публикаций\n"
        "👤 Упоминаемые личности\n"
        "💬 Популярные фразы\n"
        "😀 Топ эмодзи\n\n"
        "✨ *1 бесплатный анализ в день*",
        parse_mode="Markdown",
        reply_markup=_get_main_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    """Обработчик команды /help."""
    if not await _check_access(message):
        return

    await message.answer(
        "📖 *Как пользоваться ботом*\n\n"
        "*Анализ канала:*\n"
        "• Отправьте юзернейм: `polozhnyak`\n"
        "• Или ссылку: `t.me/polozhnyak`\n\n"
        "*Что вы получите:*\n"
        "📊 Облако ключевых слов\n"
        "📈 Топ-15 слов канала\n"
        "🎭 Анализ тональности (позитив/агрессия)\n"
        "🗓 Активность по дням недели\n"
        "🕐 Время публикаций\n"
        "👤 Упоминаемые личности\n"
        "💬 Популярные фразы\n"
        "😀 Топ эмодзи\n\n"
        "*Лимиты:*\n"
        "• 1 бесплатный анализ в день\n"
        "• Дополнительные — через /buy\n\n"
        "*Команды:*\n"
        "/start — начать\n"
        "/help — эта справка\n"
        "/buy — купить анализы",
        parse_mode="Markdown",
        reply_markup=_get_main_keyboard(),
    )


@router.message(Command("admin"))
async def cmd_admin(message: types.Message) -> None:
    """Обработчик команды /admin — статистика для администратора."""
    user = message.from_user

    if not is_admin(user.id):
        logger.warning(f"Попытка доступа к /admin от пользователя {user.id}")
        await message.answer("⛔ Доступ запрещён.")
        return

    stats = get_stats()

    # Формируем топ каналов (по подписчикам)
    top_channels_text = ""
    top_channels = get_top_channels(5)
    if top_channels:
        top_channels_text = "\n\n📺 *Топ-5 анализируемых каналов:*\n"
        for i, (channel_key, title, subs) in enumerate(top_channels, 1):
            if subs >= 1_000_000:
                subs_str = f"{subs / 1_000_000:.1f}M"
            elif subs >= 1_000:
                subs_str = f"{subs / 1_000:.1f}K"
            else:
                subs_str = str(subs)
            top_channels_text += f"{i}. {title} — {subs_str}\n"

    await message.answer(
        f"📈 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"✅ Активных (сделали анализ): {stats['active_users']}\n"
        f"📊 Всего анализов: {stats['total_requests']}"
        f"{top_channels_text}",
        parse_mode="Markdown",
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, bot: Bot) -> None:
    """Обработчик команды /broadcast — рассылка всем пользователям."""
    user = message.from_user

    if not is_admin(user.id):
        logger.warning(f"Попытка рассылки от пользователя {user.id}")
        await message.answer("⛔ Доступ запрещён.")
        return

    # Извлекаем текст после команды
    text = message.text.replace("/broadcast", "", 1).strip()

    if not text:
        await message.answer(
            "📢 *Рассылка сообщений*\n\n"
            "Использование: `/broadcast Текст сообщения`\n\n"
            "Пример: `/broadcast Привет! У нас новые функции!`",
            parse_mode="Markdown",
        )
        return

    user_ids = get_all_user_ids()
    total = len(user_ids)

    if total == 0:
        await message.answer("❌ Нет пользователей для рассылки.")
        return

    status_msg = await message.answer(f"📤 Начинаю рассылку {total} пользователям...")

    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ *Рассылка завершена*\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего: {total}",
        parse_mode="Markdown",
    )

    logger.info(f"Рассылка завершена: {sent} отправлено, {failed} ошибок")


@router.message(Command("buy"))
async def cmd_buy(message: types.Message) -> None:
    """Обработчик команды /buy — покупка анализов."""
    if not await _check_access(message):
        return

    user = message.from_user
    register_user(user.id, user.username)

    status = check_user_access(user.id)

    # Формируем информацию о текущем статусе
    status_text = ""
    if status.is_premium:
        if status.premium_until:
            status_text = f"⭐ У вас Premium до {status.premium_until.strftime('%d.%m.%Y')}\n\n"
        else:
            status_text = "⭐ У вас безлимитный доступ\n\n"
    else:
        remaining_free = max(0, status.daily_limit - status.daily_used)
        status_text = (
            f"📊 Бесплатных сегодня: {remaining_free}/{status.daily_limit}\n"
            f"💰 Платный баланс: {status.paid_balance} анализов\n\n"
        )

    await message.answer(
        f"💎 *Покупка анализов*\n\n"
        f"{status_text}"
        f"Выберите подходящий пакет:",
        parse_mode="Markdown",
        reply_markup=_get_buy_keyboard(),
    )


@router.message(F.text == "💎 Купить анализы")
async def handle_buy_button(message: types.Message) -> None:
    """Обработчик кнопки покупки в основном меню."""
    await cmd_buy(message)


@router.callback_query(F.data == "buy_pack_3")
async def callback_buy_pack_3(callback: types.CallbackQuery) -> None:
    """Обработчик покупки пакета 3 анализов."""
    await callback.answer()

    await callback.message.answer_invoice(
        title="3 анализа каналов",
        description="Проанализируйте 3 любых Telegram-канала",
        payload="pack_3",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="3 анализа", amount=PACK_3_PRICE)],
    )


@router.callback_query(F.data == "buy_pack_10")
async def callback_buy_pack_10(callback: types.CallbackQuery) -> None:
    """Обработчик покупки пакета 10 анализов."""
    await callback.answer()

    await callback.message.answer_invoice(
        title="Пакет 10 анализов",
        description="10 дополнительных анализов каналов",
        payload="pack_10",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="10 анализов", amount=PACK_10_PRICE)],
    )


@router.callback_query(F.data == "buy_weekly")
async def callback_buy_weekly(callback: types.CallbackQuery) -> None:
    """Обработчик покупки недельного безлимита."""
    await callback.answer()

    await callback.message.answer_invoice(
        title="Безлимит на неделю",
        description="Неограниченное количество анализов на 7 дней",
        payload="weekly_unlimited",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="Безлимит 7 дней", amount=PACK_WEEKLY_PRICE)],
    )


@router.callback_query(F.data == "donate")
async def callback_donate(callback: types.CallbackQuery) -> None:
    """Обработчик доната."""
    await callback.answer()

    await callback.message.answer_invoice(
        title="Поддержать бота",
        description="Спасибо, что пользуетесь ботом!",
        payload="donate",
        currency="XTR",
        prices=[LabeledPrice(label="Донат", amount=1)],
    )


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
    """Обработчик pre-checkout запроса — всегда подтверждаем."""
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    """Обработчик успешного платежа."""
    user = message.from_user
    payment = message.successful_payment
    payload = payment.invoice_payload

    logger.info(f"Успешный платёж от {user.id}: {payload}, {payment.total_amount} Stars")

    if payload == "pack_3":
        add_paid_balance(user.id, 3)
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "На ваш баланс добавлено 3 анализа.\n"
            "Отправьте юзернейм канала для анализа.",
            parse_mode="Markdown",
        )
    elif payload == "pack_10":
        add_paid_balance(user.id, 10)
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "На ваш баланс добавлено 10 анализов.\n"
            "Отправьте юзернейм канала для анализа.",
            parse_mode="Markdown",
        )
    elif payload == "weekly_unlimited":
        set_premium(user.id, 7)
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "Вам активирован безлимитный доступ на 7 дней.\n"
            "Отправьте юзернейм канала для анализа.",
            parse_mode="Markdown",
        )
    elif payload == "donate":
        await message.answer(
            "❤️ *Спасибо за поддержку!*\n\n"
            "Ваш донат очень ценен для развития бота!",
            parse_mode="Markdown",
        )


@router.message(F.text == "❓ Помощь")
async def handle_help_button(message: types.Message) -> None:
    """Обработчик кнопки помощи."""
    await cmd_help(message)


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

    # Извлекаем username из текста
    username = message.text.replace('@', '').split('/')[-1].strip()

    if not username:
        await message.answer("❌ Пожалуйста, укажите юзернейм канала.")
        return

    logger.info(f"Запрос анализа канала: {username} от пользователя {user.id}")

    # Выполняем анализ
    await _perform_analysis(message, username)


async def _perform_analysis(message: types.Message, channel: str | int) -> None:
    """
    Выполняет анализ канала и отправляет результаты.

    Args:
        message: Сообщение пользователя.
        channel: Username канала (str) или chat_id (int).
    """
    if _user_client is None:
        await message.answer("❌ Бот не готов к работе. Попробуйте позже.")
        logger.error("Telegram-клиент не инициализирован")
        return

    user = message.from_user

    # Проверяем доступ пользователя
    access = check_user_access(user.id)
    if not access.can_analyze:
        await message.answer(
            "❌ *Твои бесплатные анализы закончились!*\n\n"
            "Чтобы продолжить, купи ещё анализы за звёзды ⭐",
            parse_mode="Markdown",
            reply_markup=_get_buy_keyboard(),
        )
        return

    # Проверяем rate limit (защита от спама)
    can_proceed, wait_seconds = _check_rate_limit(user.id)
    if not can_proceed:
        await message.answer(
            f"⏳ Подождите {wait_seconds} сек. перед следующим запросом.",
        )
        return

    # Обновляем время последнего запроса
    _update_rate_limit(user.id)

    # Проверяем очередь
    semaphore = _get_semaphore()

    # Если семафор занят — сообщаем о загруженности с расчётом времени
    global _queue_position
    user_in_queue = False
    if semaphore.locked():
        _queue_position += 1
        user_in_queue = True
        wait_minutes = (_queue_position * AVERAGE_ANALYSIS_TIME) // 60 + 1
        await message.answer(
            f"⏳ *Бот сейчас загружен*\n\n"
            f"Твой анализ придёт примерно через *{wait_minutes} мин*.\n"
            f"Я пришлю уведомление, когда будет готово!",
            parse_mode="Markdown"
        )

    status_msg = await message.answer("🛸 Извлекаю смыслы... Подождите минутку")

    async with semaphore:
        # Уменьшаем счётчик очереди
        if user_in_queue and _queue_position > 0:
            _queue_position -= 1

        # Уведомляем пользователя что его очередь подошла (если ждал)
        try:
            await status_msg.edit_text("🚀 Начинаю анализ канала...")
        except Exception:
            pass

        try:
            # Telethon поддерживает как username (str), так и chat_id (int)
            # Пробуем основной клиент, при FloodWait переключаемся на резервный
            try:
                result = await analyze_channel(_user_client, channel)
            except FloodWaitError as e:
                # Уведомляем админа о FloodWait
                await notify_admin_flood(e.seconds, str(channel))

                if _backup_client is not None:
                    logger.warning(f"FloodWait {e.seconds}s на основном клиенте, пробую резервный")
                    await status_msg.edit_text("🔄 Переключаюсь на резервный канал...")
                    try:
                        result = await analyze_channel(_backup_client, channel)
                    except FloodWaitError as e2:
                        # Оба клиента заблокированы
                        await notify_admin_flood(e2.seconds, f"{channel} (backup)")
                        await message.answer(
                            "⏳ *Telegram временно ограничил скорость.*\n\n"
                            "Попробуй через 15 минут.",
                            parse_mode="Markdown"
                        )
                        await status_msg.delete()
                        return
                else:
                    logger.error(f"FloodWait {e.seconds}s, резервный клиент недоступен")
                    await message.answer(
                        "⏳ *Telegram временно ограничил скорость.*\n\n"
                        "Попробуй через 15 минут.",
                        parse_mode="Markdown"
                    )
                    await status_msg.delete()
                    return

            if result is None or result.cloud_path is None:
                await message.answer("❌ Ошибка или канал пуст.")
                await status_msg.delete()
                return

            # Списываем анализ в зависимости от типа доступа
            consume_analysis(user.id, access.reason)

            # Получаем эмоциональный тон
            emotional_tone = _get_emotional_tone(result.stats.scream_index)

            # Формируем caption со статистикой
            caption = (
                f"📊 Канал: {result.title}\n\n"
                f"📚 Уникальных слов: {result.stats.unique_count}\n"
                f"📏 Средняя длина поста: {result.stats.avg_len} слов\n"
                f"🎭 Эмоциональный тон: {emotional_tone}\n"
                f"👤 Упомянуто личностей: {result.stats.unique_names_count} "
                f"({result.stats.total_names_mentions} упоминаний)"
            )

            # Собираем медиагруппу
            media = [InputMediaPhoto(media=FSInputFile(result.cloud_path), caption=caption)]

            if result.graph_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.graph_path)))
            if result.mats_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.mats_path)))
            if result.positive_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.positive_path)))
            if result.aggressive_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.aggressive_path)))
            if result.weekday_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.weekday_path)))
            if result.hour_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.hour_path)))
            if result.names_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.names_path)))
            if result.phrases_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.phrases_path)))
            if result.dichotomy_path:
                media.append(InputMediaPhoto(media=FSInputFile(result.dichotomy_path)))

            await message.answer_media_group(media=media)

            # Отдельное сообщение с эмодзи
            if result.top_emojis:
                emoji_text = f"🔥 Топ-20 эмодзи канала {result.title}\n\n"
                for emo, count in result.top_emojis:
                    emoji_text += f"{emo} x {count}\n"
                await message.answer(emoji_text)

            logger.info(f"Анализ канала {channel} успешно отправлен пользователю {user.id}")

            # Записываем в статистику каналов
            log_channel_analysis(str(channel), result.title, result.subscribers)

            # Удаление временных файлов
            for path in result.get_all_paths():
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError as e:
                    logger.warning(f"Не удалось удалить файл {path}: {e}")

        except AnalysisError as e:
            logger.error(f"Ошибка анализа: {e}")
            error_str = str(e)
            if "Could not find the input entity" in error_str:
                await message.answer(
                    "❌ *Не удалось найти канал*\n\n"
                    "Попробуйте отправить *юзернейм* канала вместо выбора через кнопку.\n\n"
                    "Например: `polozhnyak` или `t.me/polozhnyak`",
                    parse_mode="Markdown",
                )
            elif "Cannot find any entity" in error_str:
                await message.answer(
                    "❌ *Канал не найден*\n\n"
                    "Проверьте правильность юзернейма.\n"
                    "Отправьте юзернейм без @ или ссылку на канал.",
                    parse_mode="Markdown",
                )
            elif "wait of" in error_str.lower() or "flood" in error_str.lower():
                # FloodWaitError который не был пойман раньше
                await message.answer(
                    "⏳ *Telegram ограничил запросы*\n\n"
                    "Слишком много запросов. Попробуйте через 5-10 минут.",
                    parse_mode="Markdown",
                )
            elif "private" in error_str.lower() or "приватн" in error_str.lower():
                await message.answer(
                    "🔒 *Канал приватный*\n\n"
                    "Бот может анализировать только публичные каналы.",
                    parse_mode="Markdown",
                )
            else:
                await message.answer(f"❌ Ошибка анализа канала. Попробуйте позже.")

        except Exception as e:
            logger.exception(f"Неожиданная ошибка при анализе канала {channel}")
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")

        finally:
            try:
                await status_msg.delete()
            except Exception:
                pass
