"""
Модуль анализа Telegram-каналов.
"""
import re
import logging
from dataclasses import dataclass, field
from collections import Counter
from datetime import datetime

import numpy as np
from telethon import TelegramClient
from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError, FloodWaitError

from config import MOSCOW_TZ, DEFAULT_MESSAGE_LIMIT
from nlp.processor import get_clean_words, extract_emojis, extract_phrases
from nlp.constants import positive_words, aggressive_words, METAPHYSICS_WORDS, EVERYDAY_WORDS
from visualization.wordclouds import (
    generate_main_cloud,
    generate_sentiment_cloud,
    generate_mats_cloud,
    generate_register_cloud,
    generate_dichotomy_cloud,
)
from visualization.charts import (
    generate_top_words_chart,
    generate_weekday_chart,
    generate_hour_chart,
    generate_names_chart,
    generate_phrases_chart,
)

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Ошибка анализа канала."""
    pass


@dataclass
class ChannelStats:
    """Статистика канала."""
    unique_count: int = 0
    avg_len: float = 0.0
    scream_index: float = 0.0
    unique_names_count: int = 0
    total_names_mentions: int = 0
    repost_count: int = 0
    repost_percent: float = 0.0


@dataclass
class AnalysisResult:
    """Результат анализа канала."""
    title: str = ""
    stats: ChannelStats = field(default_factory=ChannelStats)

    # Пути к файлам визуализации
    cloud_path: str | None = None
    graph_path: str | None = None
    mats_path: str | None = None
    positive_path: str | None = None
    aggressive_path: str | None = None
    weekday_path: str | None = None
    hour_path: str | None = None
    names_path: str | None = None
    phrases_path: str | None = None
    register_path: str | None = None
    dichotomy_path: str | None = None

    # Данные
    top_emojis: list[tuple[str, int]] = field(default_factory=list)

    def get_all_paths(self) -> list[str]:
        """Возвращает список всех путей к файлам."""
        paths = [
            self.cloud_path, self.graph_path, self.mats_path,
            self.positive_path, self.aggressive_path, self.weekday_path,
            self.hour_path, self.names_path, self.phrases_path,
            self.register_path, self.dichotomy_path
        ]
        return [p for p in paths if p]


async def analyze_channel(
    client: TelegramClient,
    channel: str | int,
    limit: int = DEFAULT_MESSAGE_LIMIT
) -> AnalysisResult | None:
    """
    Анализирует Telegram-канал.

    Args:
        client: Подключённый TelegramClient.
        channel: Username канала (str) или chat_id (int).
        limit: Максимальное количество сообщений для анализа.

    Returns:
        AnalysisResult с результатами или None при ошибке.

    Raises:
        AnalysisError: При критических ошибках анализа.
    """
    try:
        if not client.is_connected():
            await client.connect()

        logger.info(f"Начат анализ канала: {channel}")

        # Получение данных канала с fallback
        entity = None
        try:
            entity = await client.get_entity(channel)
        except ValueError as e:
            # Если не удалось найти по ID, пробуем как username
            if "Could not find the input entity" in str(e):
                logger.warning(f"Канал {channel} не найден по ID, пробую как username")
                # Очищаем от возможных префиксов
                clean_channel = str(channel).lstrip('@').split('/')[-1].strip()
                if clean_channel:
                    try:
                        entity = await client.get_entity(clean_channel)
                    except (ValueError, UsernameNotOccupiedError, UsernameInvalidError):
                        pass
            if entity is None:
                raise

        title = entity.title

        # Используем username или id для имён файлов
        channel_id = getattr(entity, 'username', None) or str(entity.id)

        messages = [m async for m in client.iter_messages(entity, limit=limit) if m.text]
        posts: list[tuple[datetime, str]] = [(m.date, m.text) for m in messages]

        # Подсчёт репостов (сообщения с forward)
        repost_count = sum(1 for m in messages if m.forward is not None)
        total_messages = len(messages)
        repost_percent = round(repost_count / total_messages * 100, 1) if total_messages > 0 else 0.0

        if not posts:
            logger.warning(f"Канал {channel} пуст или нет текстовых сообщений")
            return AnalysisResult(title=title)

        logger.info(f"Получено {len(posts)} сообщений из канала {channel}")

        # Извлечение слов
        all_words: list[str] = []
        mat_words: list[str] = []
        pos_words: list[str] = []
        agg_words: list[str] = []
        metaphysics_words: list[str] = []
        everyday_words: list[str] = []
        names: list[str] = []
        all_emojis: list[str] = []

        upper_ratios: list[float] = []
        excl_counts: list[float] = []

        for date, text in posts:
            all_words.extend(get_clean_words(text, 'normal'))
            mat_words.extend(get_clean_words(text, 'mats'))
            names.extend(get_clean_words(text, 'person'))
            all_emojis.extend(extract_emojis(text))

            clean = get_clean_words(text, 'normal')
            pos_words.extend(w for w in clean if w in positive_words)
            agg_words.extend(w for w in clean if w in aggressive_words)
            metaphysics_words.extend(w for w in clean if w in METAPHYSICS_WORDS)
            everyday_words.extend(w for w in clean if w in EVERYDAY_WORDS)

            if text:
                alpha_count = sum(1 for c in text if c.isalpha())
                if alpha_count > 0:
                    upper_ratios.append(sum(c.isupper() for c in text) / alpha_count)
                word_count = len(text.split())
                if word_count > 0:
                    excl_counts.append(text.count('!') / word_count)

        if not all_words:
            logger.warning(f"Не удалось извлечь слова из канала {channel}")
            return AnalysisResult(title=title)

        # Диагностика периода
        oldest = min(d for d, _ in posts)
        newest = max(d for d, _ in posts)
        logger.info(
            f"Канал: {channel_id} | Постов: {len(posts)} | "
            f"Период: {oldest.astimezone(MOSCOW_TZ).strftime('%Y-%m-%d')} – "
            f"{newest.astimezone(MOSCOW_TZ).strftime('%Y-%m-%d')}"
        )

        # Создание визуализаций
        word_counter = Counter(all_words)

        cloud_path = generate_main_cloud(channel_id, all_words, title)
        graph_path = generate_top_words_chart(channel_id, word_counter, title)
        mats_path = generate_mats_cloud(channel_id, mat_words, title)
        pos_path = generate_sentiment_cloud(channel_id, pos_words, title, 'positive')
        agg_path = generate_sentiment_cloud(channel_id, agg_words, title, 'aggressive')

        # Статистика по дням недели (количество постов)
        weekday_counts = Counter(date.astimezone(MOSCOW_TZ).weekday() for date, _ in posts)
        weekday_path = generate_weekday_chart(channel_id, dict(weekday_counts), title)

        # Статистика по часам
        hour_counts = Counter((date.astimezone(MOSCOW_TZ)).hour for date, _ in posts)
        hour_path = generate_hour_chart(channel_id, dict(hour_counts), title)

        # Имена и личности
        names_counter = Counter(names)
        unique_names_count = len(names_counter)
        total_names_mentions = len(names)
        top_names = names_counter.most_common(100)
        names_path = generate_names_chart(
            channel_id, top_names, title,
            total_unique_names=unique_names_count,
            total_mentions=total_names_mentions
        )

        # Фразы (триграммы) с фильтрацией
        all_texts = [text for _, text in posts]
        top_phrases = extract_phrases(all_texts, n=3)[:10]
        phrases_path = generate_phrases_chart(channel_id, top_phrases, title)

        # Облако регистра (CAPS vs lowercase)
        caps_words: list[str] = []
        lower_words: list[str] = []
        total_register_words = 0

        for _, text in posts:
            # Извлекаем только кириллические слова 3+ букв
            words = re.findall(r'[а-яА-ЯёЁ]{3,}', text)
            for word in words:
                total_register_words += 1
                if word.isupper():
                    caps_words.append(word)
                elif word.islower():
                    lower_words.append(word)

        # Считаем проценты
        caps_percent = (len(caps_words) / total_register_words * 100) if total_register_words > 0 else 0
        lower_percent = (len(lower_words) / total_register_words * 100) if total_register_words > 0 else 0

        # Генерируем облако регистра
        register_path = generate_register_cloud(
            channel_id, caps_words, lower_words, title,
            caps_percent, lower_percent
        )

        # Дихотомия языка (метафизика vs быт)
        dichotomy_total = len(metaphysics_words) + len(everyday_words)
        meta_percent = (len(metaphysics_words) / dichotomy_total * 100) if dichotomy_total > 0 else 0
        everyday_percent = (len(everyday_words) / dichotomy_total * 100) if dichotomy_total > 0 else 0
        dichotomy_path = generate_dichotomy_cloud(
            channel_id, metaphysics_words, everyday_words, title,
            meta_percent, everyday_percent
        )

        # Эмодзи
        emoji_freq = Counter(all_emojis)
        top_emojis = emoji_freq.most_common(20)

        # Расчёт статистики
        avg_upper = np.mean(upper_ratios) if upper_ratios else 0
        avg_excl = np.mean(excl_counts) if excl_counts else 0
        scream_index = round(avg_upper * 100 + avg_excl * 10, 1)

        stats = ChannelStats(
            unique_count=len(set(all_words)),
            avg_len=round(np.mean([len(p[1].split()) for p in posts]), 1),
            scream_index=scream_index,
            unique_names_count=unique_names_count,
            total_names_mentions=total_names_mentions,
            repost_count=repost_count,
            repost_percent=repost_percent,
        )

        logger.info(f"Анализ канала {channel_id} завершён успешно")

        return AnalysisResult(
            title=title,
            stats=stats,
            cloud_path=cloud_path,
            graph_path=graph_path,
            mats_path=mats_path,
            positive_path=pos_path,
            aggressive_path=agg_path,
            weekday_path=weekday_path,
            hour_path=hour_path,
            names_path=names_path,
            phrases_path=phrases_path,
            register_path=register_path,
            dichotomy_path=dichotomy_path,
            top_emojis=top_emojis,
        )

    except FloodWaitError:
        raise  # Пробрасываем для обработки в handlers.py

    except Exception as e:
        logger.error(f"Ошибка анализа канала {channel}: {e}")
        raise AnalysisError(f"Не удалось проанализировать канал: {e}") from e
