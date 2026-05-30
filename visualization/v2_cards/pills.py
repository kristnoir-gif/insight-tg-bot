"""
Glassmorphism pill-капсулы через PIL.

Используется для карточек у которых динамическое содержимое — список текстов,
расставленных каскадом: 02 главные темы, 03 канал в цифрах.

Каждая капсула это закруглённый прямоугольник с полупрозрачным белым фоном,
тонкой обводкой, и белым текстом по центру.
"""
from __future__ import annotations

from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

import re

from .positions import INTER_VAR, EMOJI_FONT


# Простой regex для эмодзи. Не идеально, но покрывает основные кодпоинты.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols & pictographs (extended)
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # flags (regional indicators)
    "♀♂⚕-⚗⚙⚠✨✊-✍"
    "️"                 # variation selector
    "‍"                 # zero-width joiner
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(s: str) -> str:
    """Удаляет эмодзи из строки (для PIL рендера если шрифт без эмодзи-глифов)."""
    return _EMOJI_RE.sub("", s).strip()


def _font(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(INTER_VAR, size)
    try:
        if "Variable" in INTER_VAR:
            opsz = max(14, min(32, size // 30))
            f.set_variation_by_axes([opsz, weight])
    except Exception:
        pass
    return f


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _make_gradient_stroke(w: int, h: int, radius: int, width: int = 3) -> Image.Image:
    """Создаёт RGBA-изображение с pill-обводкой по диагональному градиенту
    (top-left светло-розовый → bottom-right фиолетовый), как в Figma-дизайне.
    """
    # 1) Маска: только pill-обводка
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius,
                          outline=255, width=width)

    # 2) Градиентный fill по диагонали (linear approximation of radial)
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    # цвета: EABFFF (RGB 234,191,255) → 8726B7 (RGB 135,38,183)
    c1 = (234, 191, 255, 255)
    c2 = (135, 38, 183, 255)
    diag = (w + h) or 1
    for i in range(diag):
        t = i / diag
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        # Полоска под углом 45°: точка (x, i-x)
        gd.line([(i, 0), (0, i)], fill=(r, g, b, 255))

    # 3) Композ: gradient через маску
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def draw_pill(
    img: Image.Image,
    text: str,
    cx: int, cy: int,
    *,
    font_size: int = 60,
    weight: int = 700,        # bold по дизайну
    padding_x: int = 48,
    padding_y: int = 25,
    fill_alpha: int = 30,     # тёмное стекло слегка прозрачное
    stroke_width: int = 3,
    text_color: tuple = (255, 255, 255, 255),
) -> tuple[int, int]:
    """Рисует pill с glassmorphism-заливкой и градиентной обводкой
    (по спеке из Figma — light-pink → purple stroke, translucent fill).

    cx, cy — центр капсулы. Возвращает (width, height) капсулы.
    """
    from PIL import ImageFilter

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    font = _font(font_size, weight)
    text_w, _ = _measure(od, text, font)
    # Высота pill — фиксированная через font metrics (одинаковая для всех pill),
    # текст центрируется внутри визуально через anchor='mm' (см. ниже).
    ascent, descent = font.getmetrics()
    pill_w = text_w + 2 * padding_x
    pill_h = ascent + descent + 2 * padding_y
    radius = pill_h // 2

    x0 = cx - pill_w // 2
    y0 = cy - pill_h // 2

    # 1) Frosted glass: размытие BG внутри pill-маски
    pill_mask = Image.new("L", img.size, 0)
    pm_draw = ImageDraw.Draw(pill_mask)
    pm_draw.rounded_rectangle(
        [x0, y0, x0 + pill_w, y0 + pill_h], radius=radius, fill=255,
    )
    # Размываем копию BG и paste обратно через маску
    blurred_bg = img.filter(ImageFilter.GaussianBlur(radius=18))
    img.paste(blurred_bg, (0, 0), pill_mask)

    # 2) Полупрозрачная заливка поверх размытия
    od.rounded_rectangle(
        [x0, y0, x0 + pill_w, y0 + pill_h],
        radius=radius,
        fill=(255, 255, 255, fill_alpha),
    )

    # 3) Градиентная обводка
    stroke = _make_gradient_stroke(pill_w, pill_h, radius, stroke_width)
    overlay.paste(stroke, (x0, y0), stroke)

    # 4) Текст — anchor='mm' центрирует визуально (middle ascender↔descender в cy).
    # Это даёт правильное вертикальное положение для текстов и с descender'ами и без.
    od.text((cx, cy), text, font=font, fill=text_color, anchor="mm")

    # Композ overlay
    if img.mode != "RGBA":
        rgba = img.convert("RGBA")
        rgba = Image.alpha_composite(rgba, overlay)
        img.paste(rgba.convert("RGB"))
    else:
        composed = Image.alpha_composite(img, overlay)
        img.paste(composed)
    return pill_w, pill_h


def draw_channel_subtitle(
    img: Image.Image,
    title: str,
    *,
    y: int,
    max_w: int = 920,
    base_size: int = 50,
    weight: int = 400,
    color: tuple = (255, 255, 255, 240),
    line_gap: int = 4,
    font_path: str = INTER_VAR,
) -> None:
    """Рисует название канала под заголовком карточки.

    Логика:
    - Многословное название → перенос по словам на 2 строки если шире max_w
    - Однословное и длинное → уменьшает шрифт пропорционально, чтобы влезло
    - Всё центрируется на 1080-px холсте.
    """
    if not title:
        return
    # Эмодзи в названиях канала не рендерятся (Inter без эмодзи-глифов на проде),
    # поэтому чистим. Спец-кейс: если только эмодзи остались — оставляем «канал».
    title = _strip_emoji(title.strip())
    if not title:
        title = "канал"
    draw = ImageDraw.Draw(img)

    def _make(s: int) -> ImageFont.FreeTypeFont:
        f = ImageFont.truetype(font_path, s)
        try:
            if "Variable" in font_path:
                opsz = max(14, min(32, size // 30))
                f.set_variation_by_axes([opsz, weight])
        except Exception:
            pass
        return f

    # Подбор размера шрифта: если 1 слово длиннее max_w — уменьшаем
    size = base_size
    font = _make(size)
    bbox = draw.textbbox((0, 0), title, font=font)
    text_w = bbox[2] - bbox[0]
    has_space = " " in title

    if text_w > max_w and not has_space:
        # Однословное, не помещается — масштабируем размер
        scale = max_w / text_w
        size = max(int(base_size * scale * 0.95), 24)
        font = _make(size)
        bbox = draw.textbbox((0, 0), title, font=font)
        lines = [title]
    elif text_w > max_w and has_space:
        # Многословное — переносим на 2 строки на пробеле
        words = title.split(" ")
        # Подберём точку разрыва, при которой обе строки максимально равны и помещаются
        best_split = len(words) // 2
        for i in range(1, len(words)):
            l1 = " ".join(words[:i])
            l2 = " ".join(words[i:])
            w1 = draw.textbbox((0, 0), l1, font=font)[2]
            w2 = draw.textbbox((0, 0), l2, font=font)[2]
            if w1 <= max_w and w2 <= max_w:
                best_split = i
                break
        lines = [" ".join(words[:best_split]), " ".join(words[best_split:])]
    else:
        lines = [title]

    line_h = int(size * 1.1)
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        cx = img.width // 2
        x = cx - tw // 2 - bbox[0]
        ly = y + i * line_h
        draw.text((x, ly), line, fill=color, font=font)


def layout_pills_cascade(
    img: Image.Image,
    texts: Sequence[str],
    *,
    center_x: int = 540,
    top_y: int | None = None,
    center_y: int | None = None,
    gap_x: int = 24,
    gap_y: int = 28,
    font_size: int = 60,
    weight: int = 600,
    max_width: int = 920,
    auto_shrink: bool = False,
    min_font_size: int = 30,
) -> None:
    """Раскладывает pills каскадом из строк разной длины (как «слова в сердце»).

    Алгоритм: переходит к следующей строке когда суммарная ширина превышает max_width.
    Все строки центрированы относительно center_x.

    Если auto_shrink=True — font_size уменьшается до тех пор, пока КАЖДАЯ pill
    не помещается в max_width (для соблюдения минимальных боковых отступов).
    """
    if not texts:
        return
    od = ImageDraw.Draw(img)
    padding_x = 36

    # Auto-shrink: подбираем font_size так чтобы самый широкий pill влезал в max_width
    if auto_shrink:
        while font_size > min_font_size:
            f_test = _font(font_size, weight)
            max_pill_w = max(_measure(od, t, f_test)[0] + 2 * padding_x for t in texts)
            if max_pill_w <= max_width:
                break
            font_size -= 2
    font = _font(font_size, weight)

    # Группируем pill'ы в строки по доступной ширине
    rows: list[list[tuple[str, int]]] = []
    cur_row: list[tuple[str, int]] = []
    cur_width = 0
    for t in texts:
        text_w, _ = _measure(od, t, font)
        pill_w = text_w + 2 * padding_x
        proposed = cur_width + (gap_x if cur_row else 0) + pill_w
        if proposed > max_width and cur_row:
            rows.append(cur_row)
            cur_row = [(t, pill_w)]
            cur_width = pill_w
        else:
            cur_row.append((t, pill_w))
            cur_width = proposed
    if cur_row:
        rows.append(cur_row)

    # Высота всех pill из font metrics — одинаковая
    ascent, descent = font.getmetrics()
    text_h = ascent + descent
    pill_h = text_h + 50  # padding_y * 2

    # Если задан center_y — вычисляем top_y чтобы блок был центрирован
    total_h = len(rows) * pill_h + max(0, len(rows) - 1) * gap_y
    if center_y is not None:
        y = center_y - total_h // 2
    elif top_y is not None:
        y = top_y
    else:
        y = 700  # default fallback

    for row in rows:
        total_w = sum(pw for _, pw in row) + gap_x * (len(row) - 1)
        x = center_x - total_w // 2
        for text, pw in row:
            cx = x + pw // 2
            cy = y + pill_h // 2
            draw_pill(img, text, cx, cy,
                      font_size=font_size, weight=weight,
                      padding_x=padding_x)
            x += pw + gap_x
        y += pill_h + gap_y
