"""
Рендер архетип-карточек: PIL поверх чистого PNG из assets/figma/variants_clean/.

API:
    render_chronotype_card(peak_hour, peak_share, total_posts, hour_counts) -> bytes
    render_vocab_card(unique_count) -> bytes
    render_toxicity_card(mat_percent, posts_with_mat_percent) -> bytes
    render_jungian_card(archetype_name) -> bytes

Координаты текстовых полей — из исходных Figma-фреймов
(cards_structure.json), пиксели на canvas 1080×1920.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .positions import INTER_VAR, NOOKS_BOLD
from .variants import (
    ArchetypeVariant,
    pick_chronotype, pick_vocab, pick_toxicity, find_jungian,
    JUNGIAN_WITH_PCT, CHRONOTYPE_VARIANTS,
)

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "assets" / "figma" / "variants_clean"


def _load_template(filename: str) -> Image.Image:
    path = TEMPLATES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing template: {path}")
    return Image.open(path).convert("RGB")


def _font(path: str, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    try:
        if "Variable" in path:
            opsz = max(14, min(32, size // 30))
            f.set_variation_by_axes([opsz, weight])
    except Exception:
        pass
    return f


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Перенос по словам если строка шире max_w."""
    out: list[str] = []
    for raw in text.split("\n"):
        if not raw:
            out.append(raw); continue
        cur = ""
        for w in raw.split(" "):
            test = (cur + " " + w).strip() if cur else w
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_w:
                cur = test
            else:
                if cur: out.append(cur)
                cur = w
        if cur: out.append(cur)
    return out


def _draw_centered(img: Image.Image, text: str, *, y: int, x: int = 0, w: int | None = None,
                   font_path: str = INTER_VAR, size: int = 50, weight: int = 400,
                   color: str = "white", wrap: bool = True) -> None:
    """Рисует text по центру горизонтально (внутри прямоугольника x..x+w) на высоте y."""
    if not text:
        return
    if w is None:
        w = img.width - x
    draw = ImageDraw.Draw(img)
    font = _font(font_path, size, weight)
    line_h = int(size * 1.15)
    lines = _wrap(draw, str(text), font, w) if wrap else str(text).split("\n")
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        px = x + (w - text_w) / 2 - bbox[0]
        py = y + i * line_h
        draw.text((px, py), line, fill=color, font=font)


def _tod_phrase(variant_name: str) -> str:
    """Время суток по имени хронотип-варианта."""
    return {
        "wolf":     "вечером",        # 21-23
        "owl":      "ночью",          # 00-02
        "lunatik":  "ночью",          # 03-05
        "lark":     "утром",          # 06-08
        "tit":      "утром",          # 09-11
        "squirrel": "в полдень",      # 12-14
        "cat":      "днём",           # 15-17
        "fox":      "вечером",        # 18-20
        "chrono_chaos": "размазанно",
    }.get(variant_name, "")


def render_chronotype_card(
    peak_hour: int,
    peak_share: float,
    total_posts: int = 0,
    hour_counts: dict | None = None,
) -> bytes:
    """Хронотип: «пик активности HH:00» + divider + «N% твоих постов написано <время>»."""
    variant = pick_chronotype(peak_hour, total_posts, hour_counts)
    img = _load_template(variant.png_file)

    if variant.name == "chrono_chaos":
        return _to_bytes(img)

    # «пик активности 04:00» — Inter SemiBold (600), размер 66
    peak_text = f"пик активности {peak_hour:02d}:00"
    _draw_centered(img, peak_text, y=1370, x=0, w=1080,
                   font_path=INTER_VAR, size=66, weight=600)

    # Дивайдер между «пик активности» и «N% твоих постов»
    from pathlib import Path
    divider_path = Path(__file__).parent.parent.parent / "assets" / "figma" / "variants_clean" / "divider_chronotype.png"
    # Дивайдер ровно по центру между «пик» (y=1370 h=66 → bottom=1436)
    # и «N% твоих» (y=1490). Центр = (1436+1490)/2 = 1463
    if divider_path.exists():
        try:
            divider = Image.open(divider_path).convert("RGBA")
            x = (img.width - divider.width) // 2
            img.paste(divider, (x, 1463 - divider.height // 2), divider)
        except Exception:
            pass

    # «N% твоих постов написано <время>» — Inter Medium 36
    pct = int(peak_share) if peak_share > 0 else 83
    share_text = f"{pct}% твоих постов написано {_tod_phrase(variant.name)}"
    _draw_centered(img, share_text, y=1490, x=0, w=1080,
                   font_path=INTER_VAR, size=36, weight=500, color="#dddddd")
    return _to_bytes(img)


def render_vocab_card(unique_count: int) -> bytes:
    """Vocab: только большое число посередине."""
    variant = pick_vocab(unique_count)
    img = _load_template(variant.png_file)

    # Число + «уникальных слов» в одну строку, прямо над «норма 5-8 тысяч»
    formatted = f"{unique_count:,}".replace(",", " ")
    full_line = f"{formatted} уникальных слов"
    _draw_centered(img, full_line, y=1465, x=0, w=1080,
                   font_path=INTER_VAR, size=70, weight=600)
    return _to_bytes(img)


def render_toxicity_card(mat_percent: float, posts_with_mat_percent: float) -> bytes:
    """Toxicity: двухстрочный «мат N% / N% постов с матом»."""
    variant = pick_toxicity(mat_percent)
    img = _load_template(variant.png_file)

    if variant.name in ("angel", "light"):
        # На этих PNG описание уже статично («в канале рога и копыта, нет мата»)
        return _to_bytes(img)

    # Inter SemiBold 600 sz=65 (proportions из Figma)
    stat = f"мат {mat_percent:.1f}% от всего текста\n{int(posts_with_mat_percent)}% постов с матом"
    _draw_centered(img, stat, y=1430, x=0, w=1080,
                   font_path=INTER_VAR, size=65, weight=600)  # SemiBold
    return _to_bytes(img)


def render_jungian_card(archetype_name: str, *, sage_pct: float = 0.0, outlaw_pct: float = 0.0) -> bytes:
    """Юнгианский архетип. Для Мудреца и Бунтаря дорисовываем описание с %."""
    variant = find_jungian(archetype_name)
    if variant is None:
        raise ValueError(f"Unknown jungian archetype: {archetype_name!r}")
    img = _load_template(variant.png_file)

    if variant.name in JUNGIAN_WITH_PCT:
        pct = sage_pct if variant.name == "sage" else outlaw_pct
        if pct > 0:
            desc = JUNGIAN_WITH_PCT[variant.name].format(pct=int(pct))
            # Меньший размер + центрированное расположение — текст не выходит за края
            _draw_centered(img, desc, y=1420, x=80, w=920,
                           font_path=INTER_VAR, size=38, weight=600)
    return _to_bytes(img)


def _to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_variant_to_file(category: str, out_path: Path, **kwargs) -> Path:
    """Удобная обёртка: 'chronotype'/'vocab'/'toxicity'/'jungian' → PNG file."""
    if category == "chronotype":
        data = render_chronotype_card(**kwargs)
    elif category == "vocab":
        data = render_vocab_card(**kwargs)
    elif category == "toxicity":
        data = render_toxicity_card(**kwargs)
    elif category == "jungian":
        data = render_jungian_card(**kwargs)
    else:
        raise ValueError(f"Unknown category: {category}")
    out_path.write_bytes(data)
    return out_path
