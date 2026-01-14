"""
Обработчики команд и сообщений Telegram-бота.
"""
import os
import logging

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ChatShared,
)
from telethon import TelegramClient

from analyzer import analyze_channel, AnalysisError
from db import register_user, log_request, get_stats, is_admin

logger = logging.getLogger(__name__)

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
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    """Обработчик команды /start."""
    user = message.from_user
    logger.info(f"Пользователь {user.id} запустил бота")

    # Регистрируем пользователя в БД
    register_user(user.id, user.username)

    await message.answer(
        "📊 *Добро пожаловать в Insight Bot!*\n\n"
        "Я анализирую публичные Telegram-каналы и выворачиваю их смыслы наизнанку.\n\n"
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


@router.message(F.chat_shared)
async def handle_chat_shared(message: types.Message) -> None:
    """Обработчик выбора канала через кнопку."""
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
    status = await message.answer("🛸 Извлекаю смыслы... Подождите минутку")

    try:
        # Telethon поддерживает как username (str), так и chat_id (int)
        result = await analyze_channel(_user_client, channel)

        if result is None or result.cloud_path is None:
            await message.answer("❌ Ошибка или канал пуст.")
            await status.delete()
            return

        # Логируем успешный запрос
        log_request(user.id)

        # Формируем caption со статистикой
        caption = (
            f"📊 Канал: {result.title}\n\n"
            f"📚 Уникальных слов: {result.stats.unique_count}\n"
            f"📏 Средняя длина поста: {result.stats.avg_len} слов\n"
            f"🗣️ Индекс крика: {result.stats.scream_index}\n"
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
            await status.delete()
        except Exception:
            pass
