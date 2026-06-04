#!/usr/bin/env python3
"""Из figma_slots_raw/*.json — компактная карта текстовых слотов по карточкам.

Для каждой карточки печатает TEXT-ноды: локальные координаты (от фрейма),
шрифт (family/weight/size/lineHeight/letterSpacing/case/italic/align), цвет.
Это «рецепт» для CSS в cards.py.
"""
import glob
import json
import math
import os


def rgba(c):
    r, g, b = round(c["r"] * 255), round(c["g"] * 255), round(c["b"] * 255)
    a = c.get("a", 1.0)
    return f"#{r:02x}{g:02x}{b:02x}" if a >= 0.999 else f"rgba({r},{g},{b},{round(a,2)})"


def main():
    for path in sorted(glob.glob("figma_slots_raw/*.json")):
        name = os.path.splitext(os.path.basename(path))[0]
        d = json.load(open(path))
        node = list(d["nodes"].values())[0]["document"]
        bb = node.get("absoluteBoundingBox") or {"x": 0, "y": 0}
        ox, oy = bb["x"], bb["y"]
        texts = []

        def walk(n):
            if n.get("type") == "TEXT":
                texts.append(n)
            for c in n.get("children", []):
                walk(c)
        walk(node)

        print(f"\n{'='*78}\n{name}  (id {node['id']}, {len(texts)} TEXT-слотов)\n{'='*78}")
        for t in texts:
            b = t.get("absoluteBoundingBox") or {}
            s = t.get("style", {})
            col = next((rgba(f["color"]) for f in t.get("fills", [])
                        if f.get("type") == "SOLID"), "?")
            x = round(b.get("x", ox) - ox, 1)
            y = round(b.get("y", oy) - oy, 1)
            w = round(b.get("width", 0), 1)
            h = round(b.get("height", 0), 1)
            extra = []
            if s.get("textCase"):
                extra.append(s["textCase"])
            if s.get("italic"):
                extra.append("italic")
            txt = (t.get("characters") or "").replace("\n", "⏎")[:38]
            print(f"  [{x:>6},{y:>6} {w:>5}x{h:<5}] "
                  f"{str(s.get('fontFamily'))[:16]:<16} w{s.get('fontWeight','')} "
                  f"{str(s.get('fontSize'))[:5]:>5}px lh{str(s.get('lineHeightPx'))[:4]:>4} "
                  f"ls{str(round(s.get('letterSpacing',0),1)):>5} {s.get('textAlignHorizontal','')[:6]:<6} "
                  f"{col:<8} {' '.join(extra):<12} «{txt}»")


if __name__ == "__main__":
    main()
