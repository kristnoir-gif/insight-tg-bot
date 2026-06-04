"""Единый рендер v2-галереи карточек (канонический пайплайн).

`render_full_v2_gallery(result, channel_key)` — то, что зовёт бот
(visualization/v2_cards/__init__.py перенаправлен сюда) И dev-скрипт render_channel.py.
Рендерит карточки из cards_html/cards.py (HTML/CSS → Playwright PNG) по данным
result.v2 (V2CardData) + result.title/topics/stats.unique_count.

Порядок: контент 1-15, англицизмы пока вне обзора, архетипы (Юнг/хроно/vocab/tox) В КОНЦЕ.
Карточка пропускается, если нет данных (нет городов/имён/реакций и т.п.).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# cards.py лежит рядом — добавляем папку в путь для `import cards`
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import cards as C  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

TOX_BG = {"Ангел": "tox_angel.png", "Лёгкий": "tox_light.png", "Острый": "tox_sharp.png",
          "Ядовитый": "tox_poison.png", "Игрок": "tox_gamer.png", "Ядерный": "tox_nuclear.png",
          "Правый": "tox_right.png"}
EMO_MAP = {"😭": "слёзы", "🙏": "мольба", "🥺": "умиление", "❤": "любовь", "❤️": "любовь",
           "😍": "восторг", "😡": "гнев", "👍": "одобрение", "🔥": "огонь", "😂": "смех",
           "🤣": "смех", "😢": "грусть", "🥰": "нежность", "😅": "неловкость", "💔": "разбитость",
           "🤩": "восторг", "✨": "магия", "😎": "крутость", "🎉": "праздник", "💀": "жесть",
           "🤍": "любовь", "🖤": "любовь", "💜": "любовь", "🥲": "слёзы радости", "😘": "поцелуй",
           "😇": "ангел", "🥹": "умиление", "🤯": "взрыв мозга", "👀": "глаза", "🤡": "клоун",
           "😈": "чертёнок", "🫶": "сердце", "💅": "маникюр", "😱": "шок", "🥳": "праздник",
           "🤔": "раздумья", "😴": "сон", "🙈": "стыдоба", "🤝": "респект", "👏": "браво",
           "😤": "пыхтение", "🤬": "ярость", "😳": "смущение", "🌚": "луна", "🐳": "кит"}


def emo_label(e: str) -> str:
    """Подпись эмодзи: словарь → фолбэк на русское имя из библиотеки emoji.
    Пустой подписи не бывает."""
    base = (e or "").replace("️", "")
    lab = EMO_MAP.get(e) or EMO_MAP.get(base)
    if lab:
        return lab
    try:
        import emoji as emoji_lib
        name = emoji_lib.demojize(e, language="ru").strip(":").replace("_", " ")
        name = name.replace("жест «", "").replace("»", "").strip()
        return name if name and not name.startswith(":") else "эмоция"
    except Exception:
        return "эмоция"


def _fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


def _clean_title(t: str) -> str:
    return re.sub(r"[\U0001F000-\U0001FAFF‍☀-➿️🏴☠]", "", str(t or "")).strip()


def _vocab_bg(uc: int) -> str:
    if uc < 6000:
        return "less_6000_ARCHETYPE_by_vocabulary.png"
    tiers = [(9000, "ARCHETYPE_by_vocabulary_Intellectual.png"),
             (13000, "Master of Words_ARCHETYPE_by_vocabulary.png"),
             (16000, "Linguist-ARCHETYPE_by_vocabulary.png"),
             (19000, "Poet_ARCHETYPE_by_vocabulary.png"),
             (24000, "Writer_ARCHETYPE_by_vocabulary.png"),
             (30000, "The_greate_writer-ARCHETYPE_by_vocabulary.png")]
    for thr, bg in tiers:
        if uc < thr:
            return bg
    return "ARCHETYPE_by_vocabulary.png"


def render_full_v2_gallery(result, channel_key: str, *,
                           out_dir: "Path | None" = None,
                           jungian: str | None = None) -> list[Path]:
    """Рендерит все доступные v2-карточки, возвращает отсортированный список Path."""
    v = result.v2
    out_dir = (Path(out_dir) if out_dir else Path("/tmp/v2_gallery")) / channel_key
    out_dir.mkdir(parents=True, exist_ok=True)
    name_up = _clean_title(result.title).upper()
    name_tc = _clean_title(result.title).title()
    unique_count = getattr(getattr(result, "stats", None), "unique_count", 0) or 0
    rendered: list[tuple[int, Path]] = []

    def add(n: int, key: str, html: str):
        p = out_dir / f"{n:02d}_{key}.png"
        C.render_html(html, p)
        rendered.append((n, p))

    # 01 cover
    sy, ey = (v.start_date or "")[:4], (v.end_date or "")[:4]
    years = sy if sy == ey else f"{sy}–{ey}"
    hero = (_fmt(v.total_posts) if v.total_posts < 1000
            else f"{v.total_posts/1000:.1f}".replace(".", ",") + "К")
    # темп — целое со знаком ~ («по ~2 в день»)
    rate = max(round(v.posts_per_day_avg or 0), 1)
    avatar_png = ROOT / "cache" / channel_key / "avatar.png"
    add(1, "cover", C.cover_html(name_up, years, hero,
        f"по ~{rate} в день · каждый день",
        avatar_uri=avatar_png.as_uri() if avatar_png.exists() else None))

    # 02 main_themes
    if result.topics:
        add(2, "themes", C.main_themes_html(name_tc, result.topics or []))

    # 03 chanal_in_numbers
    pills = []
    if v.total_chars:          pills.append(f"{_fmt(v.total_chars)} символов написано")
    if v.max_consecutive_days: pills.append(
        f"рекорд {v.max_consecutive_days} "
        f"{C._plural(v.max_consecutive_days, 'день', 'дня', 'дней')} подряд")
    if v.total_reactions:      pills.append(f"{_fmt(v.total_reactions)} реакций")
    if v.years_covered:        pills.append(f"{v.years_covered} {C._plural(v.years_covered, 'год', 'года', 'лет')}")
    if v.total_words:          pills.append(f"{_fmt(v.total_words)} слов")
    if v.total_photos:         pills.append(
        f"{_fmt(v.total_photos)} {C._plural(v.total_photos, 'пост', 'поста', 'постов')} с фото")
    add(3, "numbers", C.chanal_in_numbers_html(name_up, pills))

    # 04 geography
    if v.top_cities:
        add(4, "geography", C.geography_html([tuple(x) for x in v.top_cities],
            v.total_city_mentions, v.heart_city))

    # 05 most_used
    if v.top_word:
        add(5, "most_used", C.most_used_html(v.top_word, v.top_word_count))

    # 06 top_person
    if v.top_names_with_counts:
        add(6, "top_person", C.top_person_html([tuple(x) for x in v.top_names_with_counts]))

    # 07 reading
    if v.reading_time_hours:
        h = float(v.reading_time_hours)
        mins = max(int(round(h * 60)), 1)
        if h < 1:                       # короткие каналы: «18 минут», не «0,3 часа»
            h_str = str(mins)
            unit_word = C._plural(mins, "минута", "минуты", "минут")
        else:                           # часы с шагом 0,5: 3.4 → «3,5», 3.0 → «3»
            h2 = round(h * 2) / 2
            if h2 == int(h2):
                h_str = str(int(h2))
                unit_word = C._plural(int(h2), "час", "часа", "часов")
            else:
                h_str = f"{h2:.1f}".replace(".", ",")
                unit_word = "часа"      # «3,5 часа»
        pages = max(int(getattr(v, "book_pages", 0) or 0), 1)
        seasons = float(v.sitcom_seasons or 0)
        if seasons == 0.5:
            compare = "полсезона сериала"
        elif seasons == 1.5:
            compare = "полтора сезона сериала"
        elif seasons >= 0.1:
            s_str = (str(int(seasons)) if seasons == int(seasons)
                     else str(seasons).replace(".", ","))
            compare = f"{s_str} {C._seasons_word(s_str)} сериала"
        else:                            # совсем короткие: считаем сериями (~20 мин)
            ep = max(int(round(mins / 20)), 1)
            compare = f"{ep} {C._plural(ep, 'серия', 'серии', 'серий')} сериала"
        add(7, "reading", C.reading_html(h_str, unit_word, pages, compare))

    # 08 emotions
    if v.emotion_palette_name or v.top_emoji:
        strip = v.top_emojis_strip or []
        labels = [emo_label(e) for e in strip]
        add(8, "emotions", C.emotions_html(v.emotion_palette_name, v.top_emoji,
            _fmt(v.top_emoji_count), strip, labels))

    # 09 word cloud
    if v.top_words_for_cloud:
        cw = out_dir / "_cloud.png"
        C.gen_wordcloud_png({w: int(c) for w, c in v.top_words_for_cloud}, cw)
        add(9, "word_cloud", C.word_cloud_html(name_tc, cw, "word_cloude.png"))

    # 10 bad word cloud
    if v.top_mat_words_for_cloud:
        mw = out_dir / "_mat.png"
        C.gen_wordcloud_png({w: int(c) for w, c in v.top_mat_words_for_cloud}, mw)
        add(10, "bad_word_cloud", C.word_cloud_html(name_tc, mw, "bad_word_cloude.png"))

    # 11 суммарные реакции
    if v.total_reactions:
        tr = v.total_reactions
        # точное число хайповее (как Spotify Wrapped); К/М — только когда не влезает.
        # узкий пробел (U+202F) между разрядами — экономит ширину под кегль
        total = (_fmt(tr).replace(" ", " ") if tr < 100_000
                 else f"{tr/1000:.0f}К" if tr < 1_000_000
                 else f"{tr/1_000_000:.1f}".replace(".", ",") + "М")
        # среднее по ВСЕМ постам (как на обложке), не только текстовым
        per = max(int(round(tr / max(v.total_posts or 1, 1))), 1)
        add(11, "sum_reactions", C.sum_reactions_html(total, f"≈ {per} на пост"))

    # 12 посты по дням недели
    pbw = getattr(v, "posts_by_weekday", None)
    if pbw:
        wd = {int(k): int(val) for k, val in dict(pbw).items()}
        names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        add(12, "post_by_days", C.post_by_days_html(wd, names[int(v.favorite_weekday or 0)]))

    # 13 любимые фразы
    phrases = getattr(v, "top_phrases", None)
    if phrases:
        add(13, "top_phrases", C.top_phrases_html(phrases))

    # 14 хиты канала
    if v.top_posts:
        posts = [(p.get("reactions"), p.get("text"), p.get("date")) for p in v.top_posts[:3]]
        add(14, "hit_post", C.hit_post_html(posts))

    # 15 канал в одной фразе (one_phrase) — рендерится только если LLM-фраза есть
    # (при отказе от AI-анализа поле пустое → карточка пропускается)
    if v.one_phrase_llm:
        add(15, "one_phrase", C.chanal_in_one_phrase_html(v.one_phrase_llm))

    # --- архетипы В КОНЦЕ ---
    # 16 архетип по Юнгу (только агрегаты в LLM, без сырых постов → без согласия)
    arch = jungian or v.jungian_archetype
    if arch:
        add(16, "archetype", C.archetype_html(arch))

    # 17 chronotype
    if v.chronotype_archetype:
        add(17, "chronotype", C.chronotype_html(v.chronotype_archetype, v.peak_hour,
            v.peak_bucket_share))

    # 18 vocab (по unique_count)
    if unique_count:
        add(18, "vocab", C.vocab_html(_vocab_bg(unique_count), _fmt(unique_count)))

    # 19 toxicity
    if v.toxicity_archetype:
        tox_file = TOX_BG.get(v.toxicity_archetype, "tox_sharp.png")
        add(19, "toxicity", C.toxicity_html(tox_file, v.mat_percent_of_text,
            int(v.posts_with_mat_percent)))

    rendered.sort()
    return [p for _, p in rendered]
