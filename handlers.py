"""
Обработчики команд и сообщений Telegram-бота.
"""
import os
import logging

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ChatShared,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    Message,
)
from telethon import TelegramClient

from analyzer import analyze_channel, AnalysisError
from db import (
    register_user, log_request, get_stats, is_admin,
    check_user_access, consume_analysis, add_paid_balance, set_premium,
    FREE_DAILY_LIMIT,
)

logger = logging.getLogger(__name__)

# Режим приватного доступа (только для админа)
PRIVATE_MODE = True

# Белый список пользователей (username без @)
ALLOWED_USERS = {"ltdnt"}

# Настройки платежей (Telegram Stars)
PACK_10_PRICE = 75  # Stars за 10 анализов
PACK_WEEKLY_PRICE = 250  # Stars за неделю безлимита


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

# Ссылка на Telegram-клиент (устанавливается при запуске)
_user_client: TelegramClient | None = None


def set_user_client(client: TelegramClient) -> None:
    """Устанавливает клиент Telegram для анализа."""
    global _user_client
    _user_client = client


def _get_channel_keyboard() -> ReplyKeyboardMarkup:
    """Создаёт клавиатуру с кнопкой выбора канала."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📊 Выбрать канал для анализа",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=1,
                        chat_is_channel=True,
                        user_administrator_rights=None,
                        bot_administrator_rights=None,
                    ),
                )
            ],
            [
                KeyboardButton(text="💎 Купить анализы")
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
        "Я анализирую публичные Telegram-каналы и выворачиваю их смыслы наизнанку. Вы можете бесплатно проанализировать два канала.\n\n"
        "🔹 Нажми кнопку ниже, чтобы выбрать канал\n"
        "🔹 Или просто отправь юзернейм (например: `polozhnyak`)",
        parse_mode="Markdown",
        reply_markup=_get_channel_keyboard(),
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

    # Формируем топ пользователей
    top_text = ""
    if stats["top_users"]:
        top_text = "\n\n👑 *Топ-5 пользователей:*\n"
        for i, (uid, uname, count) in enumerate(stats["top_users"], 1):
            name = f"@{uname}" if uname else f"ID:{uid}"
            top_text += f"{i}. {name} — {count} запросов\n"

    await message.answer(
        f"📈 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"✅ Активных пользователей: {stats['active_users']}\n"
        f"📊 Всего анализов: {stats['total_requests']}"
        f"{top_text}",
        parse_mode="Markdown",
    )


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
        status_text = f"⭐ У вас Premium до {status.premium_until.strftime('%d.%m.%Y')}\n\n"
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

    if payload == "pack_10":
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


@router.message(F.chat_shared)
async def handle_chat_shared(message: types.Message) -> None:
    """Обработчик выбора канала через кнопку."""
    if not await _check_access(message):
        return

    chat_shared: ChatShared = message.chat_shared

    if chat_shared.request_id != 1:
        return

    chat_id = chat_shared.chat_id
    user = message.from_user

    logger.info(f"Пользователь {user.id} выбрал канал через кнопку: {chat_id}")

    # Регистрируем пользователя
    register_user(user.id, user.username)

    # Выполняем анализ
    await _perform_analysis(message, chat_id)


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
        remaining_text = ""
        if access.daily_limit > 0:
            remaining_text = f"Бесплатный лимит: {access.daily_used}/{access.daily_limit}\n"
        if access.paid_balance > 0:
            remaining_text += f"Платный баланс: {access.paid_balance}\n"

        await message.answer(
            f"⏳ *Лимит исчерпан*\n\n"
            f"{remaining_text}\n"
            f"Купите дополнительные анализы или подождите до завтра.",
            parse_mode="Markdown",
            reply_markup=_get_buy_keyboard(),
        )
        return

    status_msg = await message.answer("🛸 Извлекаю смыслы... Подождите минутку")

    try:
        # Telethon поддерживает как username (str), так и chat_id (int)
        result = await analyze_channel(_user_client, channel)

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

        await message.answer_media_group(media=media)

        # Отдельное сообщение с эмодзи
        if result.top_emojis:
            emoji_text = f"🔥 Топ-20 эмодзи канала {result.title}\n\n"
            for emo, count in result.top_emojis:
                emoji_text += f"{emo} x {count}\n"
            await message.answer(emoji_text)

        logger.info(f"Анализ канала {channel} успешно отправлен пользователю {user.id}")

        # Удаление временных файлов
        for path in result.get_all_paths():
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                logger.warning(f"Не удалось удалить файл {path}: {e}")

    except AnalysisError as e:
        logger.error(f"Ошибка анализа: {e}")
        await message.answer(f"❌ Ошибка анализа канала: {e}")

    except Exception as e:
        logger.exception(f"Неожиданная ошибка при анализе канала {channel}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")

    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass
