"""
render_available_cards(result) — рендерит каждую карточку v2 для которой
есть готовый HTML-шаблон, возвращает список путей к PNG.

По мере того как мы добавляем шаблоны в `templates/`, эта функция автоматически
начинает их подхватывать. Используется в handlers/user.py когда у юзера
включён бета-дизайн.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from analyzer import AnalysisResult
from .hybrid import render_card_to_file, bake_template
from .renderer import TEMPLATES_DIR
from .card_data import CARDS
from .positions import CARD_FIELDS

OUT_DIR = Path(__file__).parent / "_out"


def render_available_cards(
    result: AnalysisResult,
    channel_key: str,
    *,
    out_dir: Path | None = None,
) -> list[Path]:
    """Рендерит все карточки v2 для которых есть шаблон. Возвращает PNG-пути в нужном порядке."""
    out_dir = (out_dir or OUT_DIR) / channel_key
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    # Рендерим только те карты, у которых ЕСТЬ И HTML-шаблон, И позиции
    # динамических полей (positions.py).
    for name, builder in CARDS.items():
        tpl_path = TEMPLATES_DIR / f"{name}.html"
        if not tpl_path.exists() or name not in CARD_FIELDS:
            continue
        try:
            # Bake pre-rendered шаблон, если ещё нет
            bake_template(name)
            data = builder(result)
            out_path = out_dir / f"{name}.png"
            render_card_to_file(name, data, out_path)
            paths.append(out_path)
        except Exception as e:  # noqa: BLE001 — карточка не должна валить весь анализ
            import logging
            logging.getLogger(__name__).warning(
                "v2 card render failed: %s — %s", name, e
            )
    return paths


__all__ = ["render_available_cards"]
