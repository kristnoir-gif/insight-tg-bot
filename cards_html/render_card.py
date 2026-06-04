#!/usr/bin/env python3
"""Рендер HTML-карточки через Playwright + сборка сравнения с эталоном.

Usage: python3 render_card.py geography
  - рендерит cards_html/<name>.html в 1080x1920 -> out/<name>.png
  - если есть эталон my_peerfect_card/<ref>.jpg — делает:
      out/<name>_cmp.png     (рендер | эталон, рядом)
      out/<name>_overlay.png (рендер поверх эталона, 50%)
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
HTML_DIR = ROOT / "cards_html"
OUT = HTML_DIR / "out"
OUT.mkdir(exist_ok=True)
REF_DIR = ROOT / "my_peerfect_card"

# карта: имя html -> имя эталонного jpg (без расширения)
REF_MAP = {"geography": "geography"}


def render(name: str) -> Path:
    html = HTML_DIR / f"{name}.html"
    assert html.exists(), f"нет {html}"
    out = OUT / f"{name}.png"
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto(html.as_uri())
        page.wait_for_timeout(300)  # дождаться шрифтов
        page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": 1080, "height": 1920})
        b.close()
    return out


def compare(name: str, rendered: Path):
    ref_name = REF_MAP.get(name)
    if not ref_name:
        return
    ref = REF_DIR / f"{ref_name}.jpg"
    if not ref.exists():
        print("нет эталона", ref); return
    r = Image.open(rendered).convert("RGB")
    e = Image.open(ref).convert("RGB").resize((1080, 1920))
    # side-by-side
    cmp = Image.new("RGB", (2160, 1920), "black")
    cmp.paste(r, (0, 0)); cmp.paste(e, (1080, 0))
    cmp.save(OUT / f"{name}_cmp.png")
    # overlay 50%
    Image.blend(e, r, 0.5).save(OUT / f"{name}_overlay.png")
    print("saved cmp + overlay")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "geography"
    out = render(name)
    print("rendered", out)
    compare(name, out)
