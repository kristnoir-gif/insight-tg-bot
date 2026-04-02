"""
Архетип канала — классификация + визуальная карточка v4.
Фон из Figma (bg_pics/) + шрифт Manrope + Pillow.
"""
import logging
import os
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Пути
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
BG_DIR = os.path.join(BASE_DIR, "bg_pics")
FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")

# Шрифты (variable font — один файл, разные веса)
_FONT_PATH = os.path.join(FONTS_DIR, "Manrope-Variable.ttf")
_WEIGHT_MAP = {
    "Regular": 400,
    "SemiBold": 600,
    "Bold": 700,
    "ExtraBold": 800,
}

def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(_FONT_PATH, size)
    if weight in _WEIGHT_MAP:
        f.set_variation_by_axes([_WEIGHT_MAP[weight]])
    return f


# Размер карточки (Stories 9:16)
CARD_W, CARD_H = 1080, 1920


@dataclass
class Archetype:
    """Архетип канала."""
    name: str
    emoji: str
    tagline: str
    color: str
    description: str
    bg_file: str  # файл фона из bg_pics/


# Архетипы — каждому назначен фон
ARCHETYPES = {
    "rebel": Archetype(
        name="Бунтарь",
        emoji="🔥",
        tagline="срывает покровы\nи не извиняется",
        color="#e91e8c",
        description="Высокая экспрессия, не стесняется в выражениях. "
                    "Пишет как чувствует, фильтры отключены.",
        bg_file="iPhone 16 - 1.png",  # оранжево-розовый
    ),
    "philosopher": Archetype(
        name="Философ",
        emoji="🧠",
        tagline="думает вслух,\nно красиво",
        color="#8b5cf6",
        description="Длинные тексты, абстрактная лексика, мало мата. "
                    "Канал для тех, кто любит подумать.",
        bg_file="iPhone 16 - 3.png",  # фиолетовый
    ),
    "chronicler": Archetype(
        name="Летописец",
        emoji="📜",
        tagline="документирует\nреальность",
        color="#3b82f6",
        description="Равномерная активность, конкретная лексика, упоминает людей. "
                    "Фиксирует события, а не рефлексирует.",
        bg_file="iPhone 16 - 6.png",  # голубой
    ),
    "entertainer": Archetype(
        name="Шоумен",
        emoji="🎭",
        tagline="пишет чтобы\nвас развлечь",
        color="#fbbf24",
        description="Много эмодзи, короткие посты, высокая экспрессия. "
                    "Контент заточен под реакцию.",
        bg_file="iPhone 16 - 5.png",  # жёлто-зелёный
    ),
    "night_owl": Archetype(
        name="Сова-инсомник",
        emoji="🦉",
        tagline="лучшие мысли приходят\nпосле полуночи",
        color="#818cf8",
        description="Пик активности ночью. Когда все спят — "
                    "автор только разогревается.",
        bg_file="iPhone 16 - 3.png",  # фиолетовый
    ),
    "machine": Archetype(
        name="Контент-машина",
        emoji="⚙️",
        tagline="стабильность —\nпризнак мастерства",
        color="#10b981",
        description="Регулярные посты, ровный тон, без всплесков. "
                    "Профессиональный подход к контенту.",
        bg_file="iPhone 16 - 4.png",  # зелёный
    ),
    "gossiper": Archetype(
        name="Тусовщик",
        emoji="🗣",
        tagline="знает всех\nи расскажет о каждом",
        color="#f97316",
        description="Много упоминаний имён и личностей. "
                    "Канал — социальный хаб.",
        bg_file="iPhone 16 - 1.png",  # оранжево-розовый
    ),
    "poet": Archetype(
        name="Поэт",
        emoji="✨",
        tagline="слова как музыка",
        color="#a78bfa",
        description="Богатый словарный запас, много метафизической лексики. "
                    "Автор выбирает слова как ювелир — камни.",
        bg_file="iPhone 16 - 3.png",  # фиолетовый
    ),
    "minimalist": Archetype(
        name="Минималист",
        emoji="◽",
        tagline="меньше слов —\nбольше смысла",
        color="#6b7280",
        description="Короткие посты, мало эмодзи, спокойный тон. "
                    "Каждое слово на вес золота.",
        bg_file="iPhone 16 - 6.png",  # голубой
    ),
    "agitator": Archetype(
        name="Агитатор",
        emoji="📢",
        tagline="имеет мнение\nи транслирует его",
        color="#ef4444",
        description="Высокий scream index, много восклицательных знаков. "
                    "Автор убеждает, а не рассказывает.",
        bg_file="iPhone 16 - 1.png",  # оранжево-розовый
    ),
    "reposter": Archetype(
        name="Куратор",
        emoji="🔄",
        tagline="отбирает лучшее\nиз чужого",
        color="#06b6d4",
        description="Высокий процент репостов. "
                    "Канал — кураторская подборка, не авторский контент.",
        bg_file="iPhone 16 - 4.png",  # зелёный
    ),
    "diarist": Archetype(
        name="Дневник",
        emoji="📖",
        tagline="личное пространство\nв публичном поле",
        color="#ec4899",
        description="Много позитивной лексики, средняя длина, личный тон. "
                    "Автор пишет для себя, но читают все.",
        bg_file="iPhone 16 - 6.png",  # голубой
    ),
}


def classify_archetype(
    scream_index: float,
    avg_len: float,
    unique_count: int,
    mat_count: int,
    pos_percent: float,
    agg_percent: float,
    meta_percent: float,
    everyday_percent: float,
    names_count: int,
    emoji_count: int,
    repost_percent: float,
    night_post_percent: float,
    total_posts: int,
) -> Archetype:
    """
    Классифицирует канал по архетипу на основе метрик.
    Приоритет: более специфичные архетипы сначала.
    """
    if repost_percent > 40:
        return ARCHETYPES["reposter"]
    if mat_count > 20 and scream_index > 4:
        return ARCHETYPES["rebel"]
    if night_post_percent > 35:
        return ARCHETYPES["night_owl"]
    if names_count > 30 and avg_len < 60 and mat_count > 5:
        return ARCHETYPES["gossiper"]
    if scream_index > 6:
        return ARCHETYPES["agitator"]
    if avg_len < 30 and emoji_count > 50 and scream_index > 3:
        return ARCHETYPES["entertainer"]
    if avg_len > 60 and meta_percent > 50:
        return ARCHETYPES["philosopher"]
    if unique_count > 2000 and meta_percent > 40:
        return ARCHETYPES["poet"]
    if avg_len < 25 and scream_index < 2 and emoji_count < 20:
        return ARCHETYPES["minimalist"]
    if pos_percent > 60 and 30 < avg_len < 80:
        return ARCHETYPES["diarist"]
    if names_count > 15 and everyday_percent > 50:
        return ARCHETYPES["chronicler"]
    return ARCHETYPES["machine"]


def _alpha_rect(bg: Image.Image, xy, radius: int,
                fill=(255, 255, 255, 40)):
    """Рисует полупрозрачный прямоугольник через отдельный слой."""
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle(xy, radius=radius, fill=fill)
    return Image.alpha_composite(bg, overlay)


def _draw_badge(bg: Image.Image, text: str, font: ImageFont.FreeTypeFont,
                center_x: int, y: int, pad_x: int = 40, pad_y: int = 20,
                bg_color=(255, 255, 255, 40), text_color=(255, 255, 255)):
    """Рисует текстовый бейдж с полупрозрачным фоном. Возвращает новый Image."""
    tmp_draw = ImageDraw.Draw(bg)
    bbox = tmp_draw.multiline_textbbox((0, 0), text, font=font, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    rx0 = center_x - tw // 2 - pad_x
    ry0 = y - pad_y
    rx1 = center_x + tw // 2 + pad_x
    ry1 = y + th + pad_y
    bg = _alpha_rect(bg, (rx0, ry0, rx1, ry1), radius=20, fill=bg_color)
    draw = ImageDraw.Draw(bg)
    draw.multiline_text((center_x, y), text, font=font, fill=text_color,
                        anchor="ma", align="center")
    return bg


def _draw_stat_box(bg: Image.Image, cx: int, cy: int,
                   value: str, label: str,
                   font_value: ImageFont.FreeTypeFont,
                   font_label: ImageFont.FreeTypeFont,
                   box_w: int = 200, box_h: int = 120):
    """Рисует блок статистики. Возвращает новый Image."""
    x0, y0 = cx - box_w // 2, cy - box_h // 2
    x1, y1 = cx + box_w // 2, cy + box_h // 2
    bg = _alpha_rect(bg, (x0, y0, x1, y1), radius=18,
                     fill=(255, 255, 255, 35))
    draw = ImageDraw.Draw(bg)
    draw.text((cx, cy - 12), value, font=font_value,
              fill=(255, 255, 255), anchor="mm")
    draw.text((cx, cy + 30), label, font=font_label,
              fill=(255, 255, 255, 180), anchor="mm")
    return bg


def generate_archetype_card(
    username: str,
    title: str,
    archetype: Archetype,
    stats_summary: dict,
) -> str | None:
    """
    Генерирует визуальную карточку архетипа v4.
    Фон из Figma + шрифт Manrope + Pillow.
    """
    try:
        path = f"archetype_{username}.png"

        # --- Фон ---
        bg_path = os.path.join(BG_DIR, archetype.bg_file)
        if os.path.exists(bg_path):
            bg = Image.open(bg_path).convert("RGBA")
            bg = bg.resize((CARD_W, CARD_H), Image.LANCZOS)
        else:
            bg = Image.new("RGBA", (CARD_W, CARD_H), (30, 30, 50, 255))
            logger.warning(f"Фон не найден: {bg_path}, используем fallback")

        # --- Шрифты ---
        font_badge = _font("Bold", 28)
        font_name = _font("ExtraBold", 96)
        font_name_sm = _font("ExtraBold", 72)
        font_tagline = _font("SemiBold", 30)
        font_stat_val = _font("Bold", 48)
        font_stat_lbl = _font("Regular", 22)
        font_fact = _font("SemiBold", 26)
        font_watermark = _font("Bold", 28)

        cx = CARD_W // 2

        # --- Заголовок: АРХЕТИП КАНАЛА / channel name ---
        from visualization.utils import clean_title as _clean_title
        clean = _clean_title(title)
        header_text = f"АРХЕТИП КАНАЛА\n{clean.upper()}"
        bg = _draw_badge(bg, header_text, font_badge, cx, 140,
                         pad_x=50, pad_y=25)

        # --- Название архетипа (большое) ---
        name_text = archetype.name
        font_n = font_name if len(name_text) <= 10 else font_name_sm
        draw = ImageDraw.Draw(bg)
        draw.text((cx, 380), name_text, font=font_n,
                  fill=(255, 255, 255), anchor="mm")

        # --- Тэглайн в бейдже ---
        bg = _draw_badge(bg, archetype.tagline, font_tagline, cx, 470,
                         pad_x=45, pad_y=22)

        # --- 3 блока статистики ---
        post_count = stats_summary.get('post_count', 0)
        unique_count = stats_summary.get('unique_count', 0)
        avg_len = stats_summary.get('avg_len', 0)
        avg_len_str = f"{avg_len:.0f}" if isinstance(avg_len, float) else str(avg_len)

        stats_y = 1250
        gap = 240
        items = [
            (str(post_count), "постов"),
            (str(unique_count), "слов"),
            (avg_len_str, "сл. пост"),
        ]
        for i, (val, lbl) in enumerate(items):
            sx = cx - gap + i * gap
            bg = _draw_stat_box(bg, sx, stats_y, val, lbl,
                                font_stat_val, font_stat_lbl)

        # --- Fun facts ---
        draw = ImageDraw.Draw(bg)
        facts = stats_summary.get('fun_facts', [])
        if facts:
            fy = 1420
            for j, fact in enumerate(facts[:2]):
                draw.text((cx, fy + j * 60), fact, font=font_fact,
                          fill=(255, 255, 255), anchor="mm")

        # --- Watermark ---
        draw.text((cx, CARD_H - 80), "@insight_tg_bot", font=font_watermark,
                  fill=(255, 255, 255, 100), anchor="mm")

        # --- Сохраняем ---
        bg.convert("RGB").save(path, quality=95)
        logger.info(f"Создана карточка архетипа v4: {path} ({archetype.name})")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания карточки архетипа: {e}")
        return None


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    """Переносит текст по словам, чтобы вместить в max_width пикселей."""
    words = text.split()
    lines = []
    current_line = []

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


# Маппинг эмодзи → категория для карточки инсайтов
_INSIGHT_LABELS = {
    "\u23f0": "ВРЕМЯ",        # ⏰
    "\U0001f4c5": "ДНИ НЕДЕЛИ",    # 📅
    "\U0001f60a": "ТОНАЛЬНОСТЬ",   # 😊
    "\U0001f624": "ТОНАЛЬНОСТЬ",   # 😤
    "\u26a1": "ТОНАЛЬНОСТЬ",       # ⚡
    "\U0001f9e0": "СТИЛЬ",         # 🧠
    "\U0001f3e0": "СТИЛЬ",         # 🏠
    "\U0001f465": "ЛИЧНОСТИ",      # 👥
    "\U0001f464": "ЛИЧНОСТИ",      # 👤
    "\U0001f4ac": "ФРАЗЫ",         # 💬
    "\U0001f524": "СЛОВА",         # 🔤
    "\U0001f319": "НОЧНАЯ АКТИВНОСТЬ",  # 🌙
    "\U0001f504": "КОНТЕНТ",       # 🔄
    "\u270d\ufe0f": "КОНТЕНТ",     # ✍️
}


def _parse_insight(text: str) -> tuple[str, str]:
    """Разбирает инсайт на (категория, текст без эмодзи)."""
    for emoji, label in _INSIGHT_LABELS.items():
        if text.startswith(emoji):
            return label, text[len(emoji):].strip()
    # fallback: вернуть без изменений
    return "ИНСАЙТ", text.strip()


def generate_insights_card(
    username: str,
    title: str,
    insights: list[str],
) -> str | None:
    """
    Генерирует инфографику со всеми инсайтами канала.
    Stories 9:16, Spotify Wrapped стиль.
    """
    if not insights:
        return None

    try:
        path = f"insights_{username}.png"

        # --- Фон (тёплый оранжево-розовый) ---
        bg_path = os.path.join(BG_DIR, "iPhone 16 - 1.png")
        if os.path.exists(bg_path):
            bg = Image.open(bg_path).convert("RGBA")
            bg = bg.resize((CARD_W, CARD_H), Image.LANCZOS)
        else:
            bg = Image.new("RGBA", (CARD_W, CARD_H), (30, 30, 50, 255))

        # --- Шрифты ---
        font_badge = _font("Bold", 28)
        font_header = _font("ExtraBold", 64)
        font_label = _font("ExtraBold", 24)
        font_text = _font("SemiBold", 30)
        font_watermark = _font("Bold", 28)

        cx = CARD_W // 2
        margin = 80  # отступ от краёв

        # --- Заголовок ---
        from visualization.utils import clean_title as _clean_title
        clean = _clean_title(title)
        header_text = f"ИНСАЙТЫ КАНАЛА\n{clean.upper()}"
        bg = _draw_badge(bg, header_text, font_badge, cx, 120,
                         pad_x=50, pad_y=25)

        # --- Подзаголовок ---
        draw = ImageDraw.Draw(bg)
        draw.text((cx, 310), "ЧТО ГОВОРЯТ ЦИФРЫ", font=font_header,
                  fill=(255, 255, 255), anchor="mm")

        # --- Инсайты ---
        y_cursor = 420
        max_text_width = CARD_W - margin * 2 - 40  # с учётом padding внутри блока

        for insight_raw in insights:
            label, text = _parse_insight(insight_raw)
            wrapped = _wrap_text(text, font_text, max_text_width)

            # Измеряем высоту текста
            text_bbox = draw.multiline_textbbox((0, 0), wrapped, font=font_text)
            text_h = text_bbox[3] - text_bbox[1]

            # Высота блока: label (30) + gap (8) + text + padding
            block_h = 30 + 8 + text_h + 40  # 20 padding сверху + 20 снизу
            block_top = y_cursor
            block_bottom = y_cursor + block_h

            # Проверяем что влезает
            if block_bottom > CARD_H - 120:
                break

            # Полупрозрачный фон блока
            bg = _alpha_rect(bg,
                             (margin, block_top, CARD_W - margin, block_bottom),
                             radius=16,
                             fill=(255, 255, 255, 30))
            draw = ImageDraw.Draw(bg)

            # Категория (маленький label)
            draw.text((margin + 20, block_top + 14), label, font=font_label,
                      fill=(255, 255, 255, 160), anchor="la")

            # Текст инсайта
            draw.multiline_text((margin + 20, block_top + 14 + 30 + 8), wrapped,
                                font=font_text, fill=(255, 255, 255), anchor="la")

            y_cursor = block_bottom + 14  # gap между блоками

        # --- Watermark ---
        draw = ImageDraw.Draw(bg)
        draw.text((cx, CARD_H - 80), "@insight_tg_bot", font=font_watermark,
                  fill=(255, 255, 255, 100), anchor="mm")

        # --- Сохраняем ---
        bg.convert("RGB").save(path, quality=95)
        logger.info(f"Создана карточка инсайтов: {path} ({len(insights)} items)")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания карточки инсайтов: {e}")
        return None


def generate_topics_card(
    username: str,
    title: str,
    topics: list[str],
) -> str | None:
    """
    Генерирует карточку топ-3 тем канала.
    Stories 9:16, фон из bg_pics/, шрифт Manrope.
    """
    try:
        path = f"topics_{username}.png"

        # --- Фон (фиолетовый) ---
        bg_path = os.path.join(BG_DIR, "iPhone 16 - 3.png")
        if os.path.exists(bg_path):
            bg = Image.open(bg_path).convert("RGBA")
            bg = bg.resize((CARD_W, CARD_H), Image.LANCZOS)
        else:
            bg = Image.new("RGBA", (CARD_W, CARD_H), (30, 30, 50, 255))

        # --- Шрифты ---
        font_badge = _font("Bold", 28)
        font_header = _font("ExtraBold", 72)
        font_number = _font("ExtraBold", 120)
        font_topic = _font("Bold", 48)
        font_watermark = _font("Bold", 28)

        cx = CARD_W // 2

        # --- Заголовок ---
        from visualization.utils import clean_title as _clean_title
        clean = _clean_title(title)
        header_text = f"ТЕМЫ КАНАЛА\n{clean.upper()}"
        bg = _draw_badge(bg, header_text, font_badge, cx, 140,
                         pad_x=50, pad_y=25)

        # --- Заголовок TOP 3 ---
        draw = ImageDraw.Draw(bg)
        draw.text((cx, 380), "TOP 3", font=font_header,
                  fill=(255, 255, 255), anchor="mm")

        # --- 3 темы ---
        topic_y_start = 580
        topic_gap = 320

        for i, topic in enumerate(topics[:3]):
            y = topic_y_start + i * topic_gap

            # Номер (большой, полупрозрачный)
            bg = _alpha_rect(bg,
                             (cx - 80, y - 60, cx + 80, y + 70),
                             radius=24,
                             fill=(255, 255, 255, 30))
            draw = ImageDraw.Draw(bg)
            draw.text((cx, y), str(i + 1), font=font_number,
                      fill=(255, 255, 255, 200), anchor="mm")

            # Название темы под номером
            topic_text = topic[:30]  # ограничиваем длину
            draw.text((cx, y + 110), topic_text, font=font_topic,
                      fill=(255, 255, 255), anchor="mm")

        # --- Watermark ---
        draw.text((cx, CARD_H - 80), "@insight_tg_bot", font=font_watermark,
                  fill=(255, 255, 255, 100), anchor="mm")

        # --- Сохраняем ---
        bg.convert("RGB").save(path, quality=95)
        logger.info(f"Создана карточка тем: {path} ({topics})")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания карточки тем: {e}")
        return None


def generate_fun_facts(
    scream_index: float,
    avg_len: float,
    unique_count: int,
    total_posts: int,
    top_word: str | None,
    top_word_count: int,
    mat_count: int,
    pos_percent: float,
    agg_percent: float,
    night_post_percent: float,
    peak_hour: int | None,
    peak_weekday: int | None,
    names_count: int,
    repost_percent: float,
    emoji_count: int,
    top_emoji: str | None,
) -> list[str]:
    """Генерирует список забавных/неочевидных фактов о канале."""
    facts = []
    weekdays = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье']

    if peak_hour is not None:
        if peak_hour >= 23 or peak_hour <= 4:
            facts.append(f"Пик постинга в {peak_hour}:00 — автор сова")
        elif 5 <= peak_hour <= 7:
            facts.append(f"Постит в {peak_hour}:00 — жаворонок или не ложился?")

    if night_post_percent > 30:
        facts.append(f"{night_post_percent:.0f}% постов написаны ночью (23-05)")

    if top_word and top_word_count > 0 and total_posts > 0:
        per_post = top_word_count / total_posts
        if per_post > 0.3:
            facts.append(f"«{top_word}» встречается почти в каждом 3-м посте")
        elif per_post > 0.15:
            facts.append(f"«{top_word}» — слово-мантра автора ({top_word_count} раз)")

    if unique_count > 3000:
        facts.append(f"Словарный запас {unique_count} слов — уровень литератора")
    elif unique_count < 500 and total_posts > 50:
        facts.append(f"Всего {unique_count} уникальных слов — автор лаконичен")

    if mat_count == 0 and total_posts > 50:
        facts.append("Ни одного мата — идеальная карма")
    elif mat_count > 100:
        avg_per_post = mat_count / max(total_posts, 1)
        facts.append(f"~{avg_per_post:.1f} мата на пост — экспрессивный стиль")

    if avg_len > 100:
        facts.append(f"Средний пост {avg_len:.0f} слов — это почти эссе")
    elif avg_len < 15:
        facts.append(f"Средний пост {avg_len:.0f} слов — как твит")

    if pos_percent > 80:
        facts.append(f"Позитив зашкаливает: {pos_percent:.0f}% светлых слов")
    elif agg_percent > 60:
        facts.append(f"{agg_percent:.0f}% агрессивной лексики — канал не для слабонервных")

    if scream_index > 8:
        facts.append("Scream Index зашкаливает — автор КРИЧИТ КАПСОМ")
    elif scream_index < 1:
        facts.append("Scream Index < 1 — тише воды, ниже травы")

    if names_count > 50:
        facts.append(f"{names_count} упомянутых имён — автор знает полгорода")

    if repost_percent > 50:
        facts.append(f"{repost_percent:.0f}% контента — репосты. Куратор, не автор")
    elif repost_percent == 0 and total_posts > 30:
        facts.append("0% репостов — 100% авторский контент")

    if emoji_count > 200:
        facts.append(f"{emoji_count} эмодзи — автор мыслит картинками")
    elif emoji_count == 0 and total_posts > 30:
        facts.append("Ноль эмодзи — чистый текст, без украшательств")

    if top_emoji and emoji_count > 10:
        facts.append(f"Любимый эмодзи — {top_emoji}")

    if peak_weekday is not None:
        if peak_weekday in (5, 6):
            facts.append(f"Больше всего постов в {weekdays[peak_weekday]} — работает на выходных")
        elif peak_weekday == 0:
            facts.append("Понедельник — самый продуктивный день")

    random.shuffle(facts)
    return facts[:5]
