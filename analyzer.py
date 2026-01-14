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
from nltk.util import ngrams

from config import MOSCOW_TZ, DEFAULT_MESSAGE_LIMIT
from nlp.processor import get_clean_words, extract_emojis
from nlp.constants import positive_words, aggressive_words
from visualization.wordclouds import (
    generate_main_cloud,
    generate_sentiment_cloud,
    generate_mats_cloud,
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

    # Данные
    top_emojis: list[tuple[str, int]] = field(default_factory=list)

    def get_all_paths(self) -> list[str]:
        """Возвращает список всех путей к файлам."""
        paths = [
            self.cloud_path, self.graph_path, self.mats_path,
            self.positive_path, self.aggressive_path, self.weekday_path,
            self.hour_path, self.names_path, self.phrases_path
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

        # Получение данных канала (Telethon поддерживает и username, и chat_id)
        entity = await client.get_entity(channel)
        title = entity.title

        # Используем username или id для имён файлов
        channel_id = getattr(entity, 'username', None) or str(entity.id)

        messages = [m async for m in client.iter_messages(entity, limit=limit) if m.text]
        posts: list[tuple[datetime, str]] = [(m.date, m.text) for m in messages]

        if not posts:
            logger.warning(f"Канал {channel} пуст или нет текстовых сообщений")
            return AnalysisResult(title=title)

        logger.info(f"Получено {len(posts)} сообщений из канала {channel}")

        # Извлечение слов
        all_words: list[str] = []
        mat_words: list[str] = []
        pos_words: list[str] = []
        agg_words: list[str] = []
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

        # Статистика по дням недели
        weekday_lens: dict[int, list[int]] = {i: [] for i in range(7)}
        for date, text in posts:
            weekday_lens[date.astimezone(MOSCOW_TZ).weekday()].append(len(text.split()))
        avg_lens = {wd: np.mean(lens) if lens else 0 for wd, lens in weekday_lens.items()}
        weekday_path = generate_weekday_chart(channel_id, avg_lens, title)

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

        # Фразы (триграммы)
        all_tokens: list[str] = []
        for _, text in posts:
            all_tokens.extend(re.findall(r'\b\w+\b', text.lower()))
        trigrams_list = list(ngrams(all_tokens, 3))
        top_trigrams = Counter(trigrams_list).most_common(10)
        phrases_path = generate_phrases_chart(channel_id, top_trigrams, title)

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
            top_emojis=top_emojis,
        )

    except Exception as e:
        logger.error(f"Ошибка анализа канала {channel}: {e}")
        raise AnalysisError(f"Не удалось проанализировать канал: {e}") from e
