"""
Общие утилиты, рейт-лимитинг и клавиатуры.
"""
import asyncio
import logging
import time

from cachetools import TTLCache

from aiogram import Bot, types
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import RATE_LIMIT_SECONDS, FLOODWAIT_PENALTY_SECONDS
from db import is_admin, check_user_access

logger = logging.getLogger(__name__)

# Режим приватного доступа (только для админа)
PRIVATE_MODE = False

# Белый список пользователей (username без @)
ALLOWED_USERS = {"ltdnt"}

# A/B тест цен (Telegram Stars)
PRICES_A = {'pack_1': 20, 'pack_3': 40, 'pack_10': 100}
PRICES_B = {'pack_1': 50, 'pack_3': 100, 'pack_10': 250}
SUPPORT_PRICE = 100  # Поддержка проекта


def get_ab_group(user_id: int) -> str:
    """Возвращает A/B группу пользователя."""
    return "a" if user_id % 2 == 0 else "b"


def get_prices(user_id: int) -> dict:
    """Возвращает цены для пользователя по его A/B группе."""
    return PRICES_A if user_id % 2 == 0 else PRICES_B


# Rate limiting (защита от спама и флудвейта)
# TTLCache для автоматической очистки и ограничения памяти
_rate_limit_lock = asyncio.Lock()
_user_last_request: TTLCache = TTLCache(maxsize=50000, ttl=3600)  # 1 час TTL
_user_got_floodwait: TTLCache = TTLCache(maxsize=10000, ttl=7200)  # 2 часа TTL

_bot_instance: Bot | None = None  # Для отправки уведомлений


def set_bot_instance(bot: Bot) -> None:
    """Устанавливает экземпляр бота для отправки уведомлений."""
    global _bot_instance
    _bot_instance = bot


def get_bot_instance() -> Bot | None:
    """Возвращает экземпляр бота."""
    return _bot_instance


async def notify_admin_flood(wait_seconds: int, channel: str) -> None:
    """Уведомляет админа о FloodWait."""
    from config import ADMIN_ID
    from client_pool import get_client_pool
    if _bot_instance:
        try:
            pool = get_client_pool()
            status = pool.status()
            accounts_info = ""
            for acc in status.get('accounts', []):
                state = "+" if acc.get('available') else f"... {acc.get('cooldown_remaining', 0)//60}мин"
                accounts_info += f"  {acc['name']}: {state}\n"

            await _bot_instance.send_message(
                ADMIN_ID,
                f"*Все аккаунты в FloodWait!*\n\n"
                f"Канал: `{channel}`\n"
                f"Ожидание: ~{wait_seconds // 60} мин\n\n"
                f"Аккаунты:\n{accounts_info}",
                parse_mode="Markdown"
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось уведомить админа о FloodWait: {e}")


async def notify_admin_paid_user_error(user_id: int, username: str, channel: str, error: str) -> None:
    """Уведомляет админа об ошибке анализа платного пользователя."""
    from config import ADMIN_ID
    if _bot_instance:
        try:
            await _bot_instance.send_message(
                ADMIN_ID,
                f"*Ошибка анализа платного пользователя*\n\n"
                f"Пользователь: {user_id} (@{username})\n"
                f"Канал: `{channel}`\n"
                f"Ошибка: {error[:100]}...",
                parse_mode="Markdown"
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось уведомить админа об ошибке платного пользователя: {e}")


async def notify_admin_error(error_type: str, details: str) -> None:
    """Уведомляет админа о любой ошибке/поломке."""
    from config import ADMIN_ID
    if _bot_instance:
        try:
            await _bot_instance.send_message(
                ADMIN_ID,
                f"*{error_type}*\n\n{details[:500]}",
                parse_mode="Markdown"
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось уведомить админа: {e}")


async def notify_admin_payment(pack: str, stars: int, group: str = "") -> None:
    """Уведомляет админа о новой оплате."""
    from config import ADMIN_ID
    if _bot_instance:
        try:
            group_suffix = f" ({group})" if group else ""
            await _bot_instance.send_message(ADMIN_ID, f"💰 {pack}: {stars}⭐{group_suffix}")
        except TelegramAPIError as e:
            logger.error(f"Не удалось уведомить админа о платеже: {e}")


def _check_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    Проверяет rate limit для пользователя.

    Returns:
        (можно_продолжить, секунд_до_разблокировки)
    """
    if is_admin(user_id):
        return True, 0

    now = time.time()

    # Если пользователь недавно получил FloodWait -- увеличенный лимит
    floodwait_time = _user_got_floodwait.get(user_id)
    if floodwait_time is not None:
        elapsed_since_fw = now - floodwait_time
        if elapsed_since_fw < FLOODWAIT_PENALTY_SECONDS:
            remaining = int(FLOODWAIT_PENALTY_SECONDS - elapsed_since_fw)
            return False, remaining
        # TTLCache автоматически очистит запись по TTL

    last_request = _user_last_request.get(user_id, 0.0)
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


async def check_and_update_rate_limit(user_id: int) -> tuple[bool, int]:
    """Атомарно проверяет и обновляет рейт-лимит.

    Returns:
        (можно_продолжить, секунд_до_разблокировки)
    """
    async with _rate_limit_lock:
        can_proceed, wait = _check_rate_limit(user_id)
        if can_proceed:
            _update_rate_limit(user_id)
        return can_proceed, wait


def cleanup_rate_limits() -> int:
    """Удаляет устаревшие записи из словарей рейт-лимитов.

    TTLCache автоматически удаляет истёкшие записи, но вызов expire()
    принудительно очищает их для освобождения памяти.

    Returns:
        Количество удалённых записей (приблизительно).
    """
    # TTLCache.expire() удаляет все истёкшие записи
    before_request = len(_user_last_request)
    before_floodwait = len(_user_got_floodwait)

    _user_last_request.expire()
    _user_got_floodwait.expire()

    after_request = len(_user_last_request)
    after_floodwait = len(_user_got_floodwait)

    return (before_request - after_request) + (before_floodwait - after_floodwait)


async def _check_access(message: types.Message) -> bool:
    """Проверяет доступ пользователя. Возвращает True если доступ разрешён."""
    if not PRIVATE_MODE:
        return True
    if is_admin(message.from_user.id):
        return True
    # Проверяем username в белом списке
    if message.from_user.username and message.from_user.username.lower() in ALLOWED_USERS:
        return True
    await message.answer("Бот находится в режиме тестирования. Доступ ограничен.")
    return False


def _get_emotional_tone(scream_index: float) -> str:
    """Преобразует числовой индекс крика в описательный эмоциональный тон."""
    if scream_index <= 1.5:
        return "Спокойный"
    elif scream_index <= 4.0:
        return "Умеренный"
    elif scream_index <= 7.0:
        return "Экспрессивный"
    else:
        return "Взрывной"


def _get_main_keyboard(user_id: int = 0) -> ReplyKeyboardMarkup:
    """Создаёт основную клавиатуру."""
    # Проверяем статус пользователя
    access = check_user_access(user_id)
    is_paid = access.paid_balance > 0 or access.is_premium

    keyboard = [
        [
            KeyboardButton(text="💎 Купить анализы"),
            KeyboardButton(text="💰 Баланс")
        ],
        [
            KeyboardButton(text="❓ Помощь"),
            KeyboardButton(text="✍️ Написать отзыв"),
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


# Review state — отслеживание пользователей, пишущих отзыв
_users_writing_review: set[int] = set()


def is_writing_review(user_id: int) -> bool:
    return user_id in _users_writing_review


def set_writing_review(user_id: int) -> None:
    _users_writing_review.add(user_id)


def clear_writing_review(user_id: int) -> None:
    _users_writing_review.discard(user_id)


def _get_buy_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    """Создаёт inline-клавиатуру с вариантами покупки."""
    prices = get_prices(user_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✨ 1 полный анализ — {prices['pack_1']} ⭐", callback_data="buy_pack_1")],
            [InlineKeyboardButton(text=f"🎯 3 полных анализа — {prices['pack_3']} ⭐", callback_data="buy_pack_3")],
            [InlineKeyboardButton(text=f"💎 10 полных анализов — {prices['pack_10']} ⭐", callback_data="buy_pack_10")],
            [InlineKeyboardButton(text="😍 Мне нравится бот — 1 ⭐", callback_data="donate")],
            [InlineKeyboardButton(text=f"❤️ Поддержать проект — {SUPPORT_PRICE} ⭐", callback_data="support")],
        ]
    )
