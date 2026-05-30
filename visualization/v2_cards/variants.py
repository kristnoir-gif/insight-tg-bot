"""
Карта вариантов архетипов: Figma node-id → имя + bucket + динамические поля.

Для каждой архетип-карточки в Figma есть N визуальных вариантов
(свой 3D-арт, фон, цвет). Юзер по результату анализа получает ОДИН.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArchetypeVariant:
    """Один вариант архетип-карточки."""
    name: str           # Короткое имя для кода/файла (e.g. "wolf", "intellectual")
    title: str          # Что показывается на карточке (e.g. "ВОЛК", "Интеллектуал")
    figma_id: str       # ID в Figma
    # Bucket — для классификации (диапазон значений)
    bucket_min: float = 0.0
    bucket_max: float = float("inf")
    # Имя файла чистого шаблона (PNG без динамики, в assets/figma/variants_clean/)
    png_file: str = ""


# --- Хронотип: 9 вариантов по peak_hour ---
CHRONOTYPE_VARIANTS: list[ArchetypeVariant] = [
    ArchetypeVariant("wolf",         "ВОЛК",         "383:1067", 21, 23.99, "chronotype_wolf.png"),
    ArchetypeVariant("owl",          "СОВА",         "383:992",   0,  2.99, "chronotype_owl.png"),
    ArchetypeVariant("lunatik",      "ЛУНАТИК",      "383:1003",  3,  5.99, "chronotype_lunatik.png"),
    ArchetypeVariant("lark",         "ЖАВОРОНОК",    "383:1036",  6,  8.99, "chronotype_lark.png"),
    ArchetypeVariant("tit",          "СИНИЦА",       "383:1025",  9, 11.99, "chronotype_tit.png"),
    ArchetypeVariant("squirrel",     "БЕЛОЧКА",      "383:1056", 12, 14.99, "chronotype_squirrel.png"),
    ArchetypeVariant("cat",          "КОТ",          "383:1045", 15, 17.99, "chronotype_cat.png"),
    ArchetypeVariant("fox",          "ЛИСА",         "383:1014", 18, 20.99, "chronotype_fox.png"),
    ArchetypeVariant("chrono_chaos", "ХРОНО-ХАОС",   "383:1078",  0, 0,     "chronotype_chaos.png"),
]

CHRONOTYPE_TOD_PHRASE: dict[str, str] = {
    "wolf":     "вечером",
    "owl":      "после полуночи",
    "lunatik":  "после полуночи",
    "lark":     "утром",
    "tit":      "утром",
    "squirrel": "после полудня",
    "cat":      "после полудня",
    "fox":      "вечером",
    "chrono_chaos": "размазанно",
}

CHRONOTYPE_PEAK_HOUR_DISPLAY: dict[str, str] = {
    "wolf":     "22:00",
    "owl":      "01:00",
    "lunatik":  "03:00",
    "lark":     "06:00",
    "tit":      "09:00",
    "squirrel": "12:00",
    "cat":      "15:00",
    "fox":      "18:00",
    "chrono_chaos": "",
}


# --- Архетип по словарю: 8 вариантов по unique_count ---
VOCAB_VARIANTS: list[ArchetypeVariant] = [
    ArchetypeVariant("less_6000",          "",                  "383:645",     0,  9_246,        "vocab_less_6000.png"),
    ArchetypeVariant("intellectual",       "Интеллектуал",      "383:656",  9_247, 12_246,       "vocab_intellectual.png"),
    ArchetypeVariant("master_of_words",    "Мастер Слова",      "383:668", 12_247, 14_999,       "vocab_master_of_words.png"),
    ArchetypeVariant("linguist",           "Лингвист",          "383:680", 15_000, 18_236,       "vocab_linguist.png"),
    ArchetypeVariant("poet",               "Поэт",              "383:691", 18_237, 22_236,       "vocab_poet.png"),
    ArchetypeVariant("writer",             "Писатель",          "383:703", 22_237, 27_236,       "vocab_writer.png"),
    ArchetypeVariant("great_writer",       "Великий Писатель",  "383:715", 27_237, 36_236,       "vocab_great_writer.png"),
    ArchetypeVariant("lexical_titan",      "Лексический Титан", "383:727", 36_237, float("inf"), "vocab_lexical_titan.png"),
]


# --- Архетип по мату: 7 вариантов по mat_percent_of_text ---
# Note: ЯДЕРНЫЙ в Figma показан с 0.95% — вероятно опечатка, должно быть выше ЯДОВИТОГО.
# Использую логичные пороги (АНГЕЛ < СВЕТЛЫЙ < ПРЯМОЙ < ... < ДОТЕР).
TOXICITY_VARIANTS: list[ArchetypeVariant] = [
    ArchetypeVariant("angel",   "АНГЕЛ",    "383:521",  0.0,   0.001,         "tox_angel.png"),
    ArchetypeVariant("light",   "СВЕТЛЫЙ",  "383:533",  0.001, 0.5,           "tox_light.png"),
    ArchetypeVariant("right",   "ПРЯМОЙ",   "383:544",  0.5,   1.0,           "tox_right.png"),
    ArchetypeVariant("sharp",   "ОСТРЫЙ",   "383:555",  1.0,   1.5,           "tox_sharp.png"),
    ArchetypeVariant("poison",  "ЯДОВИТЫЙ", "383:566",  1.5,   2.5,           "tox_poison.png"),
    ArchetypeVariant("nuclear", "ЯДЕРНЫЙ",  "383:589",  2.5,   5.0,           "tox_nuclear.png"),
    ArchetypeVariant("gamer",   "ДОТЕР",    "383:577",  5.0,   float("inf"),  "tox_gamer.png"),
]


# --- Юнгианский архетип: 12 вариантов (классификация LLM'ом) ---
JUNGIAN_VARIANTS: list[ArchetypeVariant] = [
    ArchetypeVariant("sage",       "Мудрец",         "355:2859",  0, 0, "jung_sage.png"),
    ArchetypeVariant("explorer",   "Искатель",       "355:2868",  0, 0, "jung_explorer.png"),
    ArchetypeVariant("innocent",   "Простодушный",   "355:2877",  0, 0, "jung_innocent.png"),
    ArchetypeVariant("outlaw",     "Бунтарь",        "355:2824",  0, 0, "jung_outlaw.png"),
    ArchetypeVariant("hero",       "Борец",          "355:2896",  0, 0, "jung_hero.png"),
    ArchetypeVariant("creator",    "Творец",         "355:2907",  0, 0, "jung_creator.png"),
    ArchetypeVariant("everyman",   "Славный малый",  "355:2918",  0, 0, "jung_everyman.png"),
    ArchetypeVariant("lover",      "Любовник",       "355:2926",  0, 0, "jung_lover.png"),
    ArchetypeVariant("jester",     "Шут",            "355:2934",  0, 0, "jung_jester.png"),
    ArchetypeVariant("caregiver",  "Опекун",         "355:2950",  0, 0, "jung_caregiver.png"),
    ArchetypeVariant("ruler",      "Правитель",      "355:2958",  0, 0, "jung_ruler.png"),
    ArchetypeVariant("magician",   "Маг",            "355:2966",  0, 0, "jung_magician.png"),
]

# Юнгианские архетипы у которых ЕСТЬ динамический % в описании.
# Для остальных описание уже на PNG и менять не нужно.
JUNGIAN_WITH_PCT = {
    "sage":   "Аналитический контент ({pct}% постов) и сложные смыслы",
    "outlaw": "Острая критика: {pct}% постов содержат провокационные тезисы",
}


def pick_chronotype(peak_hour: int, total_posts: int = 0, hour_counts: dict | None = None) -> ArchetypeVariant:
    """По peak_hour выбирает вариант хронотипа. Если активность размазана → chrono_chaos."""
    # Хроно-хаос: если ни один час не доминирует значительно над остальными
    if hour_counts and total_posts > 0:
        max_share = max(hour_counts.values()) / total_posts
        if max_share < 0.08:  # <8% постов в самом активном часе — слишком размазано
            return CHRONOTYPE_VARIANTS[-1]  # chrono_chaos
    for v in CHRONOTYPE_VARIANTS[:-1]:
        if v.bucket_min <= peak_hour <= v.bucket_max:
            return v
    return CHRONOTYPE_VARIANTS[-1]


def pick_vocab(unique_count: int) -> ArchetypeVariant:
    for v in VOCAB_VARIANTS:
        if v.bucket_min <= unique_count <= v.bucket_max:
            return v
    return VOCAB_VARIANTS[0]


def pick_toxicity(mat_percent: float) -> ArchetypeVariant:
    for v in TOXICITY_VARIANTS:
        if v.bucket_min <= mat_percent < v.bucket_max:
            return v
    return TOXICITY_VARIANTS[0]


def find_jungian(name: str) -> ArchetypeVariant | None:
    """Поиск по коду или title — для LLM-классификатора."""
    n = name.lower().strip()
    for v in JUNGIAN_VARIANTS:
        if v.name == n or v.title.lower() == n:
            return v
    return None
