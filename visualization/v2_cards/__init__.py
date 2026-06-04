# КАНОНИЧЕСКИЙ рендер v2-галереи теперь в cards_html/render_gallery.py
# (HTML/CSS-карточки по точной Figma-спеке). Старый gallery.py/hybrid/renderer —
# legacy (Фаза 2: удалить). Сигнатура render_full_v2_gallery(result, channel_key)
# сохранена → handlers/user.py не меняется.
import sys as _sys
from pathlib import Path as _Path

_CARDS_HTML = _Path(__file__).resolve().parents[2] / "cards_html"
if str(_CARDS_HTML) not in _sys.path:
    _sys.path.insert(0, str(_CARDS_HTML))
from render_gallery import render_full_v2_gallery  # noqa: E402

__all__ = ["render_full_v2_gallery"]
