"""
Обработчики команд и сообщений Telegram-бота.
"""
import os
import logging
import time
import asyncio
import json
import sqlite3
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

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
    WebAppInfo,
)
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from analyzer import AnalysisError
from client_pool import get_client_pool
from metrics import record_analysis, record_floodwait, record_payment
from config import DEFAULT_MESSAGE_LIMIT, FREE_MESSAGE_LIMIT
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
    get_top_paid_users,
    get_payment_stats,
    get_users_with_pending_and_balance,
    log_payment,
    log_buy_click,
    get_buy_funnel,
    get_all_channels_for_admin,
    FREE_DAILY_LIMIT,
    DB_PATH,
)

logger = logging.getLogger(__name__)

# Режим приватного доступа (только для админа)
PRIVATE_MODE = False

# Белый список пользователей (username без @)
ALLOWED_USERS = {"ltdnt"}

# Настройки платежей (Telegram Stars) — A/B тест цен
# Группа A (user_id чётный) — текущие цены
PRICES_A = {'pack_1': 10, 'pack_3': 20, 'pack_10': 50}
# Группа B (user_id нечётный) — x5
PRICES_B = {'pack_1': 50, 'pack_3': 100, 'pack_10': 250}
SUPPORT_PRICE = 100 # Stars поддержка проекта

def get_ab_group(user_id: int) -> str:
    """Возвращает A/B группу пользователя."""
    return "a" if user_id % 2 == 0 else "b"

def get_prices(user_id: int) -> dict:
    """Возвращает цены для пользователя по его A/B группе."""
    return PRICES_A if get_ab_group(user_id) == "a" else PRICES_B

# Rate limiting (защита от спама и флудвейта)
RATE_LIMIT_SECONDS = 600  # 10 минут между запросами (снижение FloodWait)
FLOODWAIT_RATE_LIMIT = 3600  # 60 минут если пользователь получил FloodWait
_user_last_request: dict[int, float] = defaultdict(float)
_user_got_floodwait: dict[int, float] = {}  # Когда пользователь получил FloodWait

_bot_instance: Bot | None = None  # Для отправки уведомлений


def set_bot_instance(bot: Bot) -> None:
    """Устанавливает экземпляр бота для отправки уведомлений."""
    global _bot_instance
    _bot_instance = bot


async def notify_admin_flood(wait_seconds: int, channel: str) -> None:
    """Уведомляет админа о FloodWait."""
    from db import ADMIN_ID
    if _bot_instance:
        try:
            pool = get_client_pool()
            status = pool.status()
            accounts_info = ""
            for acc in status.get('accounts', []):
                state = "✅" if acc.get('available') else f"⏳ {acc.get('cooldown_remaining', 0)//60}мин"
                accounts_info += f"  {acc['name']}: {state}\n"

            await _bot_instance.send_message(
                ADMIN_ID,
                f"🚨 *Все аккаунты в FloodWait!*\n\n"
                f"Канал: `{channel}`\n"
                f"Ожидание: ~{wait_seconds // 60} мин\n\n"
                f"📊 Аккаунты:\n{accounts_info}",
                parse_mode="Markdown"
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось уведомить админа о FloodWait: {e}")


async def notify_admin_paid_user_error(user_id: int, username: str, channel: str, error: str) -> None:
    """Уведомляет админа об ошибке анализа платного пользователя."""
    from db import ADMIN_ID
    if _bot_instance:
        try:
            await _bot_instance.send_message(
                ADMIN_ID,
                f"⚠️ *Ошибка анализа платного пользователя*\n\n"
                f"👤 Пользователь: {user_id} (@{username})\n"
                f"📺 Канал: `{channel}`\n"
                f"❌ Ошибка: {error[:100]}...",
                parse_mode="Markdown"
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось уведомить админа об ошибке платного пользователя: {e}")


async def notify_admin_error(error_type: str, details: str) -> None:
    """Уведомляет админа о любой ошибке/поломке."""
    from db import ADMIN_ID
    if _bot_instance:
        try:
            await _bot_instance.send_message(
                ADMIN_ID,
                f"🔴 *{error_type}*\n\n{details[:500]}",
                parse_mode="Markdown"
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось уведомить админа: {e}")


def _check_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    Проверяет rate limit для пользователя.

    Returns:
        (можно_продолжить, секунд_до_разблокировки)
    """
    if is_admin(user_id):
        return True, 0

    now = time.time()

    # Если пользователь недавно получил FloodWait — увеличенный лимит
    if user_id in _user_got_floodwait:
        floodwait_time = _user_got_floodwait[user_id]
        elapsed_since_fw = now - floodwait_time
        if elapsed_since_fw < FLOODWAIT_RATE_LIMIT:
            remaining = int(FLOODWAIT_RATE_LIMIT - elapsed_since_fw)
            return False, remaining
        else:
            # Очищаем запись
            del _user_got_floodwait[user_id]

    last_request = _user_last_request[user_id]
    elapsed = now - last_request

    if elapsed < RATE_LIMIT_SECONDS:
        remaining = int(RATE_LIMIT_SECONDS - elapsed)
        return False, remaining

    return True, 0


def _mark_user_floodwait(user_id: int) -> None:
    """Помечает что пользователь столкнулся с FloodWait."""
    _user_got_floodwait[user_id] = time.time()


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


def _get_main_keyboard(user_id: int = 0) -> ReplyKeyboardMarkup:
    """Создаёт основную клавиатуру."""
    from db import check_user_access

    # Проверяем статус пользователя
    access = check_user_access(user_id)
    is_paid = access.paid_balance > 0 or access.is_premium

    keyboard = [
        [
            KeyboardButton(text="💎 Купить анализы"),
            KeyboardButton(text="💰 Баланс")
        ],
        [
            KeyboardButton(text="❓ Помощь")
        ]
    ]

    # Для бесплатных пользователей показываем кнопку "Полный анализ"
    if not is_paid and not is_admin(user_id):
        keyboard.insert(0, [
            KeyboardButton(text="⚡ Полный анализ")
        ])

    # Добавляем кнопки админки для админов
    if is_admin(user_id):
        keyboard.append([
            KeyboardButton(text="📊 Админка")
        ])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def _get_buy_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Создаёт inline-клавиатуру с вариантами покупки (цены зависят от A/B группы)."""
    prices = get_prices(user_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✨ 1 полный анализ — {prices['pack_1']} ⭐",
                    callback_data="buy_pack_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🎯 3 полных анализа — {prices['pack_3']} ⭐",
                    callback_data="buy_pack_3"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"💎 10 полных анализов — {prices['pack_10']} ⭐",
                    callback_data="buy_pack_10"
                )
            ],
            [
                InlineKeyboardButton(
                    text="😍 Мне нравится бот — 1 ⭐",
                    callback_data="donate"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"❤️ Поддержать проект — {SUPPORT_PRICE} ⭐",
                    callback_data="support"
                )
            ],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    """Обработчик команды /start с поддержкой реферальных ссылок."""
    if not await _check_access(message):
        return

    user = message.from_user
    
    # Извлекаем реферальный код из deep link (если есть)
    referrer_id = None
    if message.text and len(message.text.split()) > 1:
        parts = message.text.split()
        if len(parts) == 2 and parts[1].startswith('ref'):
            try:
                referrer_id = int(parts[1][3:])  # ref12345 -> 12345
                if referrer_id == user.id:
                    referrer_id = None  # Нельзя пригласить себя
            except ValueError:
                pass
    
    # Регистрируем пользователя (с реферером если есть)
    is_new = register_user(user.id, user.username, referrer_id)
    
    if is_new and referrer_id:
        # Уведомляем нового пользователя о бонусе
        logger.info(f"Новый пользователь {user.id} пришел по реферальной ссылке от {referrer_id}")
        await message.answer(
            "🎁 *Бонус за приглашение!*\n\n"
            "Вы получили +1 анализ за переход по реферальной ссылке!\n"
            "Ваш друг тоже получил бонус 🎉",
            parse_mode="Markdown"
        )
        
        # Уведомляем реферера
        try:
            if _bot_instance:
                await _bot_instance.send_message(
                    referrer_id,
                    f"🎉 *Новый реферал!*\n\n"
                    f"@{user.username or 'пользователь'} присоединился по вашей ссылке!\n"
                    f"Вы оба получили +1 анализ 🎁",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Не удалось уведомить реферера {referrer_id}: {e}")

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
    """Показывает текущий платный баланс, статус premium и рефералов."""
    user = message.from_user
    from db import check_user_access

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


@router.message(Command("admin"))
async def cmd_admin(message: types.Message) -> None:
    """Обработчик команды /admin — статистика для администратора."""
    user = message.from_user

    if not is_admin(user.id):
        logger.warning(f"Попытка доступа к /admin от пользователя {user.id}")
        await message.answer("⛔ Доступ запрещён.")
        return

    stats = get_stats()
    logger.info(f"📊 Admin stats: total_requests={stats['total_requests']}, active={stats['active_users']}, users={stats['total_users']}")

    # Статистика по FloodWait за последние 24 часа
    fw_stats = get_floodwait_stats(days=1)

    # Inline-клавиатура с командами
    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=" Статус пула", callback_data="admin_floodstatus"),
                InlineKeyboardButton(text="🧹 Очистить кэш", callback_data="admin_clear_cache")
            ]
        ]
    )

    await message.answer(
        f"📈 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"📊 Всего анализов: {stats['total_requests']}\n\n"
        f"🚧 FloodWait за последние 24ч:\n"
        f"• Событий: {fw_stats['total']}\n"
        f"• Пользователей: {fw_stats['users']}\n\n"
        f"🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}",
        parse_mode="Markdown",
        reply_markup=admin_keyboard,
    )


@router.message(Command("clear_floodwait"))
async def cmd_clear_floodwait(message: types.Message) -> None:
    """Админ-команда: сброс cooldown всех аккаунтов."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    pool = get_client_pool()
    pool.clear_cooldowns()
    await message.answer("✅ Cooldown всех аккаунтов сброшен.")


@router.message(Command("floodstatus"))
async def cmd_floodstatus(message: types.Message) -> None:
    """Админ-команда: показать статус пула клиентов."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    pool = get_client_pool()
    await message.answer(pool.status_text(), parse_mode="Markdown")


@router.message(Command("update_description"))
async def cmd_update_description(message: types.Message) -> None:
    """Админ-команда: обновить описание бота прямо сейчас."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    try:
        # Получаем статистику
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM channel_stats")
        total_channels = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(analysis_count) FROM channel_stats")
        result = cursor.fetchone()
        total_analyses = result[0] if result and result[0] else 0
        conn.close()

        # Форматируем числа
        def format_number(n: int) -> str:
            if n >= 1000:
                return f"{n/1000:.1f}K".replace(".0K", "K")
            return str(n)

        short_desc = (
            f"📊 Анализ Telegram-каналов\n"
            f"👥 {format_number(total_users)} пользователей\n"
            f"📈 {format_number(total_channels)} каналов | {format_number(total_analyses)} анализов"
        )

        # Обновляем описание
        await _bot_instance.set_my_short_description(short_description=short_desc)
        
        await message.answer(
            f"✅ *Описание бота обновлено!*\n\n"
            f"👥 {total_users} пользователей\n"
            f"📊 {total_channels} каналов\n"
            f"📈 {total_analyses} анализов",
            parse_mode="Markdown"
        )
        logger.info(f"✅ Описание обновлено вручную админом {user.id}")
    except Exception as e:
        logger.error(f"Ошибка при обновлении описания: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("clear_cache"))
async def cmd_clear_cache(message: types.Message) -> None:
    """Админ-команда: очистить кэш результатов."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    pool = get_client_pool()
    cache_stats = pool.status()["cache"]
    pool.clear_cache()
    await message.answer(f"✅ Кэш очищен. Было {cache_stats['valid']} записей.")


@router.message(Command("clear_floodwait_db"))
async def cmd_clear_floodwait_db(message: types.Message) -> None:
    """Админ-команда: удалить все записи floodwait_events из БД."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    try:
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


@router.message(Command("paid_users"))
async def cmd_paid_users(message: types.Message) -> None:
    """Админ-команда: показать платящих пользователей и тех кто не получил результаты."""
    from db import get_top_paid_users, get_payment_stats, get_users_with_pending_and_balance
    
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    # Статистика платежей
    stats = get_payment_stats()
    
    # Топ платящих
    top_users = get_top_paid_users(10)
    
    # Пользователи с проблемами (оплатили но не получили)
    problematic = get_users_with_pending_and_balance()
    
    # Воронка покупок
    funnel = get_buy_funnel()

    text = (
        f"💰 *Статистика платежей:*\n\n"
        f"👥 Платящих пользователей: {stats.get('unique_users', 0)}\n"
        f"💳 Всего платежей: {stats.get('total_payments', 0)}\n"
        f"⭐ Всего звёзд: {stats.get('total_stars', 0)}\n"
    )

    if funnel:
        text += f"\n📊 *Воронка A/B теста:*\n"
        text += f"_A = текущие цены, B = x5_\n\n"
        for group in ['a', 'b']:
            prices = PRICES_A if group == 'a' else PRICES_B
            menu = funnel.get(f'open_menu_{group}', {'clicks': 0, 'users': 0})
            text += f"*Группа {group.upper()}* ({prices['pack_1']}/{prices['pack_3']}/{prices['pack_10']}⭐):\n"
            text += f"  Открыли меню: {menu['clicks']} ({menu['users']} чел.)\n"
            for pack in ['pack_1', 'pack_3', 'pack_10']:
                key = f'{pack}_{group}'
                if key in funnel:
                    f = funnel[key]
                    text += f"  Выбрали {pack}: {f['clicks']} ({f['users']} чел.)\n"
            text += "\n"

    if top_users:
        text += f"\n🏆 *Топ-5 платящих:*\n"
        for i, u in enumerate(top_users[:5], 1):
            text += f"{i}. @{u['username']} — {u['total_stars']}⭐ ({u['payment_count']} платежей)\n"

    if problematic:
        text += f"\n⚠️ *ВНИМАНИЕ! Не получили результаты ({len(problematic)}):*\n"
        for u in problematic[:10]:
            text += f"• @{u['username']} — {u['pending_count']} незавершённых анализов (баланс: {u['balance']})\n"

    await message.answer(text, parse_mode="Markdown")


@router.message(Command("payments"))
async def cmd_payments(message: types.Message) -> None:
    """Админ-команда: показать отчёт по платежам."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Платящие пользователи
    cursor.execute("""
        SELECT 
            u.user_id,
            u.username,
            u.paid_balance,
            COUNT(p.id) as payment_count,
            SUM(p.stars) as total_stars
        FROM users u
        LEFT JOIN payments p ON u.user_id = p.user_id
        WHERE u.paid_balance > 0 OR p.id IS NOT NULL
        GROUP BY u.user_id
        ORDER BY COALESCE(SUM(p.stars), 0) DESC
    """)
    
    rows = cursor.fetchall()
    
    text = "💳 *ОТЧЁТ ПО ПЛАТЕЖАМ*\n\n"
    
    if not rows:
        text += "❌ Нет данных о платежах\n"
    else:
        total_users = 0
        total_stars = 0
        
        for uid, username, balance, payment_count, total in rows:
            uname = f"@{username}" if username else "нет username"
            balance = balance or 0
            total = total or 0
            
            text += f"• {uname}: баланс={balance}, ⭐={total}\n"
            
            total_users += 1
            total_stars += total
        
        text += f"\n*Итого:*\n"
        text += f"👥 Платящих: {total_users}\n"
        text += f"⭐ Звёзд: {total_stars}\n"
    
    # Проверяем таблицу payments
    cursor.execute("SELECT COUNT(*) FROM payments")
    payments_count = cursor.fetchone()[0]
    
    text += f"\n📋 Таблица payments: {payments_count} записей"
    
    if payments_count == 0:
        text += "\n⚠️ ВНИМАНИЕ: Платежи не логируются!"
    
    conn.close()
    
    await message.answer(text, parse_mode="Markdown")


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


@router.message(Command("stats"))
async def cmd_stats(message: types.Message) -> None:
    """Админ-команда: графики статистики по базе данных."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer("📊 Генерирую графики...")

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()

    chart_paths = []

    try:
        # === 1. Новые пользователи по дням (последние 30 дней) ===
        cursor.execute("""
            SELECT DATE(first_seen) as day, COUNT(*) as cnt
            FROM users
            WHERE first_seen >= datetime('now', '-30 days')
            GROUP BY day ORDER BY day
        """)
        user_rows = cursor.fetchall()

        if user_rows:
            days = [datetime.strptime(r[0], "%Y-%m-%d") for r in user_rows]
            counts = [r[1] for r in user_rows]

            # Кумулятивный рост
            cursor.execute("SELECT COUNT(*) FROM users WHERE first_seen < datetime('now', '-30 days')")
            base_users = cursor.fetchone()[0]
            cumulative = []
            total = base_users
            for c in counts:
                total += c
                cumulative.append(total)

            fig, ax1 = plt.subplots(figsize=(12, 5))
            ax1.bar(days, counts, color='#6c5ce7', alpha=0.7, label='Новых за день')
            ax1.set_ylabel('Новых за день', color='#6c5ce7')
            ax1.tick_params(axis='y', labelcolor='#6c5ce7')

            ax2 = ax1.twinx()
            ax2.plot(days, cumulative, color='#d63031', linewidth=2, label='Всего')
            ax2.set_ylabel('Всего пользователей', color='#d63031')
            ax2.tick_params(axis='y', labelcolor='#d63031')

            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax1.xaxis.set_major_locator(mdates.DayLocator(interval=3))
            fig.autofmt_xdate()
            plt.title('Пользователи (30 дней)', fontweight='bold', pad=15)
            fig.tight_layout()

            p = tempfile.mktemp(suffix='_users.png')
            fig.savefig(p, dpi=150, facecolor='white')
            plt.close(fig)
            chart_paths.append(p)

        # === 2. Анализы по дням ===
        cursor.execute("""
            SELECT DATE(last_analyzed) as day, SUM(analysis_count) as cnt
            FROM channel_stats
            WHERE last_analyzed >= datetime('now', '-30 days')
            GROUP BY day ORDER BY day
        """)
        analysis_rows = cursor.fetchall()

        if analysis_rows:
            days_a = [datetime.strptime(r[0], "%Y-%m-%d") for r in analysis_rows]
            counts_a = [r[1] for r in analysis_rows]

            fig, ax = plt.subplots(figsize=(12, 5))
            ax.bar(days_a, counts_a, color='#00b894', alpha=0.8)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
            fig.autofmt_xdate()
            ax.set_ylabel('Анализов')
            plt.title('Анализы по дням (30 дней)', fontweight='bold', pad=15)
            fig.tight_layout()

            p = tempfile.mktemp(suffix='_analyses.png')
            fig.savefig(p, dpi=150, facecolor='white')
            plt.close(fig)
            chart_paths.append(p)

        # === 3. Выручка (звёзды) по дням ===
        cursor.execute("""
            SELECT DATE(created_at) as day, SUM(stars) as total_stars, COUNT(*) as tx_count
            FROM payments
            WHERE created_at >= datetime('now', '-30 days')
            AND status = 'completed'
            GROUP BY day ORDER BY day
        """)
        revenue_rows = cursor.fetchall()

        if revenue_rows:
            days_r = [datetime.strptime(r[0], "%Y-%m-%d") for r in revenue_rows]
            stars_r = [r[1] for r in revenue_rows]
            tx_r = [r[2] for r in revenue_rows]

            # Кумулятивная выручка
            cum_stars = []
            s = 0
            for st in stars_r:
                s += st
                cum_stars.append(s)

            fig, ax1 = plt.subplots(figsize=(12, 5))
            ax1.bar(days_r, stars_r, color='#fdcb6e', alpha=0.8, label='⭐ за день')
            ax1.set_ylabel('Звёзд за день', color='#e17055')
            ax1.tick_params(axis='y', labelcolor='#e17055')

            ax2 = ax1.twinx()
            ax2.plot(days_r, cum_stars, color='#e17055', linewidth=2, marker='o', markersize=4)
            ax2.set_ylabel('Накопительно ⭐', color='#e17055')

            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax1.xaxis.set_major_locator(mdates.DayLocator(interval=3))
            fig.autofmt_xdate()

            cursor.execute("SELECT SUM(stars) FROM payments WHERE status = 'completed'")
            total_all_stars = cursor.fetchone()[0] or 0
            plt.title(f'Выручка (30 дней) — всего за всё время: {total_all_stars}⭐', fontweight='bold', pad=15)
            fig.tight_layout()

            p = tempfile.mktemp(suffix='_revenue.png')
            fig.savefig(p, dpi=150, facecolor='white')
            plt.close(fig)
            chart_paths.append(p)

        # === 4. A/B тест воронки ===
        funnel = get_buy_funnel()
        if funnel:
            groups = {'a': {}, 'b': {}}
            for action, data in funnel.items():
                if action.endswith('_a'):
                    groups['a'][action.replace('_a', '')] = data
                elif action.endswith('_b'):
                    groups['b'][action.replace('_b', '')] = data

            stages = ['open_menu', 'pack_1', 'pack_3', 'pack_10']
            labels = ['Открыли меню', '1 анализ', '3 анализа', '10 анализов']

            a_clicks = [groups['a'].get(s, {}).get('clicks', 0) for s in stages]
            b_clicks = [groups['b'].get(s, {}).get('clicks', 0) for s in stages]

            # Платежи по группам
            cursor.execute("""
                SELECT notes, COUNT(*), SUM(stars)
                FROM payments
                WHERE status = 'completed' AND notes IS NOT NULL
                GROUP BY notes
            """)
            pay_rows = cursor.fetchall()
            a_paid = sum(r[1] for r in pay_rows if r[0] and '_a' in r[0])
            b_paid = sum(r[1] for r in pay_rows if r[0] and '_b' in r[0])
            a_stars = sum(r[2] for r in pay_rows if r[0] and '_a' in r[0])
            b_stars = sum(r[2] for r in pay_rows if r[0] and '_b' in r[0])

            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

            x = range(len(labels))
            w = 0.35
            ax1.bar([i - w/2 for i in x], a_clicks, w, color='#74b9ff', label='A (дешёвые)')
            ax1.bar([i + w/2 for i in x], b_clicks, w, color='#ff7675', label='B (дорогие)')
            ax1.set_xticks(x)
            ax1.set_xticklabels(labels, rotation=15)
            ax1.set_ylabel('Клики')
            ax1.legend()
            ax1.set_title('Воронка покупок (клики)')

            # Конверсия и выручка
            bar_labels = ['Покупок', 'Звёзд ⭐']
            a_vals = [a_paid, a_stars]
            b_vals = [b_paid, b_stars]
            x2 = range(len(bar_labels))
            ax2.bar([i - w/2 for i in x2], a_vals, w, color='#74b9ff', label=f'A ({a_paid} покупок, {a_stars}⭐)')
            ax2.bar([i + w/2 for i in x2], b_vals, w, color='#ff7675', label=f'B ({b_paid} покупок, {b_stars}⭐)')
            ax2.set_xticks(x2)
            ax2.set_xticklabels(bar_labels)
            ax2.legend()
            ax2.set_title('A/B тест: результат')

            fig.suptitle('A/B тест цен', fontweight='bold', fontsize=14)
            fig.tight_layout()

            p = tempfile.mktemp(suffix='_ab_test.png')
            fig.savefig(p, dpi=150, facecolor='white')
            plt.close(fig)
            chart_paths.append(p)

        conn.close()

        if not chart_paths:
            await message.answer("📊 Недостаточно данных для построения графиков.")
            return

        # Отправляем медиагруппу
        media = []
        for i, path in enumerate(chart_paths):
            caption = "📊 Статистика бота" if i == 0 else None
            media.append(InputMediaPhoto(media=FSInputFile(path), caption=caption))

        await message.answer_media_group(media=media)

        # Удаляем временные файлы
        for path in chart_paths:
            try:
                os.remove(path)
            except OSError:
                pass

    except Exception as e:
        conn.close()
        logger.exception(f"Ошибка генерации графиков: {e}")
        await message.answer(f"❌ Ошибка: {e}")


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
    log_buy_click(user.id, f"open_menu_{get_ab_group(user.id)}")

    status = check_user_access(user.id)

    # Формируем информацию о текущем статусе
    status_text = ""
    if status.is_premium:
        if status.premium_until:
            status_text = f"👑 У вас Premium до {status.premium_until.strftime('%d.%m.%Y')}\n\n"
        else:
            status_text = "👑 У вас безлимитный доступ\n\n"
    elif status.paid_balance > 0:
        status_text = f"💎 Ваш баланс: {status.paid_balance} полных анализов\n\n"
    else:
        status_text = ""

    await message.answer(
        f"💎 *Полный анализ канала*\n\n"
        f"{status_text}"
        f"*Что входит в полный анализ:*\n"
        f"• Облако слов + топ-15\n"
        f"• Анализ тональности\n"
        f"• Мат-облако\n"
        f"• Активность по дням/часам\n"
        f"• Упоминаемые личности\n"
        f"• Популярные фразы\n"
        f"• Топ-20 эмодзи\n\n"
        f"Выберите пакет:",
        parse_mode="Markdown",
        reply_markup=_get_buy_keyboard(user.id),
    )


@router.message(F.text == "💎 Купить анализы")
async def handle_buy_button(message: types.Message) -> None:
    """Обработчик кнопки покупки в основном меню."""
    await cmd_buy(message)


@router.message(F.text == "💰 Баланс")
async def handle_balance_button(message: types.Message) -> None:
    """Обработчик кнопки баланса."""
    await cmd_balance(message)


@router.callback_query(F.data == "buy_pack_1")
async def callback_buy_pack_1(callback: types.CallbackQuery) -> None:
    """Обработчик покупки 1 полного анализа."""
    user = callback.from_user
    group = get_ab_group(user.id)
    prices = get_prices(user.id)
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 1 полный анализ [group={group}]")
    log_buy_click(user.id, f"pack_1_{group}")
    await callback.answer()

    await callback.message.answer_invoice(
        title="1 полный анализ",
        description="Попробуйте полный анализ канала: тональность, активность, личности, фразы",
        payload="pack_1",
        currency="XTR",
        prices=[LabeledPrice(label="1 полный анализ", amount=prices['pack_1'])],
    )


@router.callback_query(F.data == "buy_pack_3")
async def callback_buy_pack_3(callback: types.CallbackQuery) -> None:
    """Обработчик покупки пакета 3 полных анализов."""
    user = callback.from_user
    group = get_ab_group(user.id)
    prices = get_prices(user.id)
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 3 полных анализа [group={group}]")
    log_buy_click(user.id, f"pack_3_{group}")
    await callback.answer()

    await callback.message.answer_invoice(
        title="3 полных анализа",
        description="Полный анализ 3 каналов: тональность, активность, личности, фразы, эмодзи",
        payload="pack_3",
        currency="XTR",
        prices=[LabeledPrice(label="3 полных анализа", amount=prices['pack_3'])],
    )


@router.callback_query(F.data == "buy_pack_10")
async def callback_buy_pack_10(callback: types.CallbackQuery) -> None:
    """Обработчик покупки пакета 10 полных анализов."""
    user = callback.from_user
    group = get_ab_group(user.id)
    prices = get_prices(user.id)
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 10 полных анализов [group={group}]")
    log_buy_click(user.id, f"pack_10_{group}")
    await callback.answer()

    await callback.message.answer_invoice(
        title="10 полных анализов",
        description="Полный анализ 10 каналов",
        payload="pack_10",
        currency="XTR",
        prices=[LabeledPrice(label="10 полных анализов", amount=prices['pack_10'])],
    )


@router.callback_query(F.data == "support")
async def callback_support(callback: types.CallbackQuery) -> None:
    """Обработчик поддержки проекта."""
    user = callback.from_user
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал поддержать проект")
    await callback.answer()

    await callback.message.answer_invoice(
        title="Поддержать проект",
        description="Поддержите развитие бота и помогите сделать его еще лучше!",
        payload="support",
        currency="XTR",
        prices=[LabeledPrice(label="Поддержка проекта", amount=SUPPORT_PRICE)],
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

    group = get_ab_group(user.id)
    logger.info(f"Успешный платёж от {user.id}: {payload}, {payment.total_amount} Stars [group={group}]")

    if payload == "pack_1":
        add_paid_balance(user.id, 1)
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes=f"pack_1_{group}")
        record_payment("pack_1", payment.total_amount)
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "💎 На ваш баланс добавлен *1 полный анализ*.\n\n"
            "Отправьте юзернейм канала для полного анализа!",
            parse_mode="Markdown",
        )
    elif payload == "pack_3":
        result = add_paid_balance(user.id, 3)
        logger.info(f"💰 Платеж pack_3: user={user.id}, result={result}")
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes=f"pack_3_{group}")
        record_payment("pack_3", payment.total_amount)
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "💎 На ваш баланс добавлено *3 полных анализа*.\n\n"
            "Теперь вы получите:\n"
            "• Облако слов + топ-15\n"
            "• Анализ тональности\n"
            "• Мат-облако\n"
            "• Активность по дням/часам\n"
            "• Личности, фразы, эмодзи\n\n"
            "Отправьте юзернейм канала!",
            parse_mode="Markdown",
        )
    elif payload == "pack_10":
        add_paid_balance(user.id, 10)
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes=f"pack_10_{group}")
        record_payment("pack_10", payment.total_amount)
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "💎 На ваш баланс добавлено *10 полных анализов*.\n\n"
            "Отправьте юзернейм канала для полного анализа!",
            parse_mode="Markdown",
        )
    elif payload == "support":
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes="support")
        record_payment("support", payment.total_amount)
        await message.answer(
            "💎 *Огромное спасибо за поддержку проекта!*\n\n"
            "Ваш вклад помогает развивать бот и делать его лучше.\n"
            "Мы очень ценим вашу поддержку! 🙏",
            parse_mode="Markdown",
        )
    elif payload == "donate":
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes="donate")
        record_payment("donate", payment.total_amount)
        await message.answer(
            "❤️ *Спасибо за поддержку!*\n\n"
            "Ваш донат очень ценен для развития бота!",
            parse_mode="Markdown",
        )


@router.message(F.text == "⚡ Полный анализ")
async def handle_priority_access_button(message: types.Message) -> None:
    """Обработчик кнопки полного анализа."""
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


@router.callback_query(F.data == "admin_help")
async def callback_admin_help(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Справка по командам'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await callback.answer()
    
    help_text = (
        "🔐 *АДМИНСКИЕ КОМАНДЫ*\n\n"
        "📊 *Статистика и мониторинг:*\n"
        "`/admin` — основная статистика\n"
        "`/floodstatus` — статус пула клиентов\n"
        "`/payments` — отчёт по платежам\n"
        "`/paid_users` — детальная статистика\n\n"
        "🛠️ *Управление ботом:*\n"
        "`/clear_floodwait` — сброс cooldown\n"
        "`/clear_cache` — очистка кэша\n"
        "`/clear_floodwait_db` — очистка FloodWait БД\n\n"
        "📢 *Рассылки:*\n"
        "`/broadcast <текст>` — всем\n"
        "`/broadcast_paid <текст>` — платящим\n"
        "`/send_pending` — уведомление о незавершённых\n\n"
        "💡 Используйте кнопки ниже для быстрого доступа"
    )
    
    await callback.message.answer(help_text, parse_mode="Markdown")


@router.callback_query(F.data == "admin_payments")
async def callback_admin_payments(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Платежи'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await callback.answer()
    
    # Создаём временное сообщение для вызова cmd_payments
    temp_message = callback.message
    temp_message.from_user = callback.from_user
    await cmd_payments(temp_message)


@router.callback_query(F.data == "admin_paid_users")
async def callback_admin_paid_users(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Платящие пользователи'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await callback.answer()
    
    temp_message = callback.message
    temp_message.from_user = callback.from_user
    await cmd_paid_users(temp_message)


@router.callback_query(F.data == "admin_floodstatus")
async def callback_admin_floodstatus(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Статус пула'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await callback.answer()
    
    pool = get_client_pool()
    await callback.message.answer(pool.status_text(), parse_mode="Markdown")


@router.callback_query(F.data == "admin_clear_cache")
async def callback_admin_clear_cache(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Очистить кэш'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    pool = get_client_pool()
    cache_stats = pool.status()["cache"]
    pool.clear_cache()
    
    await callback.answer(f"✅ Кэш очищен ({cache_stats['valid']} записей)", show_alert=True)


async def show_channels_menu(message_or_query, page: int = 0):
    """Показывает меню выбора каналов с пагинацией."""
    channels = get_all_channels_for_admin()
    
    if not channels:
        if isinstance(message_or_query, types.Message):
            await message_or_query.answer("📭 Нет каналов в базе данных")
        else:
            await message_or_query.message.answer("📭 Нет каналов в базе данных")
        return
    
    # Пагинация
    items_per_page = 8
    total_pages = (len(channels) + items_per_page - 1) // items_per_page
    
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_channels = channels[start_idx:end_idx]
    
    # Создаем клавиатуру
    keyboard = []
    
    # Кнопки каналов (по 2 в ряд)
    for i in range(0, len(page_channels), 2):
        row = []
        for j in range(2):
            if i + j < len(page_channels):
                ch = page_channels[i + j]
                # Ограничиваем название до 20 символов
                title = ch['title'][:18] + '..' if len(ch['title']) > 20 else ch['title']
                row.append(InlineKeyboardButton(
                    text=f"📺 {title}",
                    callback_data=f"select_ch:{ch['channel_key']}"
                ))
        keyboard.append(row)
    
    # Навигация
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"ch_page:{page - 1}"
        ))
    
    nav_row.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{total_pages}",
        callback_data="ch_noop"
    ))
    
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"ch_page:{page + 1}"
        ))
    
    keyboard.append(nav_row)
    
    # Кнопка закрыть
    keyboard.append([
        InlineKeyboardButton(text="❌ Закрыть", callback_data="ch_close")
    ])
    
    text = (
        f"📋 *Выберите канал для анализа*\n\n"
        f"Всего каналов: {len(channels)}\n"
        f"Страница {page + 1} из {total_pages}"
    )
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # Если это первый вызов - отправляем новое сообщение
    # Если callback - редактируем существующее
    if isinstance(message_or_query, types.Message):
        await message_or_query.answer(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        # Это callback query
        try:
            await message_or_query.message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        except TelegramBadRequest:
            # Если сообщение не изменилось, игнорируем ошибку
            pass


@router.callback_query(F.data.startswith("ch_page:"))
async def callback_channels_page(query: types.CallbackQuery):
    """Пагинация списка каналов."""
    page = int(query.data.split(":")[1])
    await show_channels_menu(query, page)
    await query.answer()


@router.callback_query(F.data.startswith("select_ch:"))
async def callback_select_channel(query: types.CallbackQuery):
    """Выбор канала для анализа."""
    user = query.from_user
    
    if not is_admin(user.id):
        await query.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    channel_key = query.data.split(":", 1)[1]
    
    # Закрываем меню
    try:
        await query.message.delete()
    except:
        pass
    
    # Отправляем подтверждение
    await query.message.answer(
        f"✅ Выбран канал: `{channel_key}`\n\n"
        "🔄 Запускаю анализ...",
        parse_mode="Markdown"
    )
    
    # Создаем временное сообщение для обработки
    temp_message = types.Message(
        message_id=query.message.message_id,
        date=query.message.date,
        chat=query.message.chat,
        from_user=user,
        text=channel_key
    )
    
    # Запускаем анализ
    await handle_msg(temp_message)
    await query.answer()


@router.callback_query(F.data == "ch_noop")
async def callback_channels_noop(query: types.CallbackQuery):
    """Пустой callback для кнопки страницы."""
    await query.answer()


@router.callback_query(F.data == "ch_close")
async def callback_channels_close(query: types.CallbackQuery):
    """Закрытие меню каналов."""
    try:
        await query.message.delete()
    except:
        pass
    await query.answer("Меню закрыто")


@router.message(F.text == "📋 Мои каналы")
async def cmd_my_channels_button(message: types.Message):
    """Обработчик кнопки выбора каналов."""
    user = message.from_user
    
    if not is_admin(user.id):
        return
    
    await show_channels_menu(message, page=0)


@router.message(F.text == "📊 Админка")
async def handle_admin_button(message: types.Message) -> None:
    """Обработчик кнопки админки."""
    await cmd_admin(message)


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
        # Извлекаем hash после +
        try:
            username = message.text.split('https://t.me/+')[-1].split('?')[0].strip()
            if not username or '/' in username:
                await message.answer("❌ Неправильная ссылка на приватный канал. Используйте формат: https://t.me/+xxxxx")
                return
            username = '+' + username  # Добавляем + чтобы обозначить приватный канал
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

    Args:
        message: Сообщение пользователя.
        channel: Username канала (str) или chat_id (int).
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
        # Лимит исчерпан - предлагаем купить
        # Расчёт времени до полуночи (сброс дневного лимита)
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
            # Пытаемся получить кэшированные результаты
            cached = get_cached_analysis(channel_key)
            if cached:
                logger.info(f"Free user {user.id} получил кэшированный анализ {channel_key} (last analyzed: {last_analyzed})")
                # Используем существующий кэш ClientPool
                # Сообщение об этом уже есть в логике pool.analyze с use_cache=True

    # Проверяем rate limit (защита от спама)
    can_proceed, wait_seconds = _check_rate_limit(user.id)
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
        # Проверяем доступность Account #1 (main)
        pool_status = pool.status()
        main_account_available = False
        
        for acc_info in pool_status.get('accounts', []):
            if acc_info.get('name') == 'main':  # Account #1 для free users
                if acc_info.get('available') and not acc_info.get('busy'):
                    main_account_available = True
                break
        
        if not main_account_available:
            # Account #1 в FloodWait - показываем сообщение
            await message.answer(
                "⏳ *Бесплатная очередь перегружена*\n\n"
                "Основной аккаунт временно недоступен из-за ограничений Telegram.\n\n"
                "🔄 Попробуйте позже или воспользуйтесь платным экспресс-анализом для моментальной обработки через приоритетные аккаунты!",
                parse_mode="Markdown",
                reply_markup=_get_buy_keyboard(user.id),
            )
            log_floodwait_event(user.id, str(channel), "free_queue_overloaded")
            return

    # Обновляем время последнего запроса
    _update_rate_limit(user.id)

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
                    f"⚠️ *Пожалуйста, НЕ отправляйте повторные запросы*\n\n"
                    f"🕐 Попробуйте снова через ~{wait_minutes} мин.\n"
                    f"Ваш запрос `{channel}` сохранён.",
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
            elif "Could not find" in error or "Cannot find" in error:
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

        # Списываем анализ (только если не из кэша)
        consume_analysis(user.id, access.reason)

        # Получаем эмоциональный тон
        emotional_tone = _get_emotional_tone(result.stats.scream_index)

        # Формируем caption в зависимости от режима
        if use_lite_mode:
            # LITE MODE: облако + топ слов
            caption = (
                f"📊 *{result.title}*\n\n"
                f"📚 Уникальных слов: {result.stats.unique_count}\n"
                f"📏 Средняя длина поста: {result.stats.avg_len} слов\n"
                f"🎭 Эмоциональный тон: {emotional_tone}\n\n"
                f"_Это превью. Полный анализ доступен за ⭐_"
            )
        else:
            # FULL MODE: полная статистика
            caption = (
                f"📊 Канал: {result.title}\n\n"
                f"📚 Уникальных слов: {result.stats.unique_count}\n"
                f"📏 Средняя длина поста: {result.stats.avg_len} слов\n"
                f"🎭 Эмоциональный тон: {emotional_tone}\n"
                f"👤 Упомянуто личностей: {result.stats.unique_names_count} "
                f"({result.stats.total_names_mentions} упоминаний)"
            )

        # Собираем медиагруппу
        media = [InputMediaPhoto(media=FSInputFile(result.cloud_path), caption=caption, parse_mode="Markdown")]

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

        # Для lite mode — предложение купить полный анализ
        if use_lite_mode:
            await message.answer(
                "💎 *Хотите полный анализ?*\n\n"
                "В полной версии:\n"
                "• Анализ тональности (позитив/агрессия)\n"
                "• Мат-облако\n"
                "• Активность по дням и часам\n"
                "• Упоминаемые личности\n"
                "• Популярные фразы\n"
                "• Топ эмодзи\n\n"
                "Купите анализы за ⭐ и получите полный отчёт!",
                parse_mode="Markdown",
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
