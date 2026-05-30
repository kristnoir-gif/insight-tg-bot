"""
Рендер общих карточек v2 на основе точных Figma-координат
(из cards_structure.json). Каждое поле в Figma имеет точный bounding box
и стиль — здесь применяем их 1:1.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from analyzer import AnalysisResult
from .positions import INTER_VAR, INTER_ITALIC, NOOKS_BOLD, NOOKS_EDU_BLACK, EMOJI_FONT
from .pills import draw_pill, layout_pills_cascade, draw_channel_subtitle
from .card_data import _format_int, _format_k
from .figma_layout import draw_in_box, draw_centered_in_box, draw_text_with_emojis, _font

TEMPLATES = Path(__file__).parent.parent.parent / "assets" / "figma" / "variants_clean"


def _open(name: str) -> Image.Image:
    p = TEMPLATES / name
    if not p.exists():
        raise FileNotFoundError(f"Template missing: {p}")
    return Image.open(p).convert("RGB")


def _to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ============================================================================
# 01 COVER
# ============================================================================
def render_01_cover(r: AnalysisResult) -> bytes:
    img = _open("01_cover.png")
    v = r.v2

    # Стек строк сверху: TELEGRAM RECAP → название канала. Спейсинг 100px между
    # верхами строк (одинаковый между ВСЕМИ строками если перенос).
    LINE_H = 100
    Y_TOP = 199
    name = (r.title or "канал").upper()

    from PIL import ImageDraw as _ID
    draw = _ID.Draw(img)
    test_font = _font(INTER_VAR, 100, 900)
    name_w = draw.textbbox((0, 0), name, font=test_font)[2]

    # Собираем все строки
    if name_w <= 950:
        lines = ["TELEGRAM RECAP", name]
    else:
        words = name.split(" ")
        if len(words) >= 2:
            best_split = len(words) // 2
            for i in range(1, len(words)):
                l1 = " ".join(words[:i])
                l2 = " ".join(words[i:])
                w1 = draw.textbbox((0, 0), l1, font=test_font)[2]
                w2 = draw.textbbox((0, 0), l2, font=test_font)[2]
                if w1 <= 950 and w2 <= 950:
                    best_split = i
                    break
            lines = ["TELEGRAM RECAP",
                     " ".join(words[:best_split]),
                     " ".join(words[best_split:])]
        else:
            # одно длинное слово — уменьшаем шрифт
            size = 100
            while size > 50:
                f_test = _font(INTER_VAR, size, 900)
                if draw.textbbox((0, 0), name, font=f_test)[2] <= 950:
                    break
                size -= 5
            # Рендерим только 2 строки
            draw_in_box(img, "TELEGRAM RECAP", x=75, y=Y_TOP, w=950, h=100,
                        font_path=INTER_VAR, size=100, weight=900)
            draw_text_with_emojis(img, name, x=75, y=Y_TOP + LINE_H, w=950, h=110,
                                   font_path=INTER_VAR, size=size, weight=900)
            lines = None  # уже нарисовали

    if lines is not None:
        for i, line in enumerate(lines):
            y_line = Y_TOP + i * LINE_H
            if i == 0:
                draw_in_box(img, line, x=75, y=y_line, w=950, h=110,
                            font_path=INTER_VAR, size=100, weight=900)
            else:
                draw_text_with_emojis(img, line, x=75, y=y_line, w=950, h=110,
                                       font_path=INTER_VAR, size=100, weight=900)

    # Годы — Inter Italic 80. Если анализ в пределах одного года — пишем только год.
    if v.start_date and v.end_date:
        start_y, end_y = v.start_date[:4], v.end_date[:4]
        years = start_y if start_y == end_y else f"{start_y}–{end_y}"
        draw_in_box(img, years, x=166, y=538, w=748, h=58,
                    font_path=INTER_ITALIC, size=80, weight=400)

    # Hero NOOKS Bold 450 — БОЛЬШОЙ. min_size 430 (было 400).
    if v.total_posts:
        hero = _format_k(v.total_posts)
        draw_centered_in_box(img, hero, x=55, y=582, w=970, h=639,
                              font_path=NOOKS_BOLD, size=450, weight=700,
                              auto_shrink=True, min_size=430)

    # 'по N в день · каждый день' — Inter Medium 50, y_center=1385 (box top ~1352)
    if v.posts_per_day_avg:
        subtitle = f"по {v.posts_per_day_avg} в день · каждый день"
        draw_in_box(img, subtitle, x=3, y=1352, w=1077, h=66,
                    font_path=INTER_VAR, size=50, weight=500)
    return _to_bytes(img)


# ============================================================================
# 02 MAIN THEMES
# ============================================================================
def render_02_main_themes(r: AnalysisResult) -> bytes:
    img = _open("02_main_themes.png")
    # Заголовок "ГЛАВНЫЕ ТЕМЫ" — TT Nooks Educational Black 120, y=191 (как в Figma)
    draw_in_box(img, "ГЛАВНЫЕ ТЕМЫ", x=0, y=191, w=1080, h=120,
                font_path=NOOKS_EDU_BLACK, size=120, weight=900)
    # Название канала — Inter Regular 50, Title Case. Отступ 45px от низа заголовка.
    name_titled = (r.title or "канал").title()
    draw_text_with_emojis(img, name_titled, x=65, y=356, w=950, h=50,
                           font_path=INTER_VAR, size=50, weight=400)
    # Pills — расщепляем темы LLM на одиночные концепты по " и ", " / ", ","
    import re
    raw_topics = list(r.topics or [])
    pills: list[str] = []
    seen = set()
    for t in raw_topics:
        # Разбиваем "Жизнь и общество" → ["Жизнь", "общество"]
        parts = re.split(r"\s+и\s+|\s*[,/]\s*", t)
        for p in parts:
            p = p.strip()
            if not p or len(p) > 16:  # отсеиваем мусор/слишком длинные
                continue
            key = p.lower()
            if key in seen:
                continue
            seen.add(key)
            pills.append(p.capitalize())
    pills = pills[:10]
    if pills:
        # Pills в области y=706..1503, не меньше 55px по бокам (max_width=970).
        # font_size=67 — как на 03 «канал в цифрах» (одинаковый стиль).
        layout_pills_cascade(img, pills, center_x=540, top_y=706,
                             font_size=67, weight=500, max_width=970,
                             auto_shrink=True)
    return _to_bytes(img)


# ============================================================================
# 03 CHANAL IN NUMBERS
# ============================================================================
def render_03_chanal_in_numbers(r: AnalysisResult) -> bytes:
    img = _open("03_chanal_in_numbers.png")
    v = r.v2
    title = (r.title or "канал").upper()
    draw = ImageDraw.Draw(img)
    # Адаптивная вёрстка title + 'в цифрах' subtitle:
    # 1 строка title  → title @ y=193, "в цифрах" @ y=343
    # 2 строки title → title @ y=140 + y=255, "в цифрах" @ y=395
    size = 120
    f_test = _font(NOOKS_BOLD, size, 700)
    text_w = draw.textbbox((0, 0), title, font=f_test)[2]
    if text_w <= 950:
        draw_text_with_emojis(img, title, x=65, y=193, w=950, h=120,
                               font_path=NOOKS_BOLD, size=size, weight=700)
        subtitle_y = 343
    else:
        words = title.split(" ")
        if len(words) >= 2:
            mid = len(words) // 2
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
            draw_text_with_emojis(img, line1, x=65, y=140, w=950, h=120,
                                   font_path=NOOKS_BOLD, size=size, weight=700)
            draw_text_with_emojis(img, line2, x=65, y=255, w=950, h=120,
                                   font_path=NOOKS_BOLD, size=size, weight=700)
            subtitle_y = 395
        else:
            while size > 60 and text_w > 950:
                size -= 5
                f_test = _font(NOOKS_BOLD, size, 700)
                text_w = draw.textbbox((0, 0), title, font=f_test)[2]
            draw_text_with_emojis(img, title, x=65, y=193, w=950, h=120,
                                   font_path=NOOKS_BOLD, size=size, weight=700)
            subtitle_y = 343
    # «в цифрах» — Inter Regular 50, под названием
    draw_in_box(img, "в цифрах", x=0, y=subtitle_y, w=1080, h=60,
                font_path=INTER_VAR, size=50, weight=400)
    # Pills — Inter Medium 67 (порядок как в Figma: реакции+лет рядом)
    facts: list[str] = []
    if v.total_chars:           facts.append(f"{_format_int(v.total_chars)} символов написано")
    if v.max_consecutive_days:  facts.append(f"рекорд {v.max_consecutive_days} дней подряд")
    if v.total_reactions:       facts.append(f"{_format_int(v.total_reactions)} реакций")
    if v.years_covered:         facts.append(f"{v.years_covered} лет")
    if v.total_words:           facts.append(f"{_format_int(v.total_words)} слов")
    if v.total_photos:          facts.append(f"{_format_int(v.total_photos)} фото")
    if facts:
        # Pills в области y=706..1503, не меньше 55px по бокам (max_width=970)
        layout_pills_cascade(img, facts, center_x=540, top_y=706,
                             font_size=67, weight=500, max_width=970,
                             auto_shrink=True)
    return _to_bytes(img)


# ============================================================================
# 04 SUM OF REACTIONS
# ============================================================================
def render_04_sum_of_reactions(r: AnalysisResult) -> bytes:
    img = _open("04_sum_of_reactions.png")
    v = r.v2
    # Hero '247К' — NOOKS sz=380 w=700 @ (156, 729) 768x380
    if v.total_reactions:
        hero = _format_k(v.total_reactions)
        draw_centered_in_box(img, hero, x=156, y=729, w=768, h=380,
                              font_path=NOOKS_BOLD, size=380, weight=700,
                              auto_shrink=True, min_size=200)
    # '≈ 13.3 на пост' — Inter sz=66 w=500 @ (2, 1526) 1077x66
    if v.avg_reactions_per_post:
        text = f"≈ {v.avg_reactions_per_post} на пост"
        draw_in_box(img, text, x=2, y=1526, w=1077, h=66,
                    font_path=INTER_VAR, size=66, weight=500)
    return _to_bytes(img)


# ============================================================================
# 07 / 09 WORD CLOUDS
# ============================================================================
def render_07_word_cloud(r: AnalysisResult) -> bytes:
    img = _open("07_word_cloud.png")
    # Channel name — Inter Regular 50 @ (171, 303) с эмодзи-aware (стрипает ZWJ)
    draw_text_with_emojis(img, r.title or "канал", x=171, y=303, w=740, h=50,
                           font_path=INTER_VAR, size=50, weight=400)
    _embed_cloud(img, r.v2.top_words_for_cloud, color_hex="#ffffff")
    return _to_bytes(img)


def render_09_bad_word_cloud(r: AnalysisResult) -> bytes:
    img = _open("09_bad_word_cloud.png")
    # Channel name — Inter Regular 50 @ (171, 313) с эмодзи-aware
    draw_text_with_emojis(img, r.title or "канал", x=171, y=313, w=740, h=50,
                           font_path=INTER_VAR, size=50, weight=400)
    _embed_cloud(img, r.v2.top_mat_words_for_cloud, color_hex="#ffffff")
    return _to_bytes(img)


# ============================================================================
# 08 POST BY DAYS WEEKS
# ============================================================================
def render_08_post_by_days_weeks(r: AnalysisResult) -> bytes:
    """Прозрачный bar chart по дням недели через PIL."""
    img = _open("08_post_by_days_weeks.png")
    # 'Любимый день — N' subtitle — Inter sz=55 w=600 @ (129, 623) 823x133
    counts = getattr(r.v2, '_weekday_counts', None) or {}
    if not counts:
        return _to_bytes(img)

    days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
    fav = max(counts, key=counts.get)
    fav_full = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][fav]
    draw_in_box(img, f"Любимый день — {fav_full}", x=129, y=623, w=823, h=80,
                font_path=INTER_VAR, size=55, weight=600)

    # Bar chart — точные позиции из Figma
    draw = ImageDraw.Draw(img)
    bar_x_centers = [276, 376, 476, 577, 676, 777, 877]  # из Figma centered positions ПН..ВС
    bar_w = 70
    chart_y_top = 780
    chart_y_bottom = 1400
    chart_h = chart_y_bottom - chart_y_top
    values = [counts.get(i, 0) for i in range(7)]
    max_v = max(values) if values else 1
    font_value = _font(INTER_VAR, 20, 700)
    font_label = _font(INTER_VAR, 20, 700)
    font_y_label = _font(INTER_VAR, 20, 500)

    # Y-axis labels (0,10,20...60) @ x=180
    y_ticks = [0, 10, 20, 30, 40, 50, 60]
    y_y_positions = [1378, 1280, 1183, 1083, 984, 884, 790]
    for tick, ypos in zip(y_ticks, y_y_positions):
        draw.text((180, ypos), str(tick), font=font_y_label, fill="white")

    # Bars + value labels + day labels
    for i, (cx, val) in enumerate(zip(bar_x_centers, values)):
        h_px = int((val / max_v) * (chart_h - 40)) if max_v else 0
        bx = cx - bar_w // 2
        by = chart_y_bottom - 30 - h_px
        # Бар полупрозрачный белый
        draw.rounded_rectangle([bx, by, bx + bar_w, chart_y_bottom - 30],
                                radius=bar_w // 6, fill=(255, 255, 255, 200))
        # Значение над баром
        if val:
            bbox = draw.textbbox((0, 0), str(val), font=font_value)
            tw = bbox[2] - bbox[0]
            draw.text((cx - tw//2 - bbox[0], by - 40),
                      str(val), font=font_value, fill="white")
        # Лейбл дня под баром @ y=1423
        bbox = draw.textbbox((0, 0), days[i], font=font_label)
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw//2 - bbox[0], 1423),
                  days[i], font=font_label, fill="white")
    return _to_bytes(img)


# ============================================================================
# 11 GEOGRAPHY
# ============================================================================
def render_11_geography(r: AnalysisResult) -> bytes:
    img = _open("11_geography.png")
    v = r.v2
    # Subtitle — Inter sz=50 w=400 @ (0, 314) 1080x36
    if v.total_city_mentions:
        draw_in_box(img, f"{v.total_city_mentions} упоминаний городов",
                    x=0, y=314, w=1080, h=36,
                    font_path=INTER_VAR, size=50, weight=400)

    # Cities — Inter sz=150 w=400 @ y=481, 636, 791, 946, 1101, 1256 (line_h=155)
    cities = (v.top_cities or [])[:6]
    y_positions = [481, 636, 791, 946, 1101, 1256]
    DIV_LEN = 727
    div_x_start = (img.width - DIV_LEN) // 2
    div_x_end = div_x_start + DIV_LEN
    draw = ImageDraw.Draw(img)
    # Auto-fit единый размер для всех — самая длинная строка <= 960
    target_size = 150
    while target_size > 80:
        f_test = _font(INTER_VAR, target_size, 400)
        max_w = max((draw.textbbox((0, 0), f"{c.lower()} – {n}", font=f_test)[2]
                     for c, n in cities), default=0)
        if max_w <= 960:
            break
        target_size -= 8
    for i, (city, cnt) in enumerate(cities):
        line = f"{city.lower()} – {cnt}"
        draw_in_box(img, line, x=0, y=y_positions[i], w=1080, h=109,
                    font_path=INTER_VAR, size=target_size, weight=400)
        # Divider под текстом — отступ 145 (было 130, слишком прилипал)
        div_y = y_positions[i] + 145
        draw.line([(div_x_start, div_y), (div_x_end, div_y)],
                  fill=(255, 255, 255), width=2)

    # 'сердце канала — X' — Inter ITALIC 45
    if v.heart_city:
        draw_in_box(img, f"сердце канала — {v.heart_city}",
                    x=237, y=1436, w=607, h=45,
                    font_path=INTER_ITALIC, size=45, weight=400)
    return _to_bytes(img)


# ============================================================================
# 12 TOP PHRASES
# ============================================================================
def render_12_top_phrases(r: AnalysisResult) -> bytes:
    img = _open("12_top_phrases.png")
    # 6 phrases @ y=518, 673, 828, 983, 1138, 1293 (line_h=155)
    # Inter sz=150 w=400 (так же как география)
    # TODO: брать из V2CardData.top_phrases — пока нет такого поля
    phrases: list[str] = []
    if not phrases:
        return _to_bytes(img)
    y_positions = [518, 673, 828, 983, 1138, 1293]
    DIV_LEN = 727
    div_x_start = (img.width - DIV_LEN) // 2
    div_x_end = div_x_start + DIV_LEN
    draw = ImageDraw.Draw(img)
    for i, phrase in enumerate(phrases[:6]):
        size = 150
        while size > 80:
            f_test = _font(INTER_VAR, size, 400)
            if draw.textbbox((0, 0), phrase, font=f_test)[2] <= 960:
                break
            size -= 8
        draw_in_box(img, phrase, x=0, y=y_positions[i], w=1080, h=109,
                    font_path=INTER_VAR, size=size, weight=400)
        div_y = y_positions[i] + 130
        draw.line([(div_x_start, div_y), (div_x_end, div_y)],
                  fill=(255, 255, 255), width=2)
    return _to_bytes(img)


# ============================================================================
# 13 EMOTIONS
# ============================================================================
def render_13_emotions(r: AnalysisResult) -> bytes:
    img = _open("13_emotions.png")
    v = r.v2

    # 'Драматическая' — Inter Medium 500 @ (245, 589) 589x90
    if v.emotion_palette_name:
        draw_in_box(img, v.emotion_palette_name, x=245, y=589, w=589, h=90,
                    font_path=INTER_VAR, size=75, weight=500, align="LEFT")

    # 👍 — hero. Apple Color Emoji max=160, upscale до 500
    if v.top_emoji:
        font_emoji = ImageFont.truetype(EMOJI_FONT, 160)
        emoji_canvas = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
        ed = ImageDraw.Draw(emoji_canvas)
        ed.text((30, 20), v.top_emoji, font=font_emoji, embedded_color=True)
        # Scale больше — целевой размер 500x500
        scaled = emoji_canvas.resize((500, 500), Image.Resampling.LANCZOS)
        # Центрируем на canvas 1080×1920, ниже Драматическая
        img.paste(scaled, (540 - 250, 690), scaled)

    # '1 113 раз' — Inter sz=36 w=400 центрировано
    if v.top_emoji_count:
        draw_in_box(img, f"{_format_int(v.top_emoji_count)} раз",
                    x=0, y=1130, w=1080, h=56,
                    font_path=INTER_VAR, size=36, weight=400)

    # '🙏😭😡😍' — эмодзи раздвинуты, ширина strip = ширина подписи внизу
    if v.top_emojis_strip:
        # Целевая ширина strip — как у текста-подписи ниже (Inter 36)
        from .card_data import EMOJI_TO_RU
        words = [EMOJI_TO_RU.get(e, e) for e in v.top_emojis_strip]
        caption_text = " · ".join(words)
        font_cap = ImageFont.truetype(INTER_VAR, 36)
        # Меряем ширину подписи
        d = ImageDraw.Draw(img)
        cap_bbox = d.textbbox((0, 0), caption_text, font=font_cap)
        target_w = cap_bbox[2] - cap_bbox[0]
        # Рисуем каждый эмодзи по отдельности на равных позициях
        font_em = ImageFont.truetype(EMOJI_FONT, 96)
        emojis = v.top_emojis_strip
        n = len(emojis)
        # Эмодзи каждый upscale до ~120, центрированы в равных колонках target_w
        col_w = target_w / n
        x_start = (img.width - target_w) // 2
        y_strip = 1280
        for i, em in enumerate(emojis):
            ec = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
            ed = ImageDraw.Draw(ec)
            ebbox = ed.textbbox((0, 0), em, font=font_em, embedded_color=True)
            ew = ebbox[2] - ebbox[0]
            ed.text(((220 - ew)//2 - ebbox[0], 20), em, font=font_em, embedded_color=True)
            scaled = ec.resize((140, 140), Image.Resampling.LANCZOS)
            cx = x_start + int(col_w * (i + 0.5))
            img.paste(scaled, (cx - 70, y_strip), scaled)

    # Единственный divider между «1113 раз» и блоком (emoji-strip + подпись)
    # Используем Divider.png от тебя (615×3)
    div_emoji_path = TEMPLATES / "divider_emoji.png"
    if div_emoji_path.exists():
        try:
            div_emoji = Image.open(div_emoji_path).convert("RGBA")
            x = (img.width - div_emoji.width) // 2
            img.paste(div_emoji, (x, 1230), div_emoji)
        except Exception:
            pass

    # 'мольба · слёзы · гнев · восторг' — Inter sz=36 w=400 (под emoji-strip)
    if v.top_emojis_strip:
        from .card_data import EMOJI_TO_RU
        words = [EMOJI_TO_RU.get(e, e) for e in v.top_emojis_strip]
        sub_text = " · ".join(words)
        draw_in_box(img, sub_text, x=0, y=1430, w=1080, h=56,
                    font_path=INTER_VAR, size=36, weight=400)
    return _to_bytes(img)


# ============================================================================
# 14 ONE PHRASE (LLM)
# ============================================================================
def render_14_one_phrase(r: AnalysisResult) -> bytes:
    img = _open("13_emotions.png") if not (TEMPLATES / "14_one_phrase.png").exists() else _open("14_one_phrase.png")
    v = r.v2
    # 'AI прочитал всё\nи подумал' — Inter sz=70 w=400 @ (268, 624) 545x158
    draw_in_box(img, "AI прочитал всё\nи подумал", x=268, y=624, w=545, h=158,
                font_path=INTER_VAR, size=70, weight=400)
    # Phrase — Inter sz=50 w=600 @ (170, 866) 739x337, multi-line wrap
    phrase = v.one_phrase_llm or (r.content_analysis_text or "")[:200]
    if phrase:
        # Простой wrap по словам
        draw = ImageDraw.Draw(img)
        font = _font(INTER_VAR, 50, 600)
        words = phrase.split(" ")
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip() if cur else w
            if draw.textbbox((0, 0), test, font=font)[2] <= 739:
                cur = test
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        wrapped = "\n".join(lines[:6])
        draw_in_box(img, wrapped, x=170, y=866, w=739, h=337,
                    font_path=INTER_VAR, size=50, weight=600)
    # 'сгенерировано Qwen\nна основе N постов'
    if v.total_posts:
        gen_text = f"сгенерировано LLM\nна основе {v.total_posts} постов"
        draw_in_box(img, gen_text, x=170, y=1306, w=739, h=84,
                    font_path=INTER_VAR, size=35, weight=400,
                    color=(220, 220, 230, 255))
    return _to_bytes(img)


# ============================================================================
# 15 HIT POSTS — 3 поста в РАЗНЫХ позициях из Figma
# ============================================================================
def render_15_hit_post(r: AnalysisResult) -> bytes:
    img = _open("15_hit_post.png")
    posts = (r.v2.top_posts or [])[:3]
    if not posts:
        return _to_bytes(img)
    # 3 поста на разных y-позициях (из Figma)
    POST_LAYOUTS = [
        # (react_x, react_y, text_x, text_y, text_w, text_h, date_x, date_y)
        (211, 461, 209, 558, 710, 165, 203, 725),
        (133, 839, 142, 916, 725, 264, 161, 1194),
        (301, 1300, 297, 1398, 506, 130, 295, 1541),
    ]
    for i, p in enumerate(posts):
        rx, ry, tx, ty, tw, th, dx, dy = POST_LAYOUTS[i]
        # Реакции — Inter sz=62 w=700 LEFT
        rcount = int(p.get("reactions", 0))
        draw_in_box(img, f"{rcount} реакций", x=rx, y=ry, w=484, h=88,
                    font_path=INTER_VAR, size=62, weight=700, align="LEFT")
        # Текст — Inter sz=62 (post 1) или 42 (posts 2,3) w=500
        text_size = 62 if i == 0 else 42
        text_weight = 500 if i == 0 else 400
        text = (p.get("text") or "").strip()
        draw_in_box(img, text, x=tx, y=ty, w=tw, h=th,
                    font_path=INTER_VAR, size=text_size, weight=text_weight, align="LEFT")
        # Дата — Inter sz=22 w=700 LEFT
        date = (p.get("date") or "")[:10]
        draw_in_box(img, date, x=dx, y=dy, w=177, h=46,
                    font_path=INTER_VAR, size=22, weight=700, align="LEFT",
                    color=(200, 200, 210, 255))
    return _to_bytes(img)


# ============================================================================
# 16 READING STATISTICS
# ============================================================================
def render_16_reading_statistics(r: AnalysisResult) -> bytes:
    img = _open("16_reading_statistics.png")
    v = r.v2
    # '25 ч' — NOOKS sz=290 w=700 @ (297, 624) 486x291
    if v.reading_time_hours:
        draw_centered_in_box(img, f"{v.reading_time_hours:g} ч",
                              x=297, y=624, w=486, h=291,
                              font_path=NOOKS_BOLD, size=290, weight=700,
                              auto_shrink=True, min_size=150)

    # Дивайдер между «25 ч» и «и N чашки кофе» — белая линия 727×3
    draw = ImageDraw.Draw(img)
    DIV_LEN = 727
    div_x_start = (img.width - DIV_LEN) // 2
    div_x_end = div_x_start + DIV_LEN
    draw.line([(div_x_start, 960), (div_x_end, 960)],
              fill=(255, 255, 255, 200), width=2)

    # 'и N чашки кофе...' — Inter Medium 85 @ (170, 999) 739x255
    if v.coffee_cups:
        text = f"и {v.coffee_cups} чашки кофе чтобы прочитать весь канал"
        draw = ImageDraw.Draw(img)
        font = _font(INTER_VAR, 85, 500)  # Medium
        words = text.split(" ")
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip() if cur else w
            if draw.textbbox((0, 0), test, font=font)[2] <= 739:
                cur = test
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        wrapped = "\n".join(lines)
        draw_in_box(img, wrapped, x=170, y=999, w=739, h=255,
                    font_path=INTER_VAR, size=85, weight=500)

    # Дивайдер между «кофе» и «сезона»
    draw.line([(div_x_start, 1318), (div_x_end, 1318)],
              fill=(255, 255, 255, 200), width=2)

    # 'это как N сезона сериала' — Inter Medium 47
    if v.sitcom_seasons:
        draw_in_box(img, f"это как {v.sitcom_seasons} сезона сериала",
                    x=170, y=1357, w=739, h=62,
                    font_path=INTER_VAR, size=47, weight=500)
    return _to_bytes(img)


# ============================================================================
# 17 MOST USED WORD
# ============================================================================
def render_17_most_used_word(r: AnalysisResult) -> bytes:
    img = _open("17_most_used_word.png")
    v = r.v2
    # 'ЖИЗНЬ' — NOOKS sz=283 w=700 @ (105, 779) 870x283
    if v.top_word:
        draw_centered_in_box(img, v.top_word.upper(),
                              x=105, y=779, w=870, h=283,
                              font_path=NOOKS_BOLD, size=283, weight=700,
                              auto_shrink=True, min_size=120)
    # 'упомянуто 487 раз' — Inter sz=52 w=800 @ (219, 1162) 642x28
    if v.top_word_count:
        draw_in_box(img, f"упомянуто {_format_int(v.top_word_count)} раз",
                    x=219, y=1162, w=642, h=28,
                    font_path=INTER_VAR, size=52, weight=800)
    return _to_bytes(img)


# ============================================================================
# 18 TOP PERSON
# ============================================================================
def render_18_top_person(r: AnalysisResult) -> bytes:
    """Топ-имена. Тот же принцип что география, НО:
    - Под последним именем НЕ ставим divider
    - Блок центрирован между низом заголовка (~y=540) и плашкой бота (~y=1700)
    """
    img = _open("18_top_person.png")
    v = r.v2
    city_names = {c.lower() for c, _ in v.top_cities} if v.top_cities else set()
    common_cities = {"питер", "питере", "москва", "москве", "тбилиси", "берлин",
                     "ереван", "стамбул", "париж", "лондон", "нью-йорк", "сочи",
                     "ленинград", "санкт-петербург", "минск", "киев",
                     "екатеринбург", "новосибирск", "вена", "тель-авив"}
    city_names |= common_cities
    filtered = [(n, c) for n, c in v.top_names_with_counts if n.lower() not in city_names][:6]
    if not filtered:
        return _to_bytes(img)

    draw = ImageDraw.Draw(img)
    # Auto-fit единый размер
    target_size = 150
    while target_size > 80:
        f_test = _font(INTER_VAR, target_size, 400)
        max_w = max((draw.textbbox((0, 0), f"{n.lower()} – {c}", font=f_test)[2]
                     for n, c in filtered), default=0)
        if max_w <= 960:
            break
        target_size -= 8

    # Визуальный центр блока на y=1101 (per Figma spec).
    # Используем font ascent (cap-height) для точного центрирования глифов.
    font = _font(INTER_VAR, target_size, 400)
    ascent, _ = font.getmetrics()
    line_h = int(target_size * 1.05)
    # Высота блока = ascent (для последней строки) + line_h * (N-1)
    visible_h = ascent + line_h * (len(filtered) - 1)
    BLOCK_CENTER_Y = 1101
    start_y = BLOCK_CENTER_Y - visible_h // 2

    DIV_LEN = 727
    div_x_start = (img.width - DIV_LEN) // 2
    div_x_end = div_x_start + DIV_LEN
    for i, (name, cnt) in enumerate(filtered):
        line = f"{name.lower()} – {cnt}"
        y_text = start_y + i * line_h
        draw_in_box(img, line, x=0, y=y_text, w=1080, h=target_size,
                    font_path=INTER_VAR, size=target_size, weight=400)
        # Divider — НЕ ставим под последним именем
        if i < len(filtered) - 1:
            div_y = y_text + target_size + 18
            draw.line([(div_x_start, div_y), (div_x_end, div_y)],
                      fill=(255, 255, 255), width=2)
    return _to_bytes(img)


# ============================================================================
# WORD CLOUD helper
# ============================================================================
def _generate_cloud_image(
    words_with_counts: list[tuple[str, int]],
    *, width: int = 960, height: int = 1100,
    color_hex: str = "#ffffff",
) -> Image.Image | None:
    if not words_with_counts:
        return None
    try:
        import numpy as np
        from wordcloud import WordCloud
        import math, random
        from PIL import Image as PILImage, ImageDraw as PILImageDraw

        mask_img = PILImage.new('L', (width, height), 255)
        md = PILImageDraw.Draw(mask_img)
        cx, cy = width // 2, height // 2
        rx, ry = width // 2 - 20, height // 2 - 20
        rng = random.Random(42)
        pts = []
        for i in range(80):
            angle = 2 * math.pi * i / 80
            noise = rng.uniform(-0.15, 0.15)
            x = int(cx + rx * (1 + noise) * math.cos(angle))
            y = int(cy + ry * (1 + noise) * math.sin(angle))
            pts.append((x, y))
        md.polygon(pts, fill=0)
        mask = np.array(mask_img)

        freq = {w: c for w, c in words_with_counts}
        wc = WordCloud(
            background_color=None,
            mode="RGBA",
            mask=mask,
            color_func=lambda *a, **kw: color_hex,
            max_words=120,
            min_font_size=12,
            prefer_horizontal=0.9,
            relative_scaling=0.5,
        )
        wc.generate_from_frequencies(freq)
        return wc.to_image()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"v2 wordcloud gen failed: {e}")
        return None


def _embed_cloud(img: Image.Image, words: list[tuple[str, int]], *,
                  color_hex: str = "#ffffff") -> None:
    cloud = _generate_cloud_image(words, width=960, height=1180, color_hex=color_hex)
    if cloud is None:
        return
    x = (img.width - cloud.width) // 2
    y = 460
    img.paste(cloud, (x, y), cloud)
