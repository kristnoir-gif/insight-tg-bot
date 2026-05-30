"""
Спец-карточки которые не подходят под чисто HTML-шаблон + PIL-overlay:
- 02 main_themes  — pill-список тем
- 03 chanal_in_numbers — pill-список фактов
- 15 hit_post — 3 текстовых блока с топ-постами

Word cloud (07/09) и weekday chart (08) генерируются legacy-функциями и
просто переиспользуются как готовые PNG.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from analyzer import AnalysisResult
from .hybrid import bake_template, _baked_path
from .pills import draw_channel_subtitle, layout_pills_cascade, draw_pill, _font
from .positions import NOOKS_BOLD, INTER_VAR
from .card_data import _format_int


def render_main_themes(r: AnalysisResult) -> bytes:
    """02 — список тем (5-12) в pill'ах каскадом."""
    bake_template("02_main_themes")
    img = Image.open(_baked_path("02_main_themes")).convert("RGB")
    # Channel name под заголовком
    draw_channel_subtitle(img, r.title or "канал", y=400, base_size=50, weight=400, max_w=950)
    # Pill-темы
    topics = list(r.topics or [])[:12]
    if topics:
        layout_pills_cascade(img, topics, center_x=540, top_y=720,
                             font_size=58, max_width=950)
    return _to_bytes(img)


def render_chanal_in_numbers(r: AnalysisResult) -> bytes:
    """03 — название канала + 6 fact-pill'ов."""
    bake_template("03_chanal_in_numbers")
    img = Image.open(_baked_path("03_chanal_in_numbers")).convert("RGB")
    # Большое название канала (TT Nooks)
    draw_channel_subtitle(img, r.title or "канал", y=173,
                          base_size=110, weight=700, font_path=NOOKS_BOLD, max_w=950)
    # Pills
    v = r.v2
    facts: list[str] = []
    if v.total_chars:           facts.append(f"{_format_int(v.total_chars)} символов написано")
    if v.max_consecutive_days:  facts.append(f"рекорд {v.max_consecutive_days} дней подряд")
    if v.total_words:           facts.append(f"{_format_int(v.total_words)} слов")
    if v.total_reactions:       facts.append(f"{_format_int(v.total_reactions)} реакций")
    if v.total_photos:          facts.append(f"{_format_int(v.total_photos)} фото")
    if v.years_covered:         facts.append(f"{v.years_covered} лет")
    if facts:
        layout_pills_cascade(img, facts, center_x=540, top_y=720,
                             font_size=52, max_width=960)
    return _to_bytes(img)


def render_hit_post(r: AnalysisResult) -> bytes:
    """15 — 3 топ-поста с реакциями и датами."""
    bake_template("15_hit_post")
    img = Image.open(_baked_path("15_hit_post")).convert("RGB")
    posts = (r.v2.top_posts or [])[:3]
    if not posts:
        return _to_bytes(img)

    # Каждый пост — в box'е: дата + реакции сверху, текст ниже
    draw = ImageDraw.Draw(img)
    font_text = _font(38, 400)
    font_meta = _font(34, 700)

    box_y_start = 600
    box_h = 380
    box_gap = 30
    box_w = 950
    box_x = (img.width - box_w) // 2

    for i, p in enumerate(posts):
        y = box_y_start + i * (box_h + box_gap)
        # Полупрозрачная подложка
        from PIL import ImageDraw as _ID
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = _ID.Draw(overlay)
        od.rounded_rectangle([box_x, y, box_x + box_w, y + box_h],
                              radius=40, fill=(255, 255, 255, 40),
                              outline=(255, 255, 255, 100), width=2)
        rgba = img.convert("RGBA")
        img.paste(Image.alpha_composite(rgba, overlay).convert("RGB"))
        draw = ImageDraw.Draw(img)

        # Реакции (сверху слева)
        rcount = int(p.get("reactions", 0))
        meta = f"{rcount} реакций"
        draw.text((box_x + 36, y + 28), meta, font=font_meta, fill="white")

        # Дата (сверху справа)
        date = (p.get("date") or "")[:10]
        bbox = draw.textbbox((0, 0), date, font=font_meta)
        date_w = bbox[2] - bbox[0]
        draw.text((box_x + box_w - 36 - date_w, y + 28),
                  date, font=font_meta, fill=(200, 200, 200, 255))

        # Текст поста (с переносом, до 6 строк)
        text = (p.get("text") or "").strip()
        lines = _wrap_to_box(draw, text, font_text, box_w - 72)[:6]
        ty = y + 100
        for line in lines:
            draw.text((box_x + 36, ty), line, font=font_text, fill="white")
            ty += int(38 * 1.25)

    return _to_bytes(img)


def _wrap_to_box(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    out: list[str] = []
    for raw in text.split("\n"):
        if not raw: continue
        words = raw.split(" ")
        cur = ""
        for w in words:
            test = (cur + " " + w).strip() if cur else w
            if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
                cur = test
            else:
                if cur: out.append(cur)
                cur = w
        if cur: out.append(cur)
    return out


def _to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def save(img_bytes: bytes, path: Path) -> Path:
    path.write_bytes(img_bytes)
    return path
