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
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
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
    register_user,
    get_stats,
    is_admin,
    get_all_user_ids,
    get_paid_user_ids,
    check_user_access,
    consume_analysis,
    add_paid_balance,
    set_premium,
    log_channel_analysis,
    get_top_channels,
    get_top_channels_by_subscribers,
    log_floodwait_event,
    get_floodwait_stats,
    add_pending_analysis,
    get_pending_analyses_for_user,
    remove_pending_analysis,
    FREE_DAILY_LIMIT,
    DB_PATH,
)

logger = logging.getLogger(__name__)

# Per-client cooldowns при FloodWait (каждый аккаунт независимо)
_main_cooldown_until: float = 0.0  # unix time
_backup_cooldown_until: float = 0.0
_third_cooldown_until: float = 0.0

# Режим приватного доступа (только для админа)
PRIVATE_MODE = False

# Белый список пользователей (username без @)
ALLOWED_USERS = {"ltdnt"}

# Настройки платежей (Telegram Stars)
PACK_3_PRICE = 20  # Stars за 3 анализа
PACK_10_PRICE = 75  # Stars за 10 анализов
PACK_50_PRICE = 250  # Stars за 50 анализов

# Rate limiting (защита от спама и флудвейта)
RATE_LIMIT_SECONDS = 180  # Минимальный интервал между запросами (увеличено до 3 минут)
DELAY_BETWEEN_ANALYSES = 5  # Задержка между анализами (в секундах)
_user_last_request: dict[int, float] = defaultdict(float)

# Очередь запросов (ограничение параллельных анализов)
MAX_CONCURRENT_ANALYSES = 1  # 1 анализ для снижения нагрузки на API
AVERAGE_ANALYSIS_TIME = 150  # Секунд на один анализ (для расчёта времени ожидания)
MAX_QUEUE_WAITERS = 2  # максимум ожидающих в очереди, дальше просим попробовать позже
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
        except TelegramAPIError as e:
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
_third_client: TelegramClient | None = None


def set_user_client(client: TelegramClient) -> None:
    """Устанавливает основной клиент Telegram для анализа."""
    global _user_client
    _user_client = client


def set_backup_client(client: TelegramClient) -> None:
    """Устанавливает резервный клиент Telegram для анализа."""
    global _backup_client
    _backup_client = client


def set_third_client(client: TelegramClient) -> None:
    """Устанавливает третий клиент Telegram для анализа."""
    global _third_client
    _third_client = client


def _get_main_keyboard(user_id: int = 0) -> ReplyKeyboardMarkup:
    """Создаёт основную клавиатуру."""
    keyboard = [
        [
            KeyboardButton(text="💎 Купить анализы"),
            KeyboardButton(text="❓ Помощь")
        ]
    ]
    # Добавляем кнопки админки для админов
    if is_admin(user_id):
        keyboard.append([
            KeyboardButton(text="📊 Админка"),
            KeyboardButton(text="📺 Топ каналов")
        ])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
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
                    text=f"🎁 50 анализов — {PACK_50_PRICE} ⭐",
                    callback_data="buy_pack_50"
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
        "💎 *Анализы доступны после покупки за звёзды*",
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
        "• Анализы доступны после покупки за звёзды через /buy\n\n"
        "*Команды:*\n"
        "/start — начать\n"
        "/help — эта справка\n"
        "/buy — купить анализы",
        parse_mode="Markdown",
        reply_markup=_get_main_keyboard(message.from_user.id),
    )


@router.message(Command("balance"))
async def cmd_balance(message: types.Message) -> None:
    """Показывает текущий платный баланс и статус premium пользователя."""
    user = message.from_user
    from db import check_user_access

    status = check_user_access(user.id)

    if status.is_premium:
        premium_text = f"Да, Premium до {status.premium_until.strftime('%d.%m.%Y')}" if status.premium_until else "Да (безлимитный)"
    else:
        premium_text = "Нет"

    await message.answer(
        f"📋 Статус для пользователя {user.id} (@{user.username})\n\n"
        f"💳 Платный баланс: {status.paid_balance}\n"
        f"⭐ Premium: {premium_text}\n"
        f"📅 Использовано сегодня: {status.daily_used}/{status.daily_limit}",
        parse_mode="Markdown",
        reply_markup=_get_main_keyboard(user.id),
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

    # Формируем топ каналов (по количеству анализов)
    top_channels_text = ""
    top_channels = get_top_channels(5)
    if top_channels:
        top_channels_text = "\n\n📺 *Топ-5 анализируемых каналов:*\n"
        for i, (channel_key, title, count) in enumerate(top_channels, 1):
            top_channels_text += f"{i}. {title} — {count} анализов\n"

    # Статистика по FloodWait за последние 24 часа
    fw_stats = get_floodwait_stats(days=1)

    await message.answer(
        f"📈 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"✅ Активных (сделали анализ): {stats['active_users']}\n"
        f"📊 Всего анализов: {stats['total_requests']}\n\n"
        f"🚧 FloodWait за последние 24ч:\n"
        f"• Событий: {fw_stats['total']}\n"
        f"• Пользователей: {fw_stats['users']}"
        f"{top_channels_text}",
        parse_mode="Markdown",
    )


@router.message(Command("clear_floodwait"))
async def cmd_clear_floodwait(message: types.Message) -> None:
    """Админ-команда: сброс in-memory FloodWait (обнуляет глобальную паузу)."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    globals()['_main_cooldown_until'] = 0
    globals()['_backup_cooldown_until'] = 0
    globals()['_third_cooldown_until'] = 0
    await message.answer("✅ Cooldown всех трёх аккаунтов сброшен (in-memory).")


@router.message(Command("floodstatus"))
async def cmd_floodstatus(message: types.Message) -> None:
    """Админ-команда: показать статус всех клиентов и cooldown."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    now = time.time()
    lines = ["📊 *Статус клиентов:*\n"]

    # Основной клиент
    main_status = "✅ доступен"
    if _user_client is None:
        main_status = "❌ не инициализирован"
    elif _main_cooldown_until > now:
        remaining = int(_main_cooldown_until - now)
        main_status = f"⏳ cooldown {remaining}s ({remaining // 60}m {remaining % 60}s)"
    lines.append(f"1️⃣ Main: {main_status}")

    # Backup клиент
    backup_status = "✅ доступен"
    if _backup_client is None:
        backup_status = "❌ не инициализирован"
    elif _backup_cooldown_until > now:
        remaining = int(_backup_cooldown_until - now)
        backup_status = f"⏳ cooldown {remaining}s ({remaining // 60}m {remaining % 60}s)"
    lines.append(f"2️⃣ Backup: {backup_status}")

    # Третий клиент
    third_status = "✅ доступен"
    if _third_client is None:
        third_status = "❌ не инициализирован"
    elif _third_cooldown_until > now:
        remaining = int(_third_cooldown_until - now)
        third_status = f"⏳ cooldown {remaining}s ({remaining // 60}m {remaining % 60}s)"
    lines.append(f"3️⃣ Third: {third_status}")

    # Общая доступность
    available_count = sum([
        _user_client is not None and _main_cooldown_until <= now,
        _backup_client is not None and _backup_cooldown_until <= now,
        _third_client is not None and _third_cooldown_until <= now,
    ])
    lines.append(f"\n🔢 Доступно клиентов: {available_count}/3")

    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.message(Command("clear_floodwait_db"))
async def cmd_clear_floodwait_db(message: types.Message) -> None:
    """Админ-команда: удалить все записи floodwait_events из БД."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM floodwait_events")
        total = cursor.fetchone()[0]
        cursor.execute("DELETE FROM floodwait_events")
        conn.commit()
        conn.close()
        await message.answer(f"✅ Удалено {total} записей floodwait_events из БД.")
    except sqlite3.Error as e:
        logger.error(f"Не удалось очистить floodwait_events: {e}")
        await message.answer("❌ Ошибка при очистке БД. Смотрите логи сервиса.")


@router.message(Command("send_pending"))
async def cmd_send_pending(message: types.Message, bot: Bot) -> None:
    """Админ-команда: отправить уведомление платящим пользователям о переповторных анализах."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    paid_users = get_paid_user_ids()
    
    if not paid_users:
        await message.answer("❌ Нет платящих пользователей.")
        return

    msg = await message.answer(f"📤 Отправляю уведомления {len(paid_users)} платящим пользователям...")

    success_count = 0
    for user_id in paid_users:
        try:
            status = check_user_access(user_id)
            if status.paid_balance > 0 or status.is_premium:
                pending = get_pending_analyses_for_user(user_id)
                if pending:
                    text = f"✅ У вас есть {len(pending)} незавершённых анализов:\n\n"
                    for p in pending[:5]:  # Максимум 5
                        text += f"• {p['channel_username']}\n"
                    if len(pending) > 5:
                        text += f"\n+ ещё {len(pending) - 5} анализов"
                    text += "\n\nНапишите название канала для переанализа!"
                    
                    await bot.send_message(user_id, text)
                    success_count += 1
                else:
                    # Просто уведомляем что бот работает
                    await bot.send_message(
                        user_id, 
                        "✅ Бот восстановил работу! Ваши запросы готовы к обработке."
                    )
                    success_count += 1
        except TelegramAPIError as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            continue

    await msg.edit_text(f"✅ Отправлено уведомлений: {success_count}/{len(paid_users)}")


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
        except TelegramAPIError:
            failed += 1

    await status_msg.edit_text(
        f"✅ *Рассылка завершена*\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего: {total}",
        parse_mode="Markdown",
    )

    logger.info(f"Рассылка завершена: {sent} отправлено, {failed} ошибок")


@router.message(Command("broadcast_paid"))
async def cmd_broadcast_paid(message: types.Message, bot: Bot) -> None:
    """Обработчик команды /broadcast_paid — рассылка пользователям с балансом."""
    user = message.from_user

    if not is_admin(user.id):
        logger.warning(f"Попытка рассылки от пользователя {user.id}")
        await message.answer("⛔ Доступ запрещён.")
        return

    # Извлекаем текст после команды
    text = message.text.replace("/broadcast_paid", "", 1).strip()

    if not text:
        await message.answer(
            "📢 *Рассылка платным пользователям*\n\n"
            "Использование: `/broadcast_paid Текст сообщения`\n\n"
            "Отправляет сообщение только тем, у кого paid\\_balance > 0",
            parse_mode="Markdown",
        )
        return

    user_ids = get_paid_user_ids()
    total = len(user_ids)

    if total == 0:
        await message.answer("❌ Нет пользователей с балансом для рассылки.")
        return

    status_msg = await message.answer(f"📤 Начинаю рассылку {total} платным пользователям...")

    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await bot.send_message(uid, text, parse_mode="Markdown")
            sent += 1
        except TelegramAPIError:
            failed += 1

    await status_msg.edit_text(
        f"✅ *Рассылка платным завершена*\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего платных: {total}",
        parse_mode="Markdown",
    )

    logger.info(f"Рассылка платным завершена: {sent} отправлено, {failed} ошибок")


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
        status_text = (
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
    user = callback.from_user
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 3 анализа")
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
    user = callback.from_user
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 10 анализов")
    await callback.answer()

    await callback.message.answer_invoice(
        title="Пакет 10 анализов",
        description="10 дополнительных анализов каналов",
        payload="pack_10",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="10 анализов", amount=PACK_10_PRICE)],
    )


@router.callback_query(F.data == "buy_pack_50")
async def callback_buy_pack_50(callback: types.CallbackQuery) -> None:
    """Обработчик покупки пакета 50 анализов."""
    user = callback.from_user
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 50 анализов")
    await callback.answer()

    await callback.message.answer_invoice(
        title="Пакет 50 анализов",
        description="50 дополнительных анализов каналов",
        payload="pack_50",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="50 анализов", amount=PACK_50_PRICE)],
    )


@router.callback_query(F.data == "donate")
async def callback_donate(callback: types.CallbackQuery) -> None:
    """Обработчик доната."""
    user = callback.from_user
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал донат")
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

    # Гарантируем что пользователь есть в БД перед добавлением баланса
    register_user(user.id, user.username)

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
    elif payload == "pack_50":
        add_paid_balance(user.id, 50)
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "На ваш баланс добавлено 50 анализов.\n"
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


@router.message(F.text == "📊 Админка")
async def handle_admin_button(message: types.Message) -> None:
    """Обработчик кнопки админки."""
    await cmd_admin(message)


@router.message(F.text == "📺 Топ каналов")
async def handle_top_channels_button(message: types.Message) -> None:
    """Обработчик кнопки топ каналов (по подписчикам)."""
    user = message.from_user
    if not is_admin(user.id):
        return

    top_channels = get_top_channels_by_subscribers(10)

    if not top_channels:
        await message.answer(
            "📺 *Топ каналов по подписчикам*\n\n"
            "Пока нет данных о подписчиках.\n"
            "Данные появятся после новых анализов.",
            parse_mode="Markdown",
        )
        return

    text = "📺 *Топ каналов по подписчикам:*\n\n"
    for i, (channel_key, title, subs) in enumerate(top_channels, 1):
        if subs >= 1_000_000:
            subs_str = f"{subs / 1_000_000:.1f}M"
        elif subs >= 1_000:
            subs_str = f"{subs / 1_000:.1f}K"
        else:
            subs_str = str(subs)
        text += f"{i}. @{channel_key} — {subs_str}\n   _{title}_\n"

    await message.answer(text, parse_mode="Markdown")


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
            "❌ *Нет доступных анализов.*\n\n"
            "Чтобы продолжить, купи анализы за звёзды ⭐",
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
    now = time.time()

    # Проверяем, есть ли хоть один доступный клиент (не в cooldown)
    main_available = _main_cooldown_until <= now
    backup_available = _backup_client is not None and _backup_cooldown_until <= now
    third_available = _third_client is not None and _third_cooldown_until <= now

    if not (main_available or backup_available or third_available):
        # Все клиенты в cooldown
        log_floodwait_event(user.id, str(channel), "all_cooldown_active")
        await message.answer(
            "⏳ *Все аккаунты временно ограничены (FloodWait).* \n\n"
            "Попробуйте позже.",
            parse_mode="Markdown",
        )
        return

    # Проверяем очередь
    semaphore = _get_semaphore()

    # Если семафор занят — сообщаем о загруженности с расчётом времени
    user_in_queue = False
    if semaphore.locked():
        # Если очередь уже большая — не ставим в ожидание, чтобы не долбить Telegram
        if _queue_position >= MAX_QUEUE_WAITERS:
            log_floodwait_event(user.id, str(channel), "queue_full")
            await message.answer(
                "⏳ *Бот сейчас перегружен.*\n\n"
                "Попробуйте позже.",
                parse_mode="Markdown",
            )
            return
        globals()['_queue_position'] = globals()['_queue_position'] + 1
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
        # Пересчитываем доступность клиентов (могло измениться пока ждали в очереди)
        now = time.time()
        main_available = _main_cooldown_until <= now
        backup_available = _backup_client is not None and _backup_cooldown_until <= now
        third_available = _third_client is not None and _third_cooldown_until <= now

        if not (main_available or backup_available or third_available):
            log_floodwait_event(user.id, str(channel), "all_cooldown_active_inner")
            await message.answer(
                "⏳ *Все аккаунты временно ограничены (FloodWait).* \n\n"
                "Попробуйте позже.",
                parse_mode="Markdown",
            )
            await status_msg.delete()
            return

        # Уменьшаем счётчик очереди
        if user_in_queue and _queue_position > 0:
            globals()['_queue_position'] = globals()['_queue_position'] - 1

        # Уведомляем пользователя что его очередь подошла (если ждал)
        try:
            await status_msg.edit_text("🚀 Начинаю анализ канала...\n\n⏳ Пожалуйста, подождите 1-2 минуты")
        except TelegramBadRequest:
            pass

        try:
            # Пробуем клиенты по очереди, пропуская те что в cooldown
            result = None
            floodwait_info = []  # Собираем инфо о FloodWait для уведомления админа

            # 1. Основной клиент
            if main_available:
                try:
                    result = await analyze_channel(_user_client, channel)
                except FloodWaitError as e:
                    globals()['_main_cooldown_until'] = time.time() + int(e.seconds) + 5
                    floodwait_info.append(f"main: {int(e.seconds)}s")
                    logger.warning(f"FloodWait {e.seconds}s на основном клиенте")

            # 2. Backup клиент
            if result is None and backup_available:
                await status_msg.edit_text("🔄 Переключаюсь на резервный аккаунт...")
                try:
                    result = await analyze_channel(_backup_client, channel)
                except FloodWaitError as e:
                    globals()['_backup_cooldown_until'] = time.time() + int(e.seconds) + 5
                    floodwait_info.append(f"backup: {int(e.seconds)}s")
                    logger.warning(f"FloodWait {e.seconds}s на backup клиенте")

            # 3. Третий клиент
            if result is None and third_available:
                await status_msg.edit_text("🔄 Переключаюсь на третий аккаунт...")
                try:
                    result = await analyze_channel(_third_client, channel)
                except FloodWaitError as e:
                    globals()['_third_cooldown_until'] = time.time() + int(e.seconds) + 5
                    floodwait_info.append(f"third: {int(e.seconds)}s")
                    logger.warning(f"FloodWait {e.seconds}s на третьем клиенте")

            # Если все попытки провалились
            if result is None and floodwait_info:
                log_floodwait_event(user.id, str(channel), "floodwait_all_tried")
                # Сохраняем в очередь для переанализа
                channel_key = str(channel).lstrip('@').split('/')[-1].strip().lower()
                add_pending_analysis(user.id, channel_key, str(channel))
                
                await notify_admin_flood(0, f"{channel} ({', '.join(floodwait_info)})")
                await message.answer(
                    "⏳ *Telegram временно ограничил скорость.*\n\n"
                    "Попробуйте позже.",
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

            # Добавляем задержку после анализа для избежания флудвейта
            await asyncio.sleep(DELAY_BETWEEN_ANALYSES)

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
            except TelegramBadRequest:
                pass
