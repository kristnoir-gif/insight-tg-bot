"""
Модуль анализа Telegram-каналов.
"""
import re
import os
import json
import shutil
import asyncio
from pathlib import Path
import functools
import logging
from dataclasses import dataclass, field, asdict
from collections import Counter
from datetime import datetime, timezone
from time import time as time_now

import aiohttp
from bs4 import BeautifulSoup

import numpy as np
from telethon import TelegramClient
from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError, FloodWaitError
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.types import User

from config import MOSCOW_TZ, DEFAULT_MESSAGE_LIMIT, DISK_CACHE_TTL, DISK_CACHE_TTL_LITE, FETCH_DELAY_EVERY_N, FETCH_DELAY_SECONDS, CACHE_DIR, WEB_PARSER_MAX_PAGES
from nlp.processor import get_clean_words, extract_emojis, extract_phrases, count_animals, count_food, count_cities
from nlp.constants import positive_words, aggressive_words, METAPHYSICS_WORDS, EVERYDAY_WORDS
from visualization.wordclouds import (
    generate_main_cloud,
    generate_sentiment_dual_cloud,
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
    generate_heatmap_chart,
    generate_mentions_chart,
)

logger = logging.getLogger(__name__)


async def _run_sync(func, *args, **kwargs):
    """Запускает синхронную функцию в executor чтобы не блокировать event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


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
class V2CardData:
    """Метрики для нового дизайна карточек (v2).

    Часть полей вычисляется из текста постов (chars, words, mat %, архетипы);
    поля total_photos/total_reactions/top_posts требуют расширенного источника
    (медиа-тип + реакции) и пока остаются placeholders (0/пусто) — заполнятся
    когда вызывающий код прокинет их через build_v2_card_data().
    """
    # 01 cover / 03 в цифрах
    total_posts: int = 0
    total_chars: int = 0
    total_words: int = 0
    total_photos: int = 0          # TODO: из источника (Telethon Message.media)
    max_consecutive_days: int = 0
    years_covered: int = 0
    start_date: str = ""           # ISO YYYY-MM-DD
    end_date: str = ""
    posts_per_day_avg: float = 0.0

    # 04 sum_of_reactions
    total_reactions: int = 0       # TODO: из источника (Telethon Message.reactions)
    avg_reactions_per_post: float = 0.0

    # 05 archetype_vocab
    vocab_archetype: str = ""      # Молчун / Стандарт / Эрудит / Интеллектуал / Гений

    # 06 chronotype
    peak_hour: int = 0
    chronotype_archetype: str = "" # Волк/Сова/Лунатик/Жаворонок/Синица/Белочка/Кот/Лиса/Хроно-хаос
    peak_bucket_share: float = 0.0 # % постов в 3-часовом «окне» вокруг пика — для подписи «N% постов»

    # 08 post_by_days_weeks
    favorite_weekday: int = 0      # 0=пн ... 6=вс

    # 10 archetype_bad
    mat_percent_of_text: float = 0.0
    posts_with_mat_percent: float = 0.0
    toxicity_archetype: str = ""   # Ангел / Сдержанный / Бурный / Ядовитый

    # 11 geography
    top_cities: list[tuple[str, int]] = field(default_factory=list)
    total_city_mentions: int = 0
    heart_city: str = ""

    # 13 emotions
    emotion_palette_name: str = "" # Драматическая / Радостная / Тревожная / Спокойная
    top_emoji: str = ""
    top_emoji_count: int = 0
    top_emojis_strip: list[str] = field(default_factory=list)  # 4 эмодзи для подпись «🙏😭😡😍»

    # Большой архетип канала по Юнгу (12 вариантов, классифицирует LLM)
    jungian_archetype: str = ""    # Мудрец / Искатель / ... / Маг

    # 14 one_phrase
    one_phrase_llm: str = ""       # TODO: отдельный LLM-вызов

    # 15 hit_post
    top_posts: list[dict] = field(default_factory=list)  # TODO: из источника

    # 16 reading_stats
    reading_time_hours: float = 0.0
    coffee_cups: int = 0
    sitcom_seasons: float = 0.0

    # 17 most_used_word
    top_word: str = ""
    top_word_count: int = 0

    # 07 word cloud — топ-150 слов с весами (используется в render_07_word_cloud
    # для генерации wordcloud на лету: белые слова, форма овала, прозрачный фон)
    top_words_for_cloud: list[tuple[str, int]] = field(default_factory=list)
    top_mat_words_for_cloud: list[tuple[str, int]] = field(default_factory=list)

    # 18 top_person
    top_names_with_counts: list[tuple[str, int]] = field(default_factory=list)


def _classify_vocab(unique_count: int) -> str:
    """8 уровней по unique_count — соответствуют variants.VOCAB_VARIANTS."""
    if unique_count < 9_247:      return ""                  # less_6000: без архетипа
    if unique_count < 12_247:     return "Интеллектуал"
    if unique_count < 15_000:     return "Мастер Слова"
    if unique_count < 18_237:     return "Лингвист"
    if unique_count < 22_237:     return "Поэт"
    if unique_count < 27_237:     return "Писатель"
    if unique_count < 36_237:     return "Великий Писатель"
    return "Лексический Титан"


def _classify_chronotype(peak_hour: int) -> str:
    """9 архетипов по часовому пику — соответствуют variants.CHRONOTYPE_VARIANTS."""
    if 21 <= peak_hour <= 23:    return "Волк"
    if  0 <= peak_hour <=  2:    return "Сова"
    if  3 <= peak_hour <=  5:    return "Лунатик"
    if  6 <= peak_hour <=  8:    return "Жаворонок"
    if  9 <= peak_hour <= 11:    return "Синица"
    if 12 <= peak_hour <= 14:    return "Белочка"
    if 15 <= peak_hour <= 17:    return "Кот"
    if 18 <= peak_hour <= 20:    return "Лиса"
    return "Хроно-хаос"


def _classify_toxicity(mat_pct: float) -> str:
    """7 уровней по mat % — соответствуют variants.TOXICITY_VARIANTS."""
    if mat_pct <= 0.001: return "Ангел"
    if mat_pct < 0.5:    return "Светлый"
    if mat_pct < 1.0:    return "Прямой"
    if mat_pct < 1.5:    return "Острый"
    if mat_pct < 2.5:    return "Ядовитый"
    if mat_pct < 5.0:    return "Ядерный"
    return "Дотер"


# Категории эмодзи для определения палитры эмоций
_EMOJI_DRAMA   = set("😭😢😡🤬💔😱😰😨🥺😔🥲")
_EMOJI_JOY     = set("😂🤣😍🥰❤️💕✨🔥🎉🥳😄😁🙂")
_EMOJI_CALM    = set("🤍😌🙏🕊️🌿🌸🍃☀️🌙")
_EMOJI_ANGER   = set("😤😠💢👿🤯🙄😒")

def _classify_emotion_palette(top_emojis: list[tuple[str, int]]) -> str:
    if not top_emojis:
        return "Нейтральная"
    score = {"Драматическая": 0, "Радостная": 0, "Спокойная": 0, "Тревожная": 0}
    for emoji, cnt in top_emojis[:15]:
        if emoji in _EMOJI_DRAMA: score["Драматическая"] += cnt
        elif emoji in _EMOJI_JOY: score["Радостная"]    += cnt
        elif emoji in _EMOJI_CALM: score["Спокойная"]   += cnt
        elif emoji in _EMOJI_ANGER: score["Тревожная"]  += cnt
    return max(score, key=score.get) if max(score.values()) > 0 else "Нейтральная"


def _max_consecutive_days(dates: list[datetime]) -> int:
    if not dates:
        return 0
    days = sorted({d.astimezone(MOSCOW_TZ).date() for d in dates})
    best = run = 1
    for prev, curr in zip(days, days[1:]):
        if (curr - prev).days == 1:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


# Скорость чтения и метафоры для карточки 16
_CHARS_PER_MINUTE = 1000          # ≈ 200 wpm, кириллица
_MINUTES_PER_COFFEE = 45          # одна чашка кофе ≈ 45 мин чтения
_MINUTES_PER_SITCOM_SEASON = 20 * 22  # 22 серии × 20 мин


def build_v2_card_data(
    posts: list[tuple[datetime, str]],
    all_words: list[str],
    mat_words: list[str],
    word_counter: "Counter",
    top_emojis: list[tuple[str, int]],
    hour_counts: "Counter",
    weekday_counts: "Counter",
    city_counter: "Counter",
    names_counter: "Counter",
    *,
    total_photos: int = 0,
    total_reactions: int = 0,
    top_posts: list[dict] | None = None,
) -> V2CardData:
    """Вычисляет V2CardData из агрегатов, уже собранных в `_run_analysis_pipeline`.

    Часть полей (фото, реакции, хит-посты) опциональна — передаётся когда
    источник их умеет отдавать (Telethon), иначе остаётся 0/пусто.
    """
    if not posts:
        return V2CardData()

    dates = [d for d, _ in posts]
    total_chars = sum(len(text or "") for _, text in posts)
    total_words = sum(len((text or "").split()) for _, text in posts)
    start = min(dates).astimezone(MOSCOW_TZ)
    end = max(dates).astimezone(MOSCOW_TZ)
    span_days = max((end - start).days + 1, 1)
    years_covered = max(end.year - start.year + 1, 1)
    posts_per_day = len(posts) / span_days

    # mat %
    mat_pct = (len(mat_words) / len(all_words) * 100) if all_words else 0.0
    posts_with_mat = 0
    if mat_words:
        mat_set = set(mat_words)
        from nlp.processor import get_clean_words  # отложенный импорт
        for _, text in posts:
            if any(w in mat_set for w in get_clean_words(text, "mats")):
                posts_with_mat += 1
    pwm_pct = (posts_with_mat / len(posts) * 100) if posts else 0.0

    unique_count = len({w for w in all_words})
    top_w, top_w_cnt = (word_counter.most_common(1)[0] if word_counter else ("", 0))

    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else 0
    fav_wd = max(weekday_counts, key=weekday_counts.get) if weekday_counts else 0
    # Доля постов в 3-часовом «окне» вокруг пика — для подписи «N% твоих постов».
    # Bucket'ы совпадают с архетипами хронотипа (variants.CHRONOTYPE_VARIANTS).
    _CHRONO_BUCKETS = [(21,22,23), (0,1,2), (3,4,5), (6,7,8),
                       (9,10,11), (12,13,14), (15,16,17), (18,19,20)]
    bucket = next((b for b in _CHRONO_BUCKETS if peak_hour in b), (peak_hour,))
    bucket_sum = sum(hour_counts.get(h, 0) for h in bucket)
    peak_share = (bucket_sum / len(posts) * 100) if posts else 0.0

    cities_top = city_counter.most_common(6) if city_counter else []
    total_city_mentions = sum(city_counter.values()) if city_counter else 0
    heart_city = cities_top[0][0] if cities_top else ""

    top_emoji, top_emoji_cnt = (top_emojis[0] if top_emojis else ("", 0))
    emojis_strip = [e for e, _ in top_emojis[:4]]
    palette = _classify_emotion_palette(top_emojis)

    # Чтение
    minutes_to_read = total_chars / _CHARS_PER_MINUTE if total_chars else 0
    reading_hours = round(minutes_to_read / 60, 1)
    coffee = int(round(minutes_to_read / _MINUTES_PER_COFFEE))
    sitcom = round(minutes_to_read / _MINUTES_PER_SITCOM_SEASON, 1)

    avg_reactions = (total_reactions / len(posts)) if (total_reactions and posts) else 0.0

    return V2CardData(
        total_posts=len(posts),
        total_chars=total_chars,
        total_words=total_words,
        total_photos=total_photos,
        max_consecutive_days=_max_consecutive_days(dates),
        years_covered=years_covered,
        start_date=start.date().isoformat(),
        end_date=end.date().isoformat(),
        posts_per_day_avg=round(posts_per_day, 1),

        total_reactions=total_reactions,
        avg_reactions_per_post=round(avg_reactions, 1),

        vocab_archetype=_classify_vocab(unique_count),

        peak_hour=peak_hour,
        chronotype_archetype=_classify_chronotype(peak_hour),
        peak_bucket_share=round(peak_share, 0),

        favorite_weekday=fav_wd,

        mat_percent_of_text=round(mat_pct, 1),
        posts_with_mat_percent=round(pwm_pct, 1),
        toxicity_archetype=_classify_toxicity(mat_pct),

        top_cities=cities_top,
        total_city_mentions=total_city_mentions,
        heart_city=heart_city,

        emotion_palette_name=palette,
        top_emoji=top_emoji,
        top_emoji_count=top_emoji_cnt,
        top_emojis_strip=emojis_strip,

        top_posts=top_posts or [],

        reading_time_hours=reading_hours,
        coffee_cups=coffee,
        sitcom_seasons=sitcom,

        top_word=top_w,
        top_word_count=top_w_cnt,
        top_words_for_cloud=word_counter.most_common(150) if word_counter else [],
        top_mat_words_for_cloud=(
            list(Counter(mat_words).most_common(80)) if mat_words else []
        ),

        top_names_with_counts=names_counter.most_common(6) if names_counter else [],
    )


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
    sentiment_path: str | None = None
    weekday_path: str | None = None
    hour_path: str | None = None
    names_path: str | None = None
    phrases_path: str | None = None
    register_path: str | None = None
    dichotomy_path: str | None = None
    heatmap_path: str | None = None
    archetype_path: str | None = None
    topics_path: str | None = None
    insights_path: str | None = None
    mentions_path: str | None = None

    # AI-анализ личности автора
    personality_text: str | None = None
    # AI-анализ контента канала
    content_analysis_text: str | None = None

    # Архетип и факты (для карточки)
    archetype_name: str | None = None
    fun_facts: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)

    # Данные
    top_emojis: list[tuple[str, int]] = field(default_factory=list)
    from_cache: bool = False  # Флаг: результат из кэша

    # Метрики для v2-дизайна карточек (см. visualization/v2_cards/)
    v2: V2CardData = field(default_factory=V2CardData)

    def get_all_paths(self) -> list[str]:
        """Возвращает список всех путей к файлам."""
        paths = [
            self.cloud_path, self.graph_path, self.mats_path,
            self.sentiment_path, self.weekday_path,
            self.hour_path, self.names_path, self.phrases_path,
            self.register_path, self.dichotomy_path, self.heatmap_path,
            self.archetype_path, self.topics_path, self.insights_path,
            self.mentions_path,
        ]
        return [p for p in paths if p]


def generate_insights(
    hour_counts: dict[int, int],
    weekday_counts: dict[int, int],
    pos_percent: float,
    agg_percent: float,
    meta_percent: float,
    everyday_percent: float,
    unique_names_count: int,
    total_names_mentions: int,
    top_phrases: list[tuple[tuple[str, ...], int]],
    word_counter: "Counter",
    total_posts: int,
    repost_percent: float,
    avg_len: float,
    scream_index: float,
    night_post_percent: float,
) -> list[str]:
    """Генерирует текстовые инсайты по метрикам канала — один на каждый график."""
    insights = []
    weekdays_names = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье']

    # 1. Активность по часам
    if hour_counts:
        peak_h = max(hour_counts, key=hour_counts.get)
        if 6 <= peak_h <= 9:
            insights.append(f"⏰ Пик постов в {peak_h}:00 — канал целится в утреннюю аудиторию")
        elif 10 <= peak_h <= 13:
            insights.append(f"⏰ Пик постов в {peak_h}:00 — дневной ритм, контент для обеденного перерыва")
        elif 14 <= peak_h <= 18:
            insights.append(f"⏰ Пик постов в {peak_h}:00 — вечерний прайм-тайм")
        elif 19 <= peak_h <= 22:
            insights.append(f"⏰ Пик постов в {peak_h}:00 — ловит аудиторию на отдыхе")
        else:
            insights.append(f"⏰ Пик постов в {peak_h}:00 — автор-полуночник")

    # 2. Активность по дням
    if weekday_counts:
        peak_wd = max(weekday_counts, key=weekday_counts.get)
        min_wd = min(weekday_counts, key=weekday_counts.get)
        weekend_posts = weekday_counts.get(5, 0) + weekday_counts.get(6, 0)
        weekday_posts = sum(weekday_counts.get(d, 0) for d in range(5))
        if weekend_posts > weekday_posts * 0.5 and weekday_posts > 0:
            insights.append("📅 Активен по выходным — канал не знает отдыха")
        elif weekend_posts == 0 and total_posts > 30:
            insights.append("📅 Мёртвая зона — выходные. Канал работает как офис 5/2")
        elif peak_wd in (5, 6):
            insights.append(f"📅 Больше всего постов в {weekdays_names[peak_wd]} — работает на выходных")
        else:
            insights.append(f"📅 Самый продуктивный день — {weekdays_names[peak_wd]}")

    # 3. Тональность
    if pos_percent > 0 or agg_percent > 0:
        if pos_percent > 70:
            insights.append(f"😊 {pos_percent:.0f}% позитивных слов — один из самых светлых каналов")
        elif agg_percent > 50:
            insights.append(f"😤 {agg_percent:.0f}% агрессивной лексики — канал не для слабонервных")
        elif pos_percent > agg_percent:
            insights.append(f"😊 Позитив перевешивает: {pos_percent:.0f}% против {agg_percent:.0f}% агрессии")
        else:
            insights.append(f"⚡ Агрессия перевешивает позитив: {agg_percent:.0f}% против {pos_percent:.0f}%")

    # 4. Дихотомия
    if meta_percent > 0 or everyday_percent > 0:
        if meta_percent > 70:
            insights.append(f"🧠 Канал на {meta_percent:.0f}% метафизичен — философия, абстракции, глубина")
        elif everyday_percent > 70:
            insights.append(f"🏠 Канал на {everyday_percent:.0f}% бытовой — конкретика, жизнь, практика")
        elif meta_percent > 55:
            insights.append(f"🧠 Баланс смещён в сторону абстрактного ({meta_percent:.0f}% метафизика)")
        else:
            insights.append(f"🏠 Баланс смещён в сторону бытового ({everyday_percent:.0f}% повседневное)")

    # 5. Упоминания имён
    if unique_names_count > 0:
        if unique_names_count > 50:
            insights.append(f"👥 {unique_names_count} упомянутых личностей — автор знает полгорода")
        elif unique_names_count > 20:
            insights.append(f"👥 {unique_names_count} личностей — канал с широким кругом героев")
        elif total_names_mentions > 0 and unique_names_count <= 5:
            avg_mentions = total_names_mentions / max(unique_names_count, 1)
            if avg_mentions > 5:
                insights.append(f"👤 Всего {unique_names_count} имён, но каждое повторяется ~{avg_mentions:.0f} раз — узкий круг")

    # 6. Фразы
    if top_phrases:
        phrase_str = " ".join(top_phrases[0][0])
        phrase_count = top_phrases[0][1]
        if phrase_count > total_posts * 0.1:
            insights.append(f"💬 «{phrase_str}» встречается {phrase_count} раз — привычка автора")
        elif phrase_count > 5:
            insights.append(f"💬 Любимая фраза — «{phrase_str}» ({phrase_count} раз)")

    # 7. Облако слов (топ-слово)
    if word_counter:
        top_word, top_count = word_counter.most_common(1)[0]
        per_post = top_count / max(total_posts, 1)
        if per_post > 0.5:
            insights.append(f"🔤 «{top_word}» — в каждом втором посте. Главная тема канала?")
        elif per_post > 0.3:
            insights.append(f"🔤 «{top_word}» встречается в каждом 3-м посте")

    # 8. Тепловая карта (паттерн активности)
    if hour_counts and weekday_counts and night_post_percent > 30:
        insights.append(f"🌙 {night_post_percent:.0f}% постов написаны ночью (23:00–05:00)")

    # 9. Репосты
    if repost_percent > 50:
        insights.append(f"🔄 {repost_percent:.0f}% контента — репосты. Это канал-куратор, не автор")
    elif repost_percent == 0 and total_posts > 30:
        insights.append("✍️ 0% репостов — 100% авторский контент")

    return insights


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
        if time_now() - cached_at < DISK_CACHE_TTL:
            return True
    except (json.JSONDecodeError, OSError):
        pass

    return False


def _load_from_cache(channel_id: str, require_full: bool = False) -> AnalysisResult | None:
    """Загружает результат из кэша. Если require_full=True, пропускает lite-кэш."""
    cache_path = _get_cache_path(channel_id)
    meta_path = os.path.join(cache_path, "meta.json")

    try:
        with open(meta_path, "r") as f:
            meta = json.load(f)

        # Если нужен full-анализ, а в кэше lite — пропускаем
        if require_full and meta.get("lite", False):
            logger.info(f"Кэш для {channel_id} — lite, нужен full, пропускаем")
            return None

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

        result.personality_text = meta.get("personality_text")
        result.content_analysis_text = meta.get("content_analysis_text")
        result.archetype_name = meta.get("archetype_name")
        result.fun_facts = meta.get("fun_facts", [])
        result.topics = meta.get("topics", [])
        result.insights = meta.get("insights", [])

        # v2 card data (новые поля — старые кэши не имеют этого блока)
        v2_meta = meta.get("v2") or {}
        if v2_meta:
            # Списки кортежей в JSON становятся списками списков — конвертируем обратно
            v2_meta["top_cities"] = [tuple(x) for x in v2_meta.get("top_cities", [])]
            v2_meta["top_names_with_counts"] = [tuple(x) for x in v2_meta.get("top_names_with_counts", [])]
            try:
                result.v2 = V2CardData(**v2_meta)
            except TypeError:
                # Поле в кэше из устаревшей версии — пропускаем, оставляем дефолт
                pass

        # Копируем изображения из кэша во временные файлы
        for img_name in ["cloud.png", "graph.png", "mats.png", "sentiment.png",
                         "weekday.png", "hour.png",
                         "names.png", "phrases.png", "register.png", "dichotomy.png",
                         "heatmap.png", "archetype.png", "topics.png", "insights.png"]:
            src = os.path.join(cache_path, img_name)
            if os.path.exists(src):
                dst = f"{channel_id}_{img_name}"
                shutil.copy(src, dst)
                attr_name = img_name.replace(".png", "_path")
                setattr(result, attr_name, dst)

        logger.info(f"Загружен кэш для канала {channel_id}")
        return result

    except (json.JSONDecodeError, OSError, KeyError) as e:
        logger.warning(f"Ошибка загрузки кэша: {e}")
        return None


def _save_to_cache(channel_id: str, result: AnalysisResult, lite_mode: bool = False) -> None:
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
            "personality_text": result.personality_text,
            "content_analysis_text": result.content_analysis_text,
            "archetype_name": result.archetype_name,
            "fun_facts": result.fun_facts,
            "topics": result.topics,
            "insights": result.insights,
            "v2": asdict(result.v2),
            "lite": lite_mode,
        }
        with open(os.path.join(cache_path, "meta.json"), "w") as f:
            json.dump(meta, f)

        # Копируем изображения в кэш
        path_mapping = {
            "cloud.png": result.cloud_path,
            "graph.png": result.graph_path,
            "mats.png": result.mats_path,
            "sentiment.png": result.sentiment_path,
            "weekday.png": result.weekday_path,
            "hour.png": result.hour_path,
            "names.png": result.names_path,
            "phrases.png": result.phrases_path,
            "register.png": result.register_path,
            "dichotomy.png": result.dichotomy_path,
            "heatmap.png": result.heatmap_path,
            "archetype.png": result.archetype_path,
            "topics.png": result.topics_path,
            "insights.png": result.insights_path,
        }
        for cache_name, src_path in path_mapping.items():
            if src_path and os.path.exists(src_path):
                shutil.copy(src_path, os.path.join(cache_path, cache_name))

        logger.info(f"Сохранён кэш для канала {channel_id}")

    except OSError as e:
        logger.warning(f"Ошибка сохранения кэша: {e}")


async def _fetch_posts_from_web(channel_username: str, limit: int = 500) -> tuple[str, int, list[tuple[datetime, str]]]:
    """
    Парсит посты публичного канала через t.me/s/channel с пагинацией.
    Возвращает (title, subscribers, posts).
    Не требует аккаунта — обычный HTTP.
    """
    posts = []
    title = channel_username
    subscribers = 0
    before_id = None

    async with aiohttp.ClientSession() as session:
        for page in range(WEB_PARSER_MAX_PAGES):
            url = f"https://t.me/s/{channel_username}"
            if before_id:
                url += f"?before={before_id}"

            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        break
                    html = await resp.text()
            except Exception as e:
                logger.warning(f"Web fetch error page {page}: {e}")
                break

            soup = BeautifulSoup(html, 'html.parser')

            # Название канала (только с первой страницы)
            if page == 0:
                title_el = soup.find('div', class_='tgme_channel_info_header_title')
                if title_el:
                    title = title_el.get_text(strip=True)
                extra_el = soup.find('div', class_='tgme_channel_info_counter')
                if not extra_el:
                    extra_el = soup.find('div', class_='tgme_page_extra')
                if extra_el:
                    match = re.search(r'([\d\s,.]+)', extra_el.get_text())
                    if match:
                        try:
                            subscribers = int(re.sub(r'[\s,.]', '', match.group(1)))
                        except ValueError:
                            pass

            # Парсим посты
            msg_widgets = soup.find_all('div', class_='tgme_widget_message_wrap')
            if not msg_widgets:
                break

            min_id = None
            for widget in msg_widgets:
                msg_div = widget.find('div', class_='tgme_widget_message')
                if not msg_div:
                    continue

                # ID поста
                data_post = msg_div.get('data-post', '')
                msg_id_str = data_post.split('/')[-1] if '/' in data_post else ''
                try:
                    msg_id = int(msg_id_str)
                except ValueError:
                    continue

                if min_id is None or msg_id < min_id:
                    min_id = msg_id

                # Текст
                text_div = msg_div.find('div', class_='tgme_widget_message_text')
                if not text_div:
                    continue
                text = text_div.get_text(separator=' ', strip=True)
                if not text:
                    continue

                # Дата
                time_el = msg_div.find('time')
                if time_el and time_el.get('datetime'):
                    try:
                        dt = datetime.fromisoformat(time_el['datetime'].replace('+00:00', '+00:00'))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        dt = datetime.now(timezone.utc)
                else:
                    dt = datetime.now(timezone.utc)

                posts.append((dt, text))

            if min_id is None or len(posts) >= limit:
                break

            before_id = min_id
            await asyncio.sleep(0.3)  # вежливая пауза

    # Убираем дубликаты по тексту, сохраняя порядок
    seen = set()
    unique_posts = []
    for dt, text in posts:
        if text not in seen:
            seen.add(text)
            unique_posts.append((dt, text))

    return title, subscribers, unique_posts[:limit]


async def fetch_channel_posts(channel: str, limit: int = 500) -> tuple[str, int, list[str]] | None:
    """
    Получает посты канала через веб-парсинг (без Telethon).
    Возвращает (title, subscribers, texts) или None при ошибке.
    """
    try:
        channel_key = str(channel).lstrip('@').split('/')[-1].strip().lower()
        title, subscribers, posts = await _fetch_posts_from_web(channel_key, limit)
        if not posts:
            return None
        texts = [text for _, text in posts]
        return title, subscribers, texts
    except Exception as e:
        logger.warning(f"fetch_channel_posts failed for {channel}: {e}")
        return None


async def _run_analysis_pipeline(
    posts: list[tuple[datetime, str]],
    channel_id: str,
    title: str,
    subscribers: int,
    lite_mode: bool,
    repost_count: int = 0,
    repost_percent: float = 0.0,
    enable_llm: bool = False,
    *,
    total_photos: int = 0,
    total_reactions: int = 0,
    top_posts: list[dict] | None = None,
) -> AnalysisResult:
    """
    Общая логика анализа постов канала: извлечение слов, генерация графиков, статистика.

    Используется и для Telethon, и для веб-парсинга.
    """
    # Извлечение слов и метрик из постов
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
        return AnalysisResult(title=title, subscribers=subscribers)

    word_counter = Counter(all_words)

    # Подсчёт тематических слов
    all_texts_plain = [text for _, text in posts]
    animal_counter = count_animals(all_texts_plain)
    food_counter = count_food(all_texts_plain)
    city_counter = count_cities(all_texts_plain)

    # Инициализация путей
    mats_path = sentiment_path = weekday_path = hour_path = None
    heatmap_path = names_path = phrases_path = register_path = dichotomy_path = None
    mentions_path = None
    personality_result = None
    top_emojis = []
    unique_names_count = 0
    total_names_mentions = 0
    pos_percent = agg_percent = meta_percent = everyday_percent = 0.0
    night_post_percent = 0.0
    hour_counts: Counter = Counter()
    weekday_counts: Counter = Counter()
    top_phrases: list = []
    names_counter: Counter = Counter()

    if lite_mode:
        # LITE MODE: только облако + топ слов (параллельно)
        cloud_path, graph_path = await asyncio.gather(
            _run_sync(generate_main_cloud, channel_id, all_words, title),
            _run_sync(generate_top_words_chart, channel_id, word_counter, title),
        )
    else:
        # FULL MODE: вычисляем данные, затем запускаем все 12 графиков параллельно
        weekday_counts = Counter(date.astimezone(MOSCOW_TZ).weekday() for date, _ in posts)
        hour_counts = Counter(date.astimezone(MOSCOW_TZ).hour for date, _ in posts)
        heatmap_times = [
            (date.astimezone(MOSCOW_TZ).weekday(), date.astimezone(MOSCOW_TZ).hour)
            for date, _ in posts
        ]

        names_counter = Counter(names)
        unique_names_count = len(names_counter)
        total_names_mentions = len(names)
        top_names = names_counter.most_common(100)

        all_texts = [text for _, text in posts]
        top_phrases = extract_phrases(all_texts, n=3)[:10]

        # Облако регистра (CAPS vs lowercase)
        caps_words: list[str] = []
        lower_words: list[str] = []
        total_register_words = 0
        for _, text in posts:
            words = re.findall(r'[а-яА-ЯёЁ]{3,}', text)
            for word in words:
                total_register_words += 1
                if word.isupper():
                    caps_words.append(word)
                elif word.islower():
                    lower_words.append(word)
        caps_percent = (len(caps_words) / total_register_words * 100) if total_register_words > 0 else 0
        lower_percent = (len(lower_words) / total_register_words * 100) if total_register_words > 0 else 0

        # Дихотомия языка (метафизика vs быт)
        dichotomy_total = len(metaphysics_words) + len(everyday_words)
        meta_percent = (len(metaphysics_words) / dichotomy_total * 100) if dichotomy_total > 0 else 0
        everyday_percent = (len(everyday_words) / dichotomy_total * 100) if dichotomy_total > 0 else 0

        # Эмодзи
        emoji_freq = Counter(all_emojis)
        top_emojis = emoji_freq.most_common(20)

        # Вычисляем проценты тональности
        sentiment_total = len(pos_words) + len(agg_words)
        pos_percent = (len(pos_words) / sentiment_total * 100) if sentiment_total > 0 else 0
        agg_percent = (len(agg_words) / sentiment_total * 100) if sentiment_total > 0 else 0

        # Запускаем все 11 графиков (+ LLM если включён) параллельно
        charts_coro = asyncio.gather(
            _run_sync(generate_main_cloud, channel_id, all_words, title),
            _run_sync(generate_top_words_chart, channel_id, word_counter, title),
            _run_sync(generate_mats_cloud, channel_id, mat_words, title),
            _run_sync(generate_sentiment_dual_cloud, channel_id, pos_words, agg_words, title,
                      pos_percent, agg_percent),
            _run_sync(generate_weekday_chart, channel_id, dict(weekday_counts), title),
            _run_sync(generate_hour_chart, channel_id, dict(hour_counts), title),
            _run_sync(generate_heatmap_chart, channel_id, heatmap_times, title),
            _run_sync(generate_names_chart, channel_id, top_names, title,
                      total_unique_names=unique_names_count, total_mentions=total_names_mentions),
            _run_sync(generate_phrases_chart, channel_id, top_phrases, title),
            _run_sync(generate_register_cloud, channel_id, caps_words, lower_words, title,
                      caps_percent, lower_percent),
            _run_sync(generate_dichotomy_cloud, channel_id, metaphysics_words, everyday_words, title,
                      meta_percent, everyday_percent),
            _run_sync(generate_mentions_chart, channel_id, animal_counter, food_counter, city_counter, title),
        )
        if enable_llm:
            from llm import generate_content_analysis

            # Собираем текстовую сводку метрик для анализа контента
            weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            peak_h = max(hour_counts, key=hour_counts.get) if hour_counts else 0
            peak_wd = max(weekday_counts, key=weekday_counts.get) if weekday_counts else 0
            top10_words = ", ".join(w for w, _ in word_counter.most_common(10))
            top5_emojis_str = ", ".join(f"{e} x{c}" for e, c in (emoji_freq.most_common(5) if emoji_freq else []))

            # Период канала
            dates_sorted = sorted(d for d, _ in posts)
            date_range = f"{dates_sorted[0].strftime('%d.%m.%Y')} — {dates_sorted[-1].strftime('%d.%m.%Y')}" if dates_sorted else "?"

            content_stats_text = (
                f"Постов: {len(posts)}\n"
                f"Период: {date_range}\n"
                f"Репосты: {repost_count} ({repost_percent:.0f}%)\n"
                f"Средняя длина поста: {round(np.mean([len(p[1].split()) for p in posts]), 1)} слов\n"
                f"Уникальных слов: {len(set(all_words))}\n"
                f"Пиковый час: {peak_h}:00\n"
                f"Пиковый день: {weekday_names[peak_wd]}\n"
                f"ТОП-10 слов: {top10_words}\n"
                f"ТОП эмодзи: {top5_emojis_str}\n"
                f"Позитивных слов: {pos_percent:.0f}% | Агрессивных: {agg_percent:.0f}%\n"
                f"Метафизика: {meta_percent:.0f}% | Быт: {everyday_percent:.0f}%\n"
                f"CAPS индекс: {round(np.mean(upper_ratios) * 100 + np.mean(excl_counts) * 10, 1) if upper_ratios else 0}"
            )

            llm_content_coro = generate_content_analysis(title, subscribers, content_stats_text, all_texts)
            charts_results, content_analysis_result = await asyncio.gather(
                charts_coro, llm_content_coro, return_exceptions=True,
            )
            if isinstance(charts_results, BaseException):
                raise charts_results
            if isinstance(content_analysis_result, BaseException):
                logger.warning(f"LLM content failed: {content_analysis_result}")
                content_analysis_result = None
        else:
            charts_results = await charts_coro
            content_analysis_result = None

        (cloud_path, graph_path, mats_path, sentiment_path,
         weekday_path, hour_path, heatmap_path, names_path,
         phrases_path, register_path, dichotomy_path,
         mentions_path) = charts_results

    # Расчёт статистики
    avg_upper = np.mean(upper_ratios) if upper_ratios else 0
    avg_excl = np.mean(excl_counts) if excl_counts else 0
    scream_index = round(avg_upper * 100 + avg_excl * 10, 1)
    unique_count = len(set(all_words))
    avg_len_val = round(np.mean([len(p[1].split()) for p in posts]), 1)

    stats = ChannelStats(
        unique_count=unique_count,
        avg_len=avg_len_val,
        scream_index=scream_index,
        unique_names_count=unique_names_count,
        total_names_mentions=total_names_mentions,
        repost_count=repost_count,
        repost_percent=repost_percent,
    )

    # Архетип канала (только full mode)
    archetype_path = None
    archetype_name = None
    fun_facts_list: list[str] = []

    if not lite_mode:
        from visualization.archetype import classify_archetype, generate_archetype_card, generate_fun_facts

        # Доля ночных постов (23:00-05:00)
        night_posts = sum(1 for d, _ in posts
                          if d.astimezone(MOSCOW_TZ).hour >= 23 or d.astimezone(MOSCOW_TZ).hour <= 4)
        night_post_percent = (night_posts / len(posts) * 100) if posts else 0

        # Пик по часам и дням
        peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None
        peak_weekday = max(weekday_counts, key=weekday_counts.get) if weekday_counts else None

        top_word = word_counter.most_common(1)[0][0] if word_counter else None
        top_word_count = word_counter.most_common(1)[0][1] if word_counter else 0
        top_emoji_item = top_emojis[0][0] if top_emojis else None

        archetype = classify_archetype(
            scream_index=scream_index,
            avg_len=avg_len_val,
            unique_count=unique_count,
            mat_count=len(mat_words),
            pos_percent=pos_percent,
            agg_percent=agg_percent,
            meta_percent=meta_percent,
            everyday_percent=everyday_percent,
            names_count=unique_names_count,
            emoji_count=len(all_emojis),
            repost_percent=repost_percent,
            night_post_percent=night_post_percent,
            total_posts=len(posts),
        )
        archetype_name = archetype.name

        fun_facts_list = generate_fun_facts(
            scream_index=scream_index,
            avg_len=avg_len_val,
            unique_count=unique_count,
            total_posts=len(posts),
            top_word=top_word,
            top_word_count=top_word_count,
            mat_count=len(mat_words),
            pos_percent=pos_percent,
            agg_percent=agg_percent,
            night_post_percent=night_post_percent,
            peak_hour=peak_hour,
            peak_weekday=peak_weekday,
            names_count=unique_names_count,
            repost_percent=repost_percent,
            emoji_count=len(all_emojis),
            top_emoji=top_emoji_item,
        )

        stats_summary = {
            'post_count': len(posts),
            'unique_count': unique_count,
            'avg_len': avg_len_val,
            'scream_index': scream_index,
            'top_word': top_word,
            'top_emoji': top_emoji_item,
            'peak_hour': peak_hour,
            'subscribers': subscribers,
            'fun_facts': fun_facts_list,
            'pos_percent': pos_percent,
            'night_post_percent': night_post_percent,
            'repost_percent': repost_percent,
        }

        archetype_path = await _run_sync(
            generate_archetype_card, channel_id, title, archetype, stats_summary
        )

    # Топ-3 темы канала через LLM (только full mode)
    topics_path = None
    topics_list: list[str] = []

    if not lite_mode:
        from llm import generate_topics
        from visualization.archetype import generate_topics_card

        all_texts = [text for _, text in posts]
        top_words_list = [w for w, _ in word_counter.most_common(50)]
        topics_list = await generate_topics(title, top_words_list, all_texts) or []

        if topics_list:
            topics_path = await _run_sync(
                generate_topics_card, channel_id, title, topics_list
            )

    # Инсайты по графикам (только full mode)
    insights_list: list[str] = []
    insights_path = None
    if not lite_mode:
        insights_list = generate_insights(
            hour_counts=dict(hour_counts),
            weekday_counts=dict(weekday_counts),
            pos_percent=pos_percent,
            agg_percent=agg_percent,
            meta_percent=meta_percent,
            everyday_percent=everyday_percent,
            unique_names_count=unique_names_count,
            total_names_mentions=total_names_mentions,
            top_phrases=top_phrases,
            word_counter=word_counter,
            total_posts=len(posts),
            repost_percent=repost_percent,
            avg_len=avg_len_val,
            scream_index=scream_index,
            night_post_percent=night_post_percent,
        )
        if insights_list:
            from visualization.archetype import generate_insights_card
            insights_path = await _run_sync(
                generate_insights_card, channel_id, title, insights_list
            )

    # Метрики для нового дизайна карточек (v2)
    v2_data = build_v2_card_data(
        posts=posts,
        all_words=all_words,
        mat_words=mat_words,
        word_counter=word_counter,
        top_emojis=top_emojis,
        hour_counts=hour_counts,
        weekday_counts=weekday_counts,
        city_counter=city_counter,
        names_counter=names_counter,
        total_photos=total_photos,
        total_reactions=total_reactions,
        top_posts=top_posts,
    )

    # LLM-обогащение v2 (one_phrase + jungian архетип)
    if not lite_mode:
        try:
            from llm import generate_one_phrase, classify_jungian_archetype
            sample_texts = [t for _, t in posts if t and len(t) > 20][:50]
            phrase = await generate_one_phrase(title, sample_texts) if sample_texts else None
            if phrase:
                v2_data.one_phrase_llm = phrase

            # Сигналы для Юнгианского классификатора
            signals = {
                "топ-слова": ", ".join(w for w, _ in word_counter.most_common(15)) if word_counter else "",
                "топ-эмодзи": ", ".join(e for e, _ in top_emojis[:5]) if top_emojis else "",
                "топ-фразы": ", ".join(" ".join(p) for p, _ in top_phrases[:5]) if top_phrases else "",
                "темы (LLM)": ", ".join(topics_list) if topics_list else "",
                "хронотип": v2_data.chronotype_archetype,
                "vocab уровень": v2_data.vocab_archetype,
                "mat %": f"{v2_data.mat_percent_of_text}",
                "позитив %": f"{pos_percent:.1f}",
                "агрессия %": f"{agg_percent:.1f}",
                "метафизика %": f"{meta_percent:.1f}",
                "повседневное %": f"{everyday_percent:.1f}",
                "ср. длина поста": f"{avg_len_val:.0f}",
                "scream (КАПС) индекс": f"{scream_index:.1f}",
                "ночные посты %": f"{night_post_percent:.1f}",
                "репост %": f"{repost_percent:.1f}",
            }
            jungian = await classify_jungian_archetype(title, signals)
            if jungian:
                v2_data.jungian_archetype = jungian
        except Exception as e:  # noqa: BLE001
            logger.warning(f"LLM v2 enrichment failed: {e}")

    return AnalysisResult(
        title=title, subscribers=subscribers, stats=stats,
        cloud_path=cloud_path, graph_path=graph_path,
        mats_path=mats_path, sentiment_path=sentiment_path,
        weekday_path=weekday_path, hour_path=hour_path,
        names_path=names_path, phrases_path=phrases_path,
        register_path=register_path, dichotomy_path=dichotomy_path,
        heatmap_path=heatmap_path, archetype_path=archetype_path,
        topics_path=topics_path,
        insights_path=insights_path,
        mentions_path=mentions_path,
        personality_text=None,
        content_analysis_text=content_analysis_result if not lite_mode else None,
        top_emojis=top_emojis,
        archetype_name=archetype_name,
        fun_facts=fun_facts_list,
        topics=topics_list,
        insights=insights_list,
        v2=v2_data,
    )


async def analyze_channel_from_json(
    json_path: str,
    *,
    lite_mode: bool = False,
    enable_llm: bool = False,
) -> AnalysisResult | None:
    """Анализирует канал из JSON-экспорта Telegram Desktop.

    Преимущество над web/Telethon — полная история канала + фото + реакции,
    без рейт-лимитов. Юзер делает Settings → Advanced → Export Telegram data
    → JSON и присылает result.json (или ZIP с ним).
    """
    from telegram_export import parse_telegram_export

    logger.info(f"[JSON] Парсю экспорт: {json_path}")
    export = parse_telegram_export(json_path)
    if not export.posts:
        logger.warning(f"[JSON] В экспорте нет постов: {json_path}")
        return None

    channel_key = export.channel_id or Path(json_path).stem
    logger.info(
        f"[JSON] {export.name!r}: {len(export.posts)} постов, "
        f"{export.total_photos} фото, {export.total_reactions} реакций"
    )

    result = await _run_analysis_pipeline(
        export.posts,
        channel_key,
        export.name,
        subscribers=0,            # JSON-экспорт не содержит счётчика подписчиков
        lite_mode=lite_mode,
        enable_llm=enable_llm,
        total_photos=export.total_photos,
        total_reactions=export.total_reactions,
        top_posts=export.top_posts,
    )
    return result


async def analyze_channel_web(
    channel: str,
    limit: int = DEFAULT_MESSAGE_LIMIT,
    lite_mode: bool = False,
    enable_llm: bool = False,
) -> AnalysisResult | None:
    """
    Анализирует публичный канал через веб-парсинг (без Telethon-аккаунта).
    Используется как фоллбэк при FloodWait всех аккаунтов.
    """
    channel_key = str(channel).lstrip('@').split('/')[-1].strip().lower()

    # Проверяем кэш
    if _is_cache_valid(channel_key):
        cached_result = _load_from_cache(channel_key, require_full=not lite_mode)
        if cached_result and cached_result.cloud_path:
            logger.info(f"[WEB] Используем кэш для канала {channel}")
            return cached_result

    logger.info(f"[WEB] Начат веб-анализ канала: {channel}")
    title, subscribers, posts = await _fetch_posts_from_web(channel_key, limit)

    if not posts:
        logger.warning(f"[WEB] Канал {channel} пуст или недоступен")
        return None

    logger.info(f"[WEB] Получено {len(posts)} постов из канала {channel}")

    result = await _run_analysis_pipeline(
        posts, channel_key, title, subscribers, lite_mode,
        enable_llm=enable_llm,
    )

    if not result.cloud_path:
        logger.warning(f"[WEB] Не удалось извлечь слова из канала {channel}")
        return result

    _save_to_cache(channel_key, result, lite_mode=lite_mode)
    logger.info(f"[WEB] Анализ канала {channel_key} завершён ({len(posts)} постов)")
    return result


async def analyze_channel(
    client: TelegramClient,
    channel: str | int,
    limit: int = DEFAULT_MESSAGE_LIMIT,
    is_private: bool = False,
    lite_mode: bool = False,
    enable_llm: bool = False,
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

    # Проверяем кэш
    if _is_cache_valid(channel_key):
        cached_result = _load_from_cache(channel_key, require_full=not lite_mode)
        if cached_result and cached_result.cloud_path:
            logger.info(f"Используем кэш для канала {channel}")
            return cached_result

    try:
        if not client.is_connected():
            await client.connect()

        logger.info(f"Начат анализ канала: {channel}")

        # Если channel — числовая строка, преобразуем в int (Telethon иначе считает это телефоном)
        if isinstance(channel, str) and channel.isdigit():
            channel = int(channel)

        # Получение данных канала с fallback
        entity = None
        try:
            if joined_chat:
                entity = joined_chat
            else:
                entity = await client.get_entity(channel)
        except ValueError as e:
            error_msg = str(e)
            if "Could not find the input entity" in error_msg:
                if is_private:
                    logger.warning(f"Приватный канал {channel} не найден после присоединения")
                    raise AnalysisError(f"Нет доступа к приватному каналу или ссылка истекла")
                else:
                    logger.warning(f"Канал {channel} не найден по ID, пробую как username")
                    clean_channel = str(channel).lstrip('@').split('/')[-1].strip()
                    if clean_channel:
                        try:
                            entity = await client.get_entity(clean_channel)
                        except (ValueError, UsernameNotOccupiedError, UsernameInvalidError):
                            pass
            elif "No user has" in error_msg:
                raise AnalysisError("Канал не найден. Проверьте правильность юзернейма.") from e
            if entity is None:
                raise

        if isinstance(entity, User):
            raise AnalysisError("Это аккаунт пользователя, а не канал. Отправьте юзернейм канала.")

        title = entity.title
        subscribers = 0 if is_private else (getattr(entity, 'participants_count', 0) or 0)
        channel_id = getattr(entity, 'username', None) or str(entity.id)

        # Получаем сообщения с задержками для предотвращения FloodWait
        messages = []
        msg_count = 0
        try:
            async for m in client.iter_messages(entity, limit=limit):
                if m.text:
                    messages.append(m)
                msg_count += 1
                if msg_count % FETCH_DELAY_EVERY_N == 0:
                    await asyncio.sleep(FETCH_DELAY_SECONDS)
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

        # Диагностика периода
        oldest = min(d for d, _ in posts)
        newest = max(d for d, _ in posts)
        logger.info(
            f"Канал: {channel_id} | Постов: {len(posts)} | "
            f"Период: {oldest.astimezone(MOSCOW_TZ).strftime('%Y-%m-%d')} – "
            f"{newest.astimezone(MOSCOW_TZ).strftime('%Y-%m-%d')}"
        )

        result = await _run_analysis_pipeline(
            posts, channel_id, title, subscribers, lite_mode,
            repost_count=repost_count, repost_percent=repost_percent,
            enable_llm=enable_llm,
        )

        mode_str = "lite" if lite_mode else "full"
        logger.info(f"Анализ канала {channel_id} завершён успешно ({mode_str})")

        # Сохраняем в кэш для последующих запросов
        _save_to_cache(channel_id.lower(), result, lite_mode=lite_mode)

        # Выходим из приватного канала после анализа
        if is_private and entity:
            try:
                await client(LeaveChannelRequest(entity))
                logger.info(f"Вышли из приватного канала: {title}")
            except Exception as e:
                logger.warning(f"Не удалось выйти из канала: {e}")

        return result

    except FloodWaitError:
        raise  # Пробрасываем для обработки в handlers

    except Exception as e:
        logger.error(f"Ошибка анализа канала {channel}: {e}")
        raise AnalysisError(f"Не удалось проанализировать канал: {e}") from e
