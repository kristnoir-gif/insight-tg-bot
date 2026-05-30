"""
Adapter-функции: AnalysisResult → dict с плейсхолдерами для каждой HTML-карточки.

Каждая функция `build_<n>_<name>(result) → dict` соответствует одному HTML-шаблону
в `templates/`. Адаптеры не делают вычислений — только формат/отбор полей,
вся аналитика собрана в analyzer.build_v2_card_data().
"""
from __future__ import annotations

from typing import Mapping

from analyzer import AnalysisResult


BOT_USERNAME = "insight_tg_bot"
RECAP_LABEL = "TELEGRAM RECAP"

# Эмодзи → короткое русское слово. Используется в 13_emotions чтобы
# не зависеть от наличия цветного эмодзи-шрифта на проде.
EMOJI_TO_RU: dict[str, str] = {
    "👍": "лайк",       "❤️": "сердце",     "🔥": "огонь",       "🎉": "праздник",
    "😂": "смех",       "🤣": "ржака",      "😭": "слёзы",       "😢": "слеза",
    "😍": "восторг",    "🥰": "обожание",   "😘": "поцелуй",     "🙏": "мольба",
    "😡": "гнев",       "🤬": "злость",     "💔": "разбитое",    "🤔": "задумчивость",
    "😱": "ужас",       "🥺": "грусть",     "😎": "крутость",    "🤝": "договор",
    "👏": "аплодисменты","💯": "сто",        "✨": "сияние",      "🌈": "радуга",
    "💀": "череп",      "👀": "глаза",      "🤡": "клоун",       "🙄": "закат глаз",
    "😤": "пыхтение",   "🥲": "со слезой",  "😌": "облегчение",  "😊": "улыбка",
    "🌹": "роза",       "🤍": "белое сердце","🕊️": "голубь",     "💕": "две сердечки",
}


def _emoji_to_text(emoji: str) -> str:
    """Заменяет эмодзи на русское слово; если не нашли — возвращаем сам символ."""
    return EMOJI_TO_RU.get(emoji, emoji)

_WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def _format_k(n: int) -> str:
    """247000 → '247К', 18500 → '18,5К', 980 → '980'.

    Округление до десятых для значений до 100 тыс., целые для больших.
    """
    if n >= 1_000_000:
        m = n / 1_000_000
        return (f"{int(m)}М" if m == int(m) else f"{m:.1f}М").replace(".", ",")
    if n >= 100_000:
        return f"{round(n / 1000)}К"
    if n >= 1_000:
        k = n / 1000
        return (f"{int(k)}К" if k == int(k) else f"{k:.1f}К").replace(".", ",")
    return str(n)


def _format_int(n: int) -> str:
    """1800000 → '1.8 млн', 300815 → '300 815'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} млн".replace(".0 ", " ")
    if n >= 10_000:
        return f"{n:,}".replace(",", " ")
    return str(n)


def build_01_cover(r: AnalysisResult) -> dict:
    v = r.v2
    years = v.start_date[:4] + "–" + v.end_date[:4] if v.start_date and v.end_date else ""
    return {
        "recap_label": RECAP_LABEL,
        "channel_title": r.title or "канал",
        "years": years,
        "hero_number": _format_k(v.total_posts),
        "hero_caption": "постов за все время",
        "subtitle": f"по {v.posts_per_day_avg} в день · каждый день" if v.posts_per_day_avg else "",
        "bot_username": BOT_USERNAME,
    }


def build_02_main_themes(r: AnalysisResult) -> dict:
    """Карточка тем — берём топики из LLM (r.topics)."""
    return {
        "channel_title": r.title,
        "topics": r.topics[:10],   # шаблон сам отрендерит pills
        "bot_username": BOT_USERNAME,
    }


def build_03_chanal_in_numbers(r: AnalysisResult) -> dict:
    """6 фактов о канале в pills."""
    v = r.v2
    facts = []
    if v.total_chars:
        facts.append(f"{_format_int(v.total_chars)} символов написано")
    if v.max_consecutive_days:
        facts.append(f"рекорд {v.max_consecutive_days} дней подряд")
    if v.total_words:
        facts.append(f"{_format_int(v.total_words)} слов")
    if v.total_photos:
        facts.append(f"{_format_int(v.total_photos)} фото")
    if v.total_reactions:
        facts.append(f"{_format_int(v.total_reactions)} реакций")
    if v.years_covered:
        facts.append(f"{v.years_covered} лет")
    return {
        "channel_title": r.title,
        "facts": facts,
        "bot_username": BOT_USERNAME,
    }


def build_04_sum_of_reactions(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "hero_number": _format_k(v.total_reactions),
        "hero_caption": "реакций за все время",
        "subtitle": f"≈ {v.avg_reactions_per_post} на пост" if v.avg_reactions_per_post else "",
        "bot_username": BOT_USERNAME,
    }


def build_05_archetype_vocab(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "unique_count": _format_int(r.stats.unique_count),
        "unique_caption": "уникальных слов",
        "norm_label": "норма 5–8 тысяч",
        "archetype_label": "уровень",
        "archetype_name": v.vocab_archetype,
        "bot_username": BOT_USERNAME,
    }


def build_06_chronotype(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "archetype_label": "архетип",
        "archetype_name": v.chronotype_archetype.upper(),
        "peak_info": f"пик активности {v.peak_hour:02d}:00",
        "bot_username": BOT_USERNAME,
    }


def build_07_word_cloud(r: AnalysisResult) -> dict:
    return {
        "channel_title": r.title,
        "cloud_image_path": r.cloud_path or "",
        "bot_username": BOT_USERNAME,
    }


def build_08_post_by_days_weeks(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "favorite_day_caption": f"Любимый день — {_WEEKDAYS_RU[v.favorite_weekday]}",
        # данные для столбцов берутся отдельно (weekday_counts через r.* — пока TODO)
        "bot_username": BOT_USERNAME,
    }


def build_09_bad_word_cloud(r: AnalysisResult) -> dict:
    return {
        "channel_title": r.title,
        "cloud_image_path": r.mats_path or "",
        "bot_username": BOT_USERNAME,
    }


def build_10_archetype_bad(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "archetype_label": "уровень токсичности",
        "archetype_name": v.toxicity_archetype.upper(),
        "stat_line": f"мат {v.mat_percent_of_text}% от всего текста\n{v.posts_with_mat_percent}% постов с матом",
        "bot_username": BOT_USERNAME,
    }


def build_11_geography(r: AnalysisResult) -> dict:
    v = r.v2
    cities_lines = [f"{name.lower()} – {cnt}" for name, cnt in v.top_cities]
    return {
        "channel_title": r.title,
        "heart_caption": f"сердце канала — {v.heart_city}" if v.heart_city else "",
        "total_caption": f"{v.total_city_mentions} упоминаний городов" if v.total_city_mentions else "",
        "cities_block": "\n".join(cities_lines),
        "bot_username": BOT_USERNAME,
    }


def build_12_top_phrases(r: AnalysisResult) -> dict:
    # top_phrases в analyzer.py имеет вид [((w1,w2,w3), count), ...]
    # Если не сохранены в V2CardData (пока), пробуем достать из top_emojis-pattern
    phrases: list[str] = []
    # TODO: добавить top_phrases в V2CardData (сейчас пусто после JSON-кэша)
    return {
        "channel_title": r.title,
        "phrases_block": "\n".join(phrases),
        "bot_username": BOT_USERNAME,
    }


def build_13_emotions(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "palette_title": v.emotion_palette_name,
        # Hero — сам символ эмодзи (😭, 👍, ...)
        "hero_emoji": v.top_emoji,
        "hero_count": f"{_format_int(v.top_emoji_count)} раз" if v.top_emoji_count else "",
        # Strip — символы 4 эмодзи подряд "🙏😭😡😍"
        "emojis_strip": "".join(v.top_emojis_strip),
        "bot_username": BOT_USERNAME,
    }


def build_14_chanal_in_one_phrase(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "title_label": "AI прочитал всё\nи подумал",
        "phrase": v.one_phrase_llm or (r.content_analysis_text or "")[:200],
        "source_caption": f"сгенерировано на основе {r.v2.total_posts} постов" if r.v2.total_posts else "",
        "bot_username": BOT_USERNAME,
    }


def build_15_hit_post(r: AnalysisResult) -> dict:
    return {
        "channel_title": r.title,
        "subtitle": "три поста, которые взорвали",
        "posts": r.v2.top_posts,  # TODO: список dict {date, text, reactions}
        "bot_username": BOT_USERNAME,
    }


def build_16_reading_statistics(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "hero_hours": f"{v.reading_time_hours} ч" if v.reading_time_hours else "",
        "coffee_caption": f"и {v.coffee_cups} чашки кофе чтобы прочитать весь канал" if v.coffee_cups else "",
        "metaphor": f"это как {v.sitcom_seasons} сезона сериала" if v.sitcom_seasons else "",
        "bot_username": BOT_USERNAME,
    }


def build_17_most_used_word(r: AnalysisResult) -> dict:
    v = r.v2
    return {
        "channel_title": r.title,
        "title_label": "Самое частое слово",
        "hero_word": v.top_word.upper(),
        "caption": f"упомянуто {_format_int(v.top_word_count)} раз" if v.top_word_count else "",
        "bot_username": BOT_USERNAME,
    }


def build_18_top_person(r: AnalysisResult) -> dict:
    v = r.v2
    lines = [f"{name.lower()} – {cnt}" for name, cnt in v.top_names_with_counts]
    return {
        "channel_title": r.title,
        "people_block": "\n".join(lines),
        "bot_username": BOT_USERNAME,
    }


# Реестр: имя шаблона → builder. Используется renderer для batch-рендера.
CARDS: Mapping[str, callable] = {
    "01_cover":              build_01_cover,
    "02_main_themes":        build_02_main_themes,
    "03_chanal_in_numbers":  build_03_chanal_in_numbers,
    "04_sum_of_reactions":   build_04_sum_of_reactions,
    "05_archetype_vocab":    build_05_archetype_vocab,
    "06_chronotype":         build_06_chronotype,
    "07_word_cloud":         build_07_word_cloud,
    "08_post_by_days_weeks": build_08_post_by_days_weeks,
    "09_bad_word_cloud":     build_09_bad_word_cloud,
    "10_archetype_bad":      build_10_archetype_bad,
    "11_geography":          build_11_geography,
    "12_top_phrases":        build_12_top_phrases,
    "13_emotions":           build_13_emotions,
    "14_one_phrase":         build_14_chanal_in_one_phrase,
    "15_hit_post":           build_15_hit_post,
    "16_reading_statistics": build_16_reading_statistics,
    "17_most_used_word":     build_17_most_used_word,
    "18_top_person":         build_18_top_person,
}
