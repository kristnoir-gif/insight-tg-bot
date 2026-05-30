"""
Гибридный рендер карточек: Playwright pre-bake (один раз) + PIL per-render.

Шаг 1 (bake): HTML с зашитым статичным текстом и пустыми динамическими полями
рендерится Playwright'ом в `_templates_clean/<name>.png`. Делается один раз
при старте бота или вручную (см. main()).

Шаг 2 (render): PIL открывает pre-baked PNG, рисует динамические поля поверх
по координатам из positions.py. ~200ms на карточку.

Если pre-baked PNG отсутствует — bake выполняется лениво при первом запросе.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

from .positions import CARD_FIELDS, TextField

logger = logging.getLogger(__name__)

CARD_W, CARD_H = 1080, 1920
TEMPLATES_DIR = Path(__file__).parent / "templates"
BAKED_DIR = Path(__file__).parent / "_templates_clean"
BAKED_DIR.mkdir(parents=True, exist_ok=True)


def _baked_path(card_name: str) -> Path:
    return BAKED_DIR / f"{card_name}.png"


def bake_template(card_name: str, force: bool = False) -> Path:
    """Рендерит чистый HTML-шаблон в PNG через Playwright. Один раз на карточку."""
    out = _baked_path(card_name)
    if out.exists() and not force:
        return out
    tpl = TEMPLATES_DIR / f"{card_name}.html"
    if not tpl.exists():
        raise FileNotFoundError(f"HTML template not found: {tpl}")

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": CARD_W, "height": CARD_H}, device_scale_factor=1)
        page = ctx.new_page()
        page.goto(tpl.as_uri(), wait_until="load")
        # Дожидаемся загрузки шрифтов вместо networkidle (он зависает)
        page.evaluate("() => document.fonts.ready")
        page.screenshot(path=str(out))
        b.close()
    logger.info("baked %s → %s", card_name, out)
    return out


def bake_all(force: bool = False) -> list[Path]:
    """Пробегает по всем картам с зарегистрированными полями и pre-bake'ит каждую."""
    paths: list[Path] = []
    for name in CARD_FIELDS.keys():
        try:
            paths.append(bake_template(name, force=force))
        except FileNotFoundError as e:
            logger.warning(str(e))
    return paths


# Variable-fonts: для Inter указываем weight через variation_axes
def _load_font(path: str, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    try:
        if "Variable" in path or "VF" in path:
            opsz = max(14, min(32, size // 30))
            f.set_variation_by_axes([opsz, weight])
    except Exception:  # noqa: BLE001
        # Не-вариативный шрифт или PIL не поддерживает — игнорируем
        pass
    return f


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Простой перенос по словам если строка шире max_w."""
    out: list[str] = []
    for raw in text.split("\n"):
        if not raw:
            out.append(raw)
            continue
        words = raw.split(" ")
        cur = ""
        for w in words:
            test = (cur + " " + w).strip() if cur else w
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_w:
                cur = test
            else:
                if cur:
                    out.append(cur)
                cur = w
        if cur:
            out.append(cur)
    return out


def _draw_field(draw: ImageDraw.ImageDraw, field: TextField, value: str) -> None:
    if not value:
        return
    font = _load_font(field.font, field.size, field.weight)
    line_h = int(field.size * 1.05)
    kwargs = {"font": font}
    if field.emoji:
        kwargs["embedded_color"] = True
    else:
        kwargs["fill"] = field.color

    # Ауто-перенос длинных строк (только для не-эмодзи)
    if field.emoji:
        lines = str(value).split("\n")
    else:
        lines = _wrap_lines(draw, str(value), font, field.w)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font, embedded_color=field.emoji)
        text_w = bbox[2] - bbox[0]
        if field.align == "center":
            x = field.x + (field.w - text_w) / 2 - bbox[0]
        elif field.align == "right":
            x = field.x + field.w - text_w - bbox[0]
        else:
            x = field.x - bbox[0]
        y = field.y + i * line_h
        draw.text((x, y), line, **kwargs)


def render_card(card_name: str, data: Mapping[str, object]) -> bytes:
    """Открывает pre-baked PNG, рисует поля поверх, возвращает PNG-байты."""
    fields = CARD_FIELDS.get(card_name)
    if fields is None:
        raise ValueError(f"No fields registered for {card_name} in positions.py")
    base = _baked_path(card_name)
    if not base.exists():
        bake_template(card_name)
    img = Image.open(base).convert("RGB")
    draw = ImageDraw.Draw(img)
    for f in fields:
        v = data.get(f.data_key, "")
        if v != "":
            _draw_field(draw, f, str(v))
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_card_to_file(card_name: str, data: Mapping[str, object], out_path: Path) -> Path:
    out_path.write_bytes(render_card(card_name, data))
    return out_path


if __name__ == "__main__":
    import sys
    if "--bake" in sys.argv:
        for p in bake_all(force="--force" in sys.argv):
            print("  baked:", p)
    else:
        # Демо: pre-bake (если нужно) + рендер обложки
        from analyzer import AnalysisResult, V2CardData
        from .card_data import CARDS
        r = AnalysisResult(title="новый положняк", v2=V2CardData(
            total_posts=18500, total_chars=1_800_000,
            start_date="2017-01-01", end_date="2026-05-21",
            posts_per_day_avg=5.6,
        ))
        out = Path(__file__).parent / "preview_01_cover_HYBRID.png"
        render_card_to_file("01_cover", CARDS["01_cover"](r), out)
        print("saved →", out)
