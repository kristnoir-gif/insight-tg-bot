"""
Модуль анализа Telegram-каналов.
"""
import re
import os
import json
import shutil
import asyncio
import logging
from dataclasses import dataclass, field
from collections import Counter
from datetime import datetime
from time import time as time_now

import numpy as np
from telethon import TelegramClient
from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError, FloodWaitError
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import LeaveChannelRequest

from config import MOSCOW_TZ, DEFAULT_MESSAGE_LIMIT

# Кэширование результатов анализа
CACHE_DIR = "cache"
CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 часов (агрессивное кэширование)
CACHE_TTL_LITE_SECONDS = 24 * 60 * 60  # 24 часа для lite-анализов
MESSAGES_DELAY_INTERVAL = 30   # Пауза каждые N сообщений (снижение нагрузки)
MESSAGES_DELAY_SECONDS = 2.0   # Длительность паузы
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
    subscribers: int = 0
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
    from_cache: bool = False  # Флаг: результат из кэша

    def get_all_paths(self) -> list[str]:
        """Возвращает список всех путей к файлам."""
        paths = [
            self.cloud_path, self.graph_path, self.mats_path,
            self.positive_path, self.aggressive_path, self.weekday_path,
            self.hour_path, self.names_path, self.phrases_path,
            self.register_path, self.dichotomy_path
        ]
        return [p for p in paths if p]


def _get_cache_path(channel_id: str) -> str:
    """Возвращает путь к папке кэша для канала."""
    return os.path.join(CACHE_DIR, channel_id.lower())


def _is_cache_valid(channel_id: str) -> bool:
    """Проверяет, есть ли валидный кэш для канала."""
    cache_path = _get_cache_path(channel_id)
    meta_path = os.path.join(cache_path, "meta.json")

    if not os.path.exists(meta_path):
        return False

    try:
        with open(meta_path, "r") as f:
            meta = json.load(f)
        cached_at = meta.get("cached_at", 0)
        if time_now() - cached_at < CACHE_TTL_SECONDS:
            return True
    except (json.JSONDecodeError, OSError):
        pass

    return False


def _load_from_cache(channel_id: str) -> AnalysisResult | None:
    """Загружает результат из кэша."""
    cache_path = _get_cache_path(channel_id)
    meta_path = os.path.join(cache_path, "meta.json")

    try:
        with open(meta_path, "r") as f:
            meta = json.load(f)

        result = AnalysisResult(
            title=meta.get("title", ""),
            subscribers=meta.get("subscribers", 0),
            stats=ChannelStats(
                unique_count=meta.get("unique_count", 0),
                avg_len=meta.get("avg_len", 0.0),
                scream_index=meta.get("scream_index", 0.0),
                unique_names_count=meta.get("unique_names_count", 0),
                total_names_mentions=meta.get("total_names_mentions", 0),
            ),
            top_emojis=[(e[0], e[1]) for e in meta.get("top_emojis", [])],
        )

        # Копируем изображения из кэша во временные файлы
        for img_name in ["cloud.png", "graph.png", "mats.png", "positive.png",
                         "aggressive.png", "weekday.png", "hour.png",
                         "names.png", "phrases.png"]:
            src = os.path.join(cache_path, img_name)
            if os.path.exists(src):
                dst = f"{channel_id}_{img_name}"
                shutil.copy(src, dst)
                attr_name = img_name.replace(".png", "_path")
                if attr_name == "cloud_path":
                    result.cloud_path = dst
                elif attr_name == "graph_path":
                    result.graph_path = dst
                elif attr_name == "mats_path":
                    result.mats_path = dst
                elif attr_name == "positive_path":
                    result.positive_path = dst
                elif attr_name == "aggressive_path":
                    result.aggressive_path = dst
                elif attr_name == "weekday_path":
                    result.weekday_path = dst
                elif attr_name == "hour_path":
                    result.hour_path = dst
                elif attr_name == "names_path":
                    result.names_path = dst
                elif attr_name == "phrases_path":
                    result.phrases_path = dst

        logger.info(f"Загружен кэш для канала {channel_id}")
        return result

    except (json.JSONDecodeError, OSError, KeyError) as e:
        logger.warning(f"Ошибка загрузки кэша: {e}")
        return None


def _save_to_cache(channel_id: str, result: AnalysisResult) -> None:
    """Сохраняет результат в кэш."""
    cache_path = _get_cache_path(channel_id)

    try:
        os.makedirs(cache_path, exist_ok=True)

        # Сохраняем метаданные
        meta = {
            "cached_at": time_now(),
            "title": result.title,
            "subscribers": result.subscribers,
            "unique_count": result.stats.unique_count,
            "avg_len": result.stats.avg_len,
            "scream_index": result.stats.scream_index,
            "unique_names_count": result.stats.unique_names_count,
            "total_names_mentions": result.stats.total_names_mentions,
            "top_emojis": result.top_emojis,
        }
        with open(os.path.join(cache_path, "meta.json"), "w") as f:
            json.dump(meta, f)

        # Копируем изображения в кэш
        path_mapping = {
            "cloud.png": result.cloud_path,
            "graph.png": result.graph_path,
            "mats.png": result.mats_path,
            "positive.png": result.positive_path,
            "aggressive.png": result.aggressive_path,
            "weekday.png": result.weekday_path,
            "hour.png": result.hour_path,
            "names.png": result.names_path,
            "phrases.png": result.phrases_path,
        }
        for cache_name, src_path in path_mapping.items():
            if src_path and os.path.exists(src_path):
                shutil.copy(src_path, os.path.join(cache_path, cache_name))

        logger.info(f"Сохранён кэш для канала {channel_id}")

    except OSError as e:
        logger.warning(f"Ошибка сохранения кэша: {e}")


async def analyze_channel(
    client: TelegramClient,
    channel: str | int,
    limit: int = DEFAULT_MESSAGE_LIMIT,
    is_private: bool = False,
    lite_mode: bool = False
) -> AnalysisResult | None:
    """
    Анализирует Telegram-канал.

    Args:
        client: Подключённый TelegramClient.
        channel: Username канала (str) или chat_id (int).
        limit: Максимальное количество сообщений для анализа.
        is_private: Является ли канал приватным (требует присоединения).
        lite_mode: Облегчённый режим — только облако слов и топ-15 (для бесплатных).

    Returns:
        AnalysisResult с результатами или None при ошибке.

    Raises:
        AnalysisError: При критических ошибках анализа.
    """
    # Определяем channel_id для кэша
    channel_key = str(channel).lstrip('@').split('/')[-1].strip().lower()
    
    # Для приватных каналов - пытаемся присоединиться
    joined_chat = None
    if is_private:
        try:
            logger.info(f"Присоединение к приватному каналу: {channel}")
            # channel содержит hash (например: +glL4HD1_l584ODAy)
            # Используем ImportChatInviteRequest для присоединения
            chat_hash = str(channel).lstrip('+').strip()
            if chat_hash:
                result = await client(ImportChatInviteRequest(hash=chat_hash))
                if result.chats:
                    joined_chat = result.chats[0]
                    logger.info(f"Успешно присоединены к: {joined_chat.title}")
            else:
                logger.warning(f"Неправильный формат приватного канала: {channel}")
        except Exception as e:
            logger.error(f"Ошибка присоединения к приватному каналу {channel}: {type(e).__name__}: {e}")
            # Продолжаем - возможно уже присоединены или будет ошибка при получении entity

    # Проверяем кэш
    if _is_cache_valid(channel_key):
        cached_result = _load_from_cache(channel_key)
        if cached_result and cached_result.cloud_path:
            logger.info(f"Используем кэш для канала {channel}")
            return cached_result

    try:
        if not client.is_connected():
            await client.connect()

        logger.info(f"Начат анализ канала: {channel}")

        # Получение данных канала с fallback
        entity = None
        try:
            if joined_chat:
                # Используем результат присоединения напрямую
                entity = joined_chat
            else:
                entity = await client.get_entity(channel)
        except ValueError as e:
            # Если не удалось найти по ID, пробуем как username
            if "Could not find the input entity" in str(e):
                if is_private:
                    logger.warning(f"Приватный канал {channel} не найден после присоединения")
                    raise AnalysisError(f"Нет доступа к приватному каналу или ссылка истекла")
                else:
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
        # Не сохраняем количество подписчиков для приватных/закрытых каналов
        # это требует дополнительного входа в канал и создает нагрузку на API
        subscribers = 0 if is_private else (getattr(entity, 'participants_count', 0) or 0)

        # Используем username или id для имён файлов
        channel_id = getattr(entity, 'username', None) or str(entity.id)

        # Получаем сообщения с задержками для предотвращения FloodWait
        messages = []
        msg_count = 0
        try:
            async for m in client.iter_messages(entity, limit=limit):
                if m.text:
                    messages.append(m)
                msg_count += 1
                # Пауза каждые N сообщений для снижения нагрузки на API
                if msg_count % MESSAGES_DELAY_INTERVAL == 0:
                    await asyncio.sleep(MESSAGES_DELAY_SECONDS)
        except Exception as e:
            error_str = str(e).lower()
            if "restricted" in error_str or "api access" in error_str or "bot users" in error_str:
                logger.error(f"Канал {channel} недоступен для анализа (API ограничение): {e}")
                raise AnalysisError(f"Канал ограничен для анализа через пользовательский API")
            else:
                raise

        posts: list[tuple[datetime, str]] = [(m.date, m.text) for m in messages]

        # Подсчёт репостов (сообщения с forward)
        repost_count = sum(1 for m in messages if m.forward is not None)
        total_messages = len(messages)
        repost_percent = round(repost_count / total_messages * 100, 1) if total_messages > 0 else 0.0

        if not posts:
            logger.warning(f"Канал {channel} пуст или нет текстовых сообщений")
            return AnalysisResult(title=title, subscribers=subscribers)

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
            return AnalysisResult(title=title, subscribers=subscribers)

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

        # Основные визуализации (всегда создаются)
        cloud_path = generate_main_cloud(channel_id, all_words, title)
        graph_path = generate_top_words_chart(channel_id, word_counter, title)

        # Инициализация путей для полного анализа
        mats_path = None
        pos_path = None
        agg_path = None
        weekday_path = None
        hour_path = None
        names_path = None
        phrases_path = None
        register_path = None
        dichotomy_path = None
        top_emojis = []
        unique_names_count = 0
        total_names_mentions = 0

        if lite_mode:
            # LITE MODE: только облако + топ слов
            logger.info(f"Lite-анализ канала {channel_id} (облако + топ-15)")
        else:
            # FULL MODE: все визуализации
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

        mode_str = "lite" if lite_mode else "full"
        logger.info(f"Анализ канала {channel_id} завершён успешно ({mode_str})")

        result = AnalysisResult(
            title=title,
            subscribers=subscribers,
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

        # Сохраняем в кэш для последующих запросов
        _save_to_cache(channel_id.lower(), result)

        # Выходим из приватного канала после анализа
        if is_private and entity:
            try:
                await client(LeaveChannelRequest(entity))
                logger.info(f"Вышли из приватного канала: {title}")
            except Exception as e:
                logger.warning(f"Не удалось выйти из канала: {e}")

        return result

    except FloodWaitError:
        raise  # Пробрасываем для обработки в handlers.py

    except Exception as e:
        logger.error(f"Ошибка анализа канала {channel}: {e}")
        raise AnalysisError(f"Не удалось проанализировать канал: {e}") from e
