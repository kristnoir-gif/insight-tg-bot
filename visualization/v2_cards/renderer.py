"""
Рендерит HTML-шаблоны карточек v2 в PNG 1080x1920 через Playwright (Chromium).

Шаблоны лежат в templates/, формат — простой str.format() с {{placeholders}}.
Для подстановки используем {{ name }} (двойные фигурные) — это снаружи безопаснее
относительно CSS, который содержит одинарные { }.

Использование:
    from visualization.v2_cards.renderer import render_card
    png_bytes = render_card("01_cover", {
        "recap_label": "TELEGRAM RECAP",
        "channel_title": "новый положняк",
        "years": "2017–2026",
        "hero_number": "18,5К",
        "hero_caption": "постов за все время",
        "subtitle": "по 5.6 в день · каждый день",
        "bot_username": "insight_tg_bot",
    })
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from playwright.sync_api import sync_playwright

TEMPLATES_DIR = Path(__file__).parent / "templates"
CARD_W, CARD_H = 1080, 1920


def render_card(template_name: str, data: Mapping[str, object]) -> bytes:
    """Рендерит карточку и возвращает PNG-байты."""
    tpl_path = TEMPLATES_DIR / f"{template_name}.html"
    html = tpl_path.read_text(encoding="utf-8")
    html = _substitute(html, data)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": CARD_W, "height": CARD_H},
                                  device_scale_factor=1)
        page = ctx.new_page()
        # Open the template URL first so relative paths (CSS, fonts) resolve,
        # then overwrite content while keeping the base URL.
        page.goto(tpl_path.as_uri())
        page.set_content(html, wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        png = page.screenshot(full_page=False, omit_background=False, type="png")
        browser.close()
        return png


def render_card_to_file(template_name: str, data: Mapping[str, object], out_path: Path) -> Path:
    out_path.write_bytes(render_card(template_name, data))
    return out_path


def _substitute(html: str, data: Mapping[str, object]) -> str:
    # Заменяем {{ key }} на значение из data, html-экранируя.
    def repl(m: re.Match) -> str:
        key = m.group(1).strip()
        if key not in data:
            return m.group(0)  # оставляем как есть, чтоб видно было что не заполнено
        return _esc(str(data[key]))
    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", repl, html)


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


if __name__ == "__main__":
    # Быстрая проверка из CLI: рендерит обложку с дефолтными данными в preview.png
    out = TEMPLATES_DIR.parent / "preview_01_cover.png"
    render_card_to_file("01_cover", {
        "recap_label": "TELEGRAM RECAP",
        "channel_title": "новый положняк",
        "years": "2017–2026",
        "hero_number": "18,5К",
        "hero_caption": "постов за все время",
        "subtitle": "по 5.6 в день · каждый день",
        "bot_username": "insight_tg_bot",
    }, out)
    print(f"Saved → {out}")
