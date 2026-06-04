"""
Модуль AI-анализа контента Telegram-канала через LLM (Alibaba DashScope / Qwen).
"""
import re
import logging

import aiohttp

from config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_MAX_TOKENS, LLM_TIMEOUT

logger = logging.getLogger(__name__)

# Допустимые HTML-теги для Telegram
_ALLOWED_TAGS = {"b", "i", "u", "code"}
_TAG_RE = re.compile(r"<(/?)(\w+)(?:\s[^>]*)?>")

# Максимум символов контекста для LLM (~32K символов, qwen-max поддерживает 32K+ окно)
_MAX_CONTEXT_CHARS = 32_000
_MIN_POSTS = 10


def _sanitize_html(text: str) -> str:
    """Оставляет только допустимые HTML-теги для Telegram."""
    def _replace(m: re.Match) -> str:
        slash, tag = m.group(1), m.group(2).lower()
        if tag in _ALLOWED_TAGS:
            return f"<{slash}{tag}>"
        return ""
    return _TAG_RE.sub(_replace, text)


_JUNGIAN_DESCRIPTIONS = {
    "Мудрец":         "аналитический контент, сложные смыслы, длинные посты, экспертный тон",
    "Искатель":       "темы путешествий, поиск нового, разнообразие интересов, частые вопросы",
    "Простодушный":   "позитивный тон, простой язык, искренние истории, отсутствие агрессии",
    "Бунтарь":        "провокации, высокий мат, КАПС, острая критика, нонконформизм",
    "Борец":          "темы целей, побед, преодоления, мотивация, спорт/достижения",
    "Творец":         "уникальный визуальный стиль, креативная лексика, искусство, эстетика",
    "Славный малый":  "повседневные жизненные истории, бытовая лексика, разговоры «для своих»",
    "Любовник":       "эмоции, чувства, отношения, романтика, эстетические эмодзи",
    "Шут":            "ирония, мемы, сарказм, фановое общение, высокая частота эмодзи",
    "Опекун":         "советы, гайды, поддержка аудитории, помощь, забота, лайфхаки",
    "Правитель":      "экспертный контент, лидерская позиция, масштабные темы, статус",
    "Маг":            "инсайты, трансформации, нестандартный взгляд, переосмысление",
}


async def generate_one_phrase(
    channel_title: str,
    posts_sample: list[str],
    *,
    max_words: int = 25,
) -> str | None:
    """Генерирует одну броскую фразу-эссенцию канала (для карточки 14).

    Пример: «Девушка-разработчица из Питера, переехавшая в Тбилиси,
    философствует в 2 ночи о любви, котах, нейросетях и разводе».
    """
    if not LLM_API_KEY or not posts_sample:
        return None
    sample = "\n".join(p[:300] for p in posts_sample[:50] if p)[:6000]
    system = (
        "Ты — психолог-литератор. На основе нескольких постов канала "
        f"сформулируй ОДНО ёмкое описание канала из не более чем {max_words} слов. "
        "Без воды, без вступления, без объяснений. Сразу фраза. "
        "Передай характер: возраст, локация, темы, тон, стиль. "
        "СТРОГО: одно грамматически согласованное предложение с подлежащим "
        "и сказуемым, как живая речь — НЕ перечисление эпитетов через запятую. "
        "Хорошо: «Молодая художница из Тбилиси ведёт дневник о психике, любви "
        "и творчестве — эксцентрично и искренне». "
        "Плохо: «Молодая, тбилисская, квир-арт-хиппи, размышления о психике»."
    )
    user = f"Канал: «{channel_title}»\n\nОбразцы постов:\n{sample}\n\nОдна фраза:"
    url = f"{LLM_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 120, "temperature": 0.7,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=LLM_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"LLM one_phrase API {resp.status}: {body[:200]}")
                    return None
                data = await resp.json()
        phrase = data["choices"][0]["message"]["content"].strip().strip('"').strip("«»")
        # Убираем перенос строк и многоточия в начале/конце
        phrase = " ".join(phrase.split())
        logger.info(f"LLM one_phrase для '{channel_title}': {phrase[:80]}…")
        return phrase
    except TimeoutError:
        logger.warning(f"LLM one_phrase timeout для '{channel_title}'")
        return None
    except (aiohttp.ClientError, KeyError, IndexError) as e:
        logger.warning(f"LLM one_phrase error: {type(e).__name__}: {e}")
        return None


async def classify_jungian_archetype(
    channel_title: str,
    signals: dict,
) -> str | None:
    """Классифицирует канал в один из 12 юнгианских архетипов.

    Args:
        channel_title: название канала (для контекста)
        signals: компактная сводка метрик из analyzer:
            top_words, top_emojis, top_phrases, pos_percent, agg_percent,
            meta_percent, everyday_percent, mat_percent, avg_len,
            scream_index, repost_percent, night_post_percent,
            topics, chronotype, vocab_level

    Returns:
        Имя архетипа (e.g. "Мудрец") или None при ошибке.
    """
    if not LLM_API_KEY:
        return None

    arch_lines = "\n".join(
        f"- {name}: {desc}" for name, desc in _JUNGIAN_DESCRIPTIONS.items()
    )
    signals_lines = "\n".join(f"{k}: {v}" for k, v in signals.items() if v)

    system = (
        "Ты — психолог-аналитик, классифицирующий Telegram-каналы по 12 архетипам Юнга. "
        "На основе аналитических сигналов канала выбери ОДИН наиболее подходящий архетип. "
        "Отвечай СТРОГО одним словом — именем архетипа из списка, без объяснений и без точки."
    )
    user = (
        f"Канал: «{channel_title}»\n\n"
        f"СИГНАЛЫ:\n{signals_lines}\n\n"
        f"АРХЕТИПЫ (выбери один):\n{arch_lines}\n\n"
        "Ответ — только имя архетипа:"
    )

    url = f"{LLM_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 20,
        "temperature": 0.3,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=LLM_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"LLM jungian API error {resp.status}: {body[:300]}")
                    return None
                data = await resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        # Принудительно матчим в один из известных архетипов (нейронка может прислать "Архетип: Мудрец")
        for name in _JUNGIAN_DESCRIPTIONS:
            if name.lower() in raw.lower():
                logger.info(f"LLM jungian for '{channel_title}': {name}  (raw: {raw!r})")
                return name
        logger.warning(f"LLM jungian: не распознан архетип в ответе: {raw!r}")
        return None
    except TimeoutError:
        logger.warning(f"LLM jungian timeout for '{channel_title}'")
        return None
    except (aiohttp.ClientError, KeyError, IndexError) as e:
        logger.warning(f"LLM jungian error for '{channel_title}': {type(e).__name__}: {e}")
        return None


def _build_content_prompt(
    channel_title: str,
    subscribers: int,
    stats_text: str,
    posts_texts: list[str],
) -> list[dict]:
    """Формирует messages для анализа контента канала."""
    system = (
        "Ты — аналитик Telegram-каналов с экспертизой в контент-стратегии и психологии медиа. "
        "Твоя задача — составить комплексный анализ канала на основе постов И готовой статистики.\n\n"
        "Формат: HTML для Telegram (теги <b>, <i>, <u>). Максимум 3800 символов. "
        "Не используй markdown. Не используй ### или **.\n\n"
        "ВХОДНЫЕ ДАННЫЕ:\n"
        "Ты получишь: (1) статистику канала, рассчитанную программно, (2) тексты постов.\n"
        "Статистику не пересчитывай — интерпретируй её.\n\n"
        "КРИТИЧЕСКИ ВАЖНО:\n"
        "• Каждое утверждение подкрепляй цитатой из поста: <i>«цитата»</i> [номер поста]\n"
        "• Не перечисляй числа из статистики — объясняй что они ЗНАЧАТ\n"
        "• Не лей воду, не пиши очевидное\n\n"
        "СТРУКТУРА ОТВЕТА:\n\n"
        "<b>📊 Портрет канала</b>\n"
        "Определи тип канала — это может быть личный дневник, тематический блог, "
        "новостной канал, агрегатор, арт-канал, канал мемов и т.д. "
        "Не предполагай автоматически что это личный блог — определи по контенту.\n"
        "— Для кого и зачем ведётся канал (самовыражение, монетизация, комьюнити, архив?)\n"
        "— Эволюция: как менялся канал со временем (если видно из постов)\n\n"
        "<b>📈 Что говорят цифры</b>\n"
        "Интерпретируй статистику — не перечисляй, а объясни:\n"
        "— Паттерны активности (время суток, дни недели — что это говорит?)\n"
        "— Соотношение контента (оригинал vs репосты, текст vs медиа)\n"
        "— Словарный запас и длина постов — что это значит для формата канала?\n\n"
        "<b>🎭 Тематика и тон</b>\n"
        "На основе частотных слов и текстов постов:\n"
        "— Ключевые темы канала\n"
        "— Эмоциональный тон (рефлексия, юмор, гнев, ирония, нежность?)\n"
        "— Что выдают ТОП-слова о мышлении автора?\n"
        "Подкрепляй цитатами: <i>«цитата»</i> [номер поста]\n\n"
        "<b>💬 Аудитория и вовлечённость</b>\n"
        "На основе данных о подписчиках и контенте:\n"
        "— Для кого этот канал (целевая аудитория)?\n"
        "— Какой тип контента скорее всего резонирует?\n"
        "— Отношение автора к аудитории\n\n"
        "<b>⚡ Главный инсайт</b>\n"
        "Одно неочевидное наблюдение о канале, которое автор сам может не осознавать.\n\n"
        "Пиши живо, конкретно, с цитатами. Каждый тезис — доказательство. "
        "Не делай предположений о личной жизни автора — анализируй контент."
    )

    posts_block = []
    total_chars = 0
    for i, text in enumerate(posts_texts, 1):
        entry = f"[{i}] {text}"
        if total_chars + len(entry) > _MAX_CONTEXT_CHARS - len(stats_text):
            break
        posts_block.append(entry)
        total_chars += len(entry)

    user_msg = (
        f"Канал: {channel_title}\n"
        f"Подписчики: {subscribers}\n\n"
        f"СТАТИСТИКА:\n{stats_text}\n\n"
        f"Посты:\n\n" + "\n\n".join(posts_block)
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]


async def generate_content_analysis(
    channel_title: str,
    subscribers: int,
    stats_text: str,
    posts_texts: list[str],
) -> str | None:
    """
    Генерирует AI-анализ контента канала.

    Args:
        stats_text: готовая текстовая сводка метрик (часы, слова, реакции и т.д.)

    Returns:
        HTML-текст анализа или None при ошибке / недостатке данных.
    """
    if not LLM_API_KEY:
        logger.debug("LLM: API ключ не задан, пропускаем анализ контента")
        return None

    if not posts_texts or len(posts_texts) < _MIN_POSTS:
        logger.debug(f"LLM: недостаточно постов для анализа контента ({len(posts_texts) if posts_texts else 0})")
        return None

    messages = _build_content_prompt(channel_title, subscribers, stats_text, posts_texts)

    url = f"{LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.7,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=LLM_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"LLM content API error {resp.status}: {body[:300]}")
                    return None

                data = await resp.json()

        content = data["choices"][0]["message"]["content"]
        result = _sanitize_html(content.strip())

        logger.info(f"LLM: анализ контента для '{channel_title}' готов ({len(result)} символов)")
        return result

    except TimeoutError:
        logger.warning(f"LLM: таймаут ({LLM_TIMEOUT}с) для анализа контента '{channel_title}'")
        return None
    except (aiohttp.ClientError, KeyError, IndexError) as e:
        logger.warning(f"LLM: ошибка анализа контента '{channel_title}': {type(e).__name__}: {e}")
        return None
    except Exception as e:
        logger.warning(f"LLM: неожиданная ошибка анализа контента: {type(e).__name__}: {e}")
        return None


def _build_topics_prompt(
    channel_title: str,
    top_words: list[str],
    sample_posts: list[str],
) -> list[dict]:
    """Формирует messages для определения топ-3 тем канала."""
    system = (
        "Ты — аналитик Telegram-каналов. "
        "На основе частотных слов и текстов постов определи 3 главные темы канала.\n\n"
        "ФОРМАТ ОТВЕТА — строго 3 строки, каждая тема на отдельной строке:\n"
        "Тема 1\n"
        "Тема 2\n"
        "Тема 3\n\n"
        "ПРАВИЛА:\n"
        "• Каждая тема — 1-3 слова (существительное или словосочетание)\n"
        "• Темы должны быть конкретными (не «разное» или «жизнь»)\n"
        "• Не нумеруй, не добавляй эмодзи, не пиши ничего кроме 3 тем\n"
        "• Отвечай на русском языке"
    )

    posts_block = []
    total_chars = 0
    for i, text in enumerate(sample_posts[:50], 1):
        entry = f"[{i}] {text[:500]}"
        if total_chars + len(entry) > 8000:
            break
        posts_block.append(entry)
        total_chars += len(entry)

    user_msg = (
        f"Канал: {channel_title}\n"
        f"ТОП-50 слов: {', '.join(top_words[:50])}\n\n"
        f"Примеры постов:\n\n" + "\n\n".join(posts_block)
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]


async def generate_topics(
    channel_title: str,
    top_words: list[str],
    sample_posts: list[str],
) -> list[str] | None:
    """
    Определяет топ-3 темы канала через LLM.

    Returns:
        Список из 3 тем или None при ошибке.
    """
    if not LLM_API_KEY:
        logger.debug("LLM: API ключ не задан, пропускаем определение тем")
        return None

    if not sample_posts or len(sample_posts) < _MIN_POSTS:
        logger.debug("LLM: недостаточно постов для определения тем")
        return None

    messages = _build_topics_prompt(channel_title, top_words, sample_posts)

    url = f"{LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": 200,
        "temperature": 0.5,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=LLM_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"LLM topics API error {resp.status}: {body[:300]}")
                    return None

                data = await resp.json()

        content = data["choices"][0]["message"]["content"].strip()
        topics = [line.strip() for line in content.split("\n") if line.strip()]
        topics = topics[:3]

        if len(topics) < 3:
            logger.warning(f"LLM: получено {len(topics)} тем вместо 3")
            return None

        logger.info(f"LLM: темы для '{channel_title}': {topics}")
        return topics

    except TimeoutError:
        logger.warning(f"LLM: таймаут определения тем для '{channel_title}'")
        return None
    except (aiohttp.ClientError, KeyError, IndexError) as e:
        logger.warning(f"LLM: ошибка определения тем '{channel_title}': {type(e).__name__}: {e}")
        return None
    except Exception as e:
        logger.warning(f"LLM: неожиданная ошибка определения тем: {type(e).__name__}: {e}")
        return None


# Обратная совместимость: personality -> content analysis
async def generate_personality_analysis(
    channel_title: str,
    subscribers: int,
    posts_texts: list[str],
) -> str | None:
    """Deprecated: используй generate_content_analysis. Оставлено для совместимости."""
    return None
