"""
Координаты и стили динамических текстовых полей в каждой карточке.

Координаты XYWH относительно frame'a 1080×1920 (взяты из cards_structure.json
по слоям Figma). Каждое поле описывает где и каким шрифтом нарисовать значение
из словаря-данных (см. card_data.py builders).

Используется в hybrid.py для рисования текста PIL'ом поверх pre-baked PNG.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FONTS = Path(__file__).parent.parent.parent / "assets" / "fonts"
INTER_VAR = str(FONTS / "Inter-Variable.ttf")
INTER_ITALIC = str(FONTS / "Inter-Italic-Variable.ttf")
NOOKS_BOLD = str(FONTS / "TT Nooks Script Educational Bold.otf")
NOOKS_REGULAR = str(FONTS / "TT Nooks Script Educational Regular.otf")
# Не-скриптовый Nooks для заголовков карточек (закруглённый sans-serif как в Figma).
NOOKS_EDU_BLACK = str(FONTS / "TT Nooks Educational Black.otf")

# Цветной эмодзи-шрифт — берём первый существующий в системе.
# На прод-Linux надо положить NotoColorEmoji.ttf в assets/fonts/.
import os as _os
for _cand in [
    "/System/Library/Fonts/Apple Color Emoji.ttc",          # macOS
    str(FONTS / "NotoColorEmoji.ttf"),                       # project-local
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",     # Debian/Ubuntu
    "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf", # Fedora
]:
    if _os.path.exists(_cand):
        EMOJI_FONT = _cand
        break
else:
    EMOJI_FONT = INTER_VAR  # fallback — будут "NO GLYPH" пустышки


@dataclass
class TextField:
    """Описание одного текстового поля карточки."""
    data_key: str       # ключ в dict из card_data.py
    x: int              # левый верх XYWH относительно картинки 1080×1920
    y: int
    w: int
    h: int
    font: str           # путь к .ttf/.otf
    size: int           # font-size в пт (≈ px для bitmap-рендера)
    weight: int = 400   # для variable-шрифтов
    align: str = "center"   # left | center | right
    color: str = "white"
    emoji: bool = False     # если True — рисуется цветным эмодзи-шрифтом


# 01 — обложка: 4 динамических поля
COVER_FIELDS: list[TextField] = [
    # Название канала (после "TELEGRAM RECAP" — на второй строке "h-bold")
    TextField("channel_title", x=75, y=300, w=950, h=120, font=INTER_VAR, size=90, weight=800),
    # Период "2017–2026"
    TextField("years", x=166, y=500, w=748, h=80, font=INTER_VAR, size=68, weight=400),
    # Hero-число "18,5К" — чуть выше и компактнее чтобы не залезть на пилл
    TextField("hero_number", x=55, y=680, w=970, h=400, font=NOOKS_BOLD, size=360, weight=700),
    # Подзаголовок "по 5.6 в день · каждый день"
    TextField("subtitle", x=3, y=1305, w=1077, h=60, font=INTER_VAR, size=42, weight=400, color="#cccccc"),
]


# 04 — суммарные реакции
SUM_REACTIONS_FIELDS: list[TextField] = [
    # hero "247К"
    TextField("hero_number", x=156, y=729, w=768, h=380, font=NOOKS_BOLD, size=360, weight=700),
    # "≈ 13.3 на пост"
    TextField("subtitle", x=2, y=1450, w=1077, h=66, font=INTER_VAR, size=62, weight=500),
]

# 17 — самое частое слово
MOST_USED_WORD_FIELDS: list[TextField] = [
    # hero — слово ЖИЗНЬ
    TextField("hero_word", x=105, y=820, w=870, h=283, font=NOOKS_BOLD, size=260, weight=700),
    # "упомянуто 487 раз"
    TextField("caption", x=219, y=1170, w=642, h=52, font=INTER_VAR, size=50, weight=800),
]

# 06 — хронотип
CHRONOTYPE_FIELDS: list[TextField] = [
    # ЛУНАТИК
    TextField("archetype_name", x=65, y=266, w=950, h=180, font=NOOKS_BOLD, size=170, weight=700),
    # пик активности 03:00
    TextField("peak_info", x=104, y=1414, w=873, h=66, font=INTER_VAR, size=62, weight=600),
]

# 05 — архетип по словарю
ARCHETYPE_VOCAB_FIELDS: list[TextField] = [
    # archetype_name "Интеллектуал"
    TextField("archetype_name", x=65, y=326, w=950, h=140, font=NOOKS_BOLD, size=130, weight=700),
    # unique_count "9 247" — выровнен по правому краю в Figma, ставим CENTER рядом с подписью
    TextField("unique_count", x=57, y=1445, w=262, h=66, font=NOOKS_BOLD, size=80, weight=700, align="right"),
    # " уникальных слов" — Inter справа от числа (с отступом)
    TextField("unique_caption", x=345, y=1441, w=636, h=66, font=INTER_VAR, size=72, weight=600, align="left"),
]


# 10 — токсичность
ARCHETYPE_BAD_FIELDS: list[TextField] = [
    # ЯДОВИТЫЙ (большой архетип)
    TextField("archetype_name", x=0, y=236, w=1080, h=180, font=NOOKS_BOLD, size=170, weight=700),
    # "мат N% от всего текста\nN% постов с матом"
    TextField("stat_line", x=1, y=1380, w=1079, h=158, font=INTER_VAR, size=58, weight=800),
]

# 16 — статистика чтения
READING_FIELDS: list[TextField] = [
    # "25 ч" — Hero (script)
    TextField("hero_hours", x=297, y=600, w=486, h=291, font=NOOKS_BOLD, size=270, weight=700),
    # "и N чашки кофе чтобы прочитать весь канал"
    TextField("coffee_caption", x=170, y=990, w=739, h=255, font=INTER_VAR, size=72, weight=500),
    # "это как 2.5 сезона сериала"
    TextField("metaphor", x=170, y=1300, w=739, h=62, font=INTER_VAR, size=44, weight=500, color="#cccccc"),
]

# 13 — эмоции (эмодзи отрисовываются как цветные глифы)
EMOTIONS_FIELDS: list[TextField] = [
    # "Драматическая" — название палитры
    TextField("palette_title", x=0, y=580, w=1080, h=90, font=INTER_VAR, size=70, weight=500),
    # Hero-эмодзи 👍 (Apple/Noto Color Emoji, фиксированный размер 160)
    TextField("hero_emoji", x=460, y=780, w=160, h=160, font=EMOJI_FONT, size=160, emoji=True),
    # "N раз"
    TextField("hero_count", x=462, y=1140, w=155, h=56, font=INTER_VAR, size=42, weight=400),
    # 🙏😭😡😍 strip
    TextField("emojis_strip", x=232, y=1320, w=615, h=80, font=EMOJI_FONT, size=96, emoji=True),
]

# 12 — топ-фразы: 6 фраз через \n
TOP_PHRASES_FIELDS: list[TextField] = [
    TextField("phrases_block", x=0, y=480, w=1080, h=900, font=INTER_VAR, size=85, weight=400),
]

# 14 — канал в одной фразе (длинный LLM-текст, нужен перенос)
ONE_PHRASE_FIELDS: list[TextField] = [
    # сама фраза от AI — крупно, центрирована, с автопереносом
    TextField("phrase", x=120, y=860, w=840, h=340, font=INTER_VAR, size=48, weight=600),
    # подпись "сгенерировано Qwen на основе N постов"
    TextField("source_caption", x=170, y=1310, w=739, h=84, font=INTER_VAR, size=32, weight=400, color="#bbbbbb"),
]

# 18 — топ-имена (как 11/12, multi-line list)
TOP_PERSON_FIELDS: list[TextField] = [
    TextField("people_block", x=0, y=820, w=1080, h=900, font=INTER_VAR, size=85, weight=400),
]

# 11 — география: 6 cities как одно multi-line поле + heart_caption + total_caption
GEOGRAPHY_FIELDS: list[TextField] = [
    # "N упоминаний городов"
    TextField("total_caption", x=0, y=312, w=1080, h=36, font=INTER_VAR, size=48, weight=400, color="#cccccc"),
    # 6 строк в формате "city – N", все через \n
    TextField("cities_block", x=0, y=470, w=1080, h=900, font=INTER_VAR, size=85, weight=400),
    # "сердце канала — Тбилиси"
    TextField("heart_caption", x=0, y=1430, w=1080, h=45, font=INTER_VAR, size=42, weight=400, color="#cccccc"),
]


CARD_FIELDS: dict[str, list[TextField]] = {
    "01_cover":             COVER_FIELDS,
    "04_sum_of_reactions":  SUM_REACTIONS_FIELDS,
    "05_archetype_vocab":   ARCHETYPE_VOCAB_FIELDS,
    "06_chronotype":        CHRONOTYPE_FIELDS,
    "10_archetype_bad":     ARCHETYPE_BAD_FIELDS,
    "11_geography":         GEOGRAPHY_FIELDS,
    "12_top_phrases":       TOP_PHRASES_FIELDS,
    "13_emotions":          EMOTIONS_FIELDS,
    "14_one_phrase":        ONE_PHRASE_FIELDS,
    "16_reading_statistics": READING_FIELDS,
    "17_most_used_word":    MOST_USED_WORD_FIELDS,
    "18_top_person":        TOP_PERSON_FIELDS,
    # 02, 03, 07, 08, 09, 15 — последняя пачка (нужны charts/cloud images)
}
