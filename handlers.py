"""
Обработчики команд и сообщений Telegram-бота.
"""
import os
import logging

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InputMediaPhoto
from telethon import TelegramClient

from analyzer import analyze_channel, AnalysisError

logger = logging.getLogger(__name__)

router = Router()

# Ссылка на Telegram-клиент (устанавливается при запуске)
_user_client: TelegramClient | None = None


def set_user_client(client: TelegramClient) -> None:
    """Устанавливает клиент Telegram для анализа."""
    global _user_client
    _user_client = client


@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    """Обработчик команды /start."""
    logger.info(f"Пользователь {message.from_user.id} запустил бота")
    await message.answer(
        "Пришли мне юзернейм канала (например: `polozhnyak`), "
        "и я выверну его смыслы наизнанку!"
    )


@router.message(F.text)
async def handle_msg(message: types.Message) -> None:
    """Обработчик текстовых сообщений с юзернеймом канала."""
    if message.text.startswith('/'):
        return

    if _user_client is None:
        await message.answer("Бот не готов к работе. Попробуйте позже.")
        logger.error("Telegram-клиент не инициализирован")
        return

    username = message.text.replace('@', '').split('/')[-1].strip()
    logger.info(f"Запрос анализа канала: {username} от пользователя {message.from_user.id}")

    status = await message.answer("Извлекаю смыслы... Подождите минутку")

    try:
        result = await analyze_channel(_user_client, username)

        if result is None or result.cloud_path is None:
            await message.answer("Ошибка или канал пуст.")
            await status.delete()
            return

        # Формируем caption со статистикой
        caption = (
            f"Канал: {result.title}\n\n"
            f"Количество уникальных слов: {result.stats.unique_count}\n"
            f"Средняя длина поста: {result.stats.avg_len} слов\n"
            f"Индекс крика: {result.stats.scream_index}"
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
            emoji_text = f"Топ-20 эмодзи канала {result.title}\n\n"
            for emo, count in result.top_emojis:
                emoji_text += f"{emo} x {count}\n"
            await message.answer(emoji_text)

        logger.info(f"Анализ канала {username} успешно отправлен пользователю {message.from_user.id}")

        # Удаление временных файлов
        for path in result.get_all_paths():
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                logger.warning(f"Не удалось удалить файл {path}: {e}")

    except AnalysisError as e:
        logger.error(f"Ошибка анализа: {e}")
        await message.answer(f"Ошибка анализа канала: {e}")

    except Exception as e:
        logger.exception(f"Неожиданная ошибка при анализе канала {username}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

    finally:
        try:
            await status.delete()
        except Exception:
            pass
