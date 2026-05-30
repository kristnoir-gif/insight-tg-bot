"""
Хелперы для пиксель-перфект рендера на основе точных Figma-координат.

Используется в general_cards.py. Каждое поле описывается боксом (x, y, w, h)
из Figma + точным шрифтом/размером/весом. Текст рисуется внутри бокса с
указанным выравниванием.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont
from .positions import INTER_VAR, NOOKS_BOLD


def _strip_zwj_compounds(text: str) -> str:
    """Удаляет ZWJ-compound эмодзи (типа 🏴‍☠️, 👨‍👩‍👧).
    Без libraqm PIL не склеивает их и они рендерятся как 2+ отдельных глифа.
    """
    import re
    # ZWJ — U+200D. Удаляем любую последовательность вокруг неё.
    # Pattern: emoji + ZWJ + emoji [+ ZWJ + emoji ...] + optional VS-16
    return re.sub(
        r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
        r"(?:‍[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]️?)+",
        "",
        text,
    )


def _font(path: str, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    try:
        if "Variable" in path:
            # Inter Variable: axes = [opsz, wght] — нужно передать ОБА.
            # Иначе weight уходит в opsz и Bold не работает.
            opsz = max(14, min(32, size // 30))  # 14-32 диапазон opsz
            f.set_variation_by_axes([opsz, weight])
    except Exception:
        pass
    return f


def draw_in_box(
    img: Image.Image,
    text: str,
    *,
    x: int, y: int, w: int, h: int,
    font_path: str, size: int, weight: int = 400,
    align: str = "CENTER",
    color=(255, 255, 255, 255),
    auto_shrink: bool = False,
    min_size: int = 50,
) -> None:
    """Рисует text внутри bounding box (x, y, w, h) точно как в Figma.

    align: CENTER / LEFT / RIGHT — выравнивание по горизонтали (вертикально всегда top по Figma)
    auto_shrink: уменьшать размер если ширина текста превышает w
    """
    if not text:
        return
    draw = ImageDraw.Draw(img)
    font = _font(font_path, size, weight)

    if auto_shrink:
        cur_size = size
        while cur_size > min_size:
            f_test = _font(font_path, cur_size, weight)
            tw_test = max(draw.textbbox((0, 0), ln, font=f_test)[2] for ln in text.split("\n"))
            if tw_test <= w:
                font = f_test
                size = cur_size
                break
            cur_size -= 5

    line_h = int(size * 1.0)
    for i, line in enumerate(text.split("\n")):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        if align == "CENTER":
            tx = x + (w - text_w) // 2 - bbox[0]
        elif align == "RIGHT":
            tx = x + w - text_w - bbox[0]
        else:
            tx = x - bbox[0]
        ty = y + i * line_h  # без bbox[1] чтобы совпадал с draw_text_with_emojis
        draw.text((tx, ty), line, font=font, fill=color)


def draw_text_with_emojis(
    img: Image.Image,
    text: str,
    *,
    x: int, y: int, w: int, h: int,
    font_path: str, size: int, weight: int = 400,
    align: str = "CENTER",
    color=(255, 255, 255, 255),
) -> None:
    """Рисует текст с эмодзи внутри (поддержка \\n для multi-line):
    обычные символы — Inter, эмодзи — Apple Color Emoji (embedded_color)."""
    import re
    from .positions import EMOJI_FONT
    _EMOJI_RE = re.compile(
        "["
        "\U0001F300-\U0001FAFF"
        "\U0001F600-\U0001F64F"
        "\U0001F900-\U0001F9FF"
        "\U00002600-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "♀♂⚕-⚗⚙⚠✨✊-✍"
        "️‍"
        "]+",
        flags=re.UNICODE,
    )
    draw = ImageDraw.Draw(img)
    font_text = _font(font_path, size, weight)
    emoji_supported = [160, 96, 64, 48, 40, 32]
    emoji_size = min(emoji_supported, key=lambda s: abs(s - size))
    font_emoji = ImageFont.truetype(EMOJI_FONT, emoji_size)

    # Убираем ZWJ-compound эмодзи (PIL без libraqm не склеивает их)
    # Например 🏴‍☠️ распадается на 🏴 + ☠. Лучше убрать.
    text = _strip_zwj_compounds(text)
    lines = str(text).split("\n")
    line_h = int(size * 1.05)
    for li, line in enumerate(lines):
        # Сегментация одной строки
        segments: list[tuple[str, bool]] = []
        last = 0
        for m in _EMOJI_RE.finditer(line):
            if m.start() > last:
                segments.append((line[last:m.start()], False))
            segments.append((m.group(), True))
            last = m.end()
        if last < len(line):
            segments.append((line[last:], False))
        if not segments:
            continue

        # Меряем ширину строки
        total_w = 0
        widths: list[int] = []
        for s, is_em in segments:
            font_use = font_emoji if is_em else font_text
            bbox = draw.textbbox((0, 0), s, font=font_use,
                                  embedded_color=is_em)
            sw = bbox[2] - bbox[0]
            widths.append(sw)
            total_w += sw

        # X offset
        if align == "CENTER":
            cur_x = x + (w - total_w) // 2
        elif align == "RIGHT":
            cur_x = x + w - total_w
        else:
            cur_x = x

        cur_y = y + li * line_h
        for (s, is_em), sw in zip(segments, widths):
            if is_em:
                emoji_y_offset = (size - emoji_size) // 2
                draw.text((cur_x, cur_y + emoji_y_offset), s, font=font_emoji,
                          embedded_color=True)
            else:
                draw.text((cur_x, cur_y), s, font=font_text, fill=color)
            cur_x += sw


def draw_centered_in_box(
    img: Image.Image,
    text: str,
    *,
    x: int, y: int, w: int, h: int,
    font_path: str, size: int, weight: int = 400,
    color=(255, 255, 255, 255),
    auto_shrink: bool = False,
    min_size: int = 50,
) -> None:
    """Рисует text по ЦЕНТРУ бокса (x, y, w, h) — и по горизонтали, и по вертикали."""
    if not text:
        return
    draw = ImageDraw.Draw(img)
    font = _font(font_path, size, weight)

    if auto_shrink:
        cur_size = size
        while cur_size > min_size:
            f_test = _font(font_path, cur_size, weight)
            tw_test = max(draw.textbbox((0, 0), ln, font=f_test)[2] for ln in text.split("\n"))
            if tw_test <= w:
                font = f_test
                size = cur_size
                break
            cur_size -= 5

    lines = text.split("\n")
    line_h = int(size * 1.05)
    total_h = line_h * len(lines)
    start_y = y + (h - total_h) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tx = x + (w - text_w) // 2 - bbox[0]
        ty = start_y + i * line_h - bbox[1] // 2
        draw.text((tx, ty), line, font=font, fill=color)
