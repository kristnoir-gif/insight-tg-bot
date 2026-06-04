#!/usr/bin/env python3
"""Экстрактор слоёв из Figma REST API.

Выгружает дерево фреймов с координатами, шрифтами и цветами в JSON,
удобный для генерации CSS под карточки.

Usage:
    python3 figma_extract.py FILE_KEY [--node 386:1112] [--node 12:34] \
        [--token TOKEN] [--out figma_dump.json]

Токен можно положить в переменную окружения FIGMA_TOKEN.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import ssl
import urllib.parse
import urllib.request

API = "https://api.figma.com/v1"

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()


def fetch(path: str, token: str) -> dict:
    req = urllib.request.Request(f"{API}/{path}", headers={"X-Figma-Token": token})
    with urllib.request.urlopen(req, context=_SSL_CTX) as r:
        return json.loads(r.read().decode())


def rgba(color: dict, opacity: float | None = None) -> str:
    r = round(color["r"] * 255)
    g = round(color["g"] * 255)
    b = round(color["b"] * 255)
    a = color.get("a", 1.0)
    if opacity is not None:
        a *= opacity
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {round(a, 3)})"


def fills_to_colors(fills: list) -> list:
    out = []
    for f in fills or []:
        if f.get("visible") is False:
            continue
        t = f.get("type")
        if t == "SOLID":
            out.append({"type": "solid", "color": rgba(f["color"], f.get("opacity"))})
        elif t and t.startswith("GRADIENT"):
            stops = [
                {"color": rgba(s["color"]), "position": round(s["position"], 3)}
                for s in f.get("gradientStops", [])
            ]
            out.append({"type": t.lower(), "stops": stops})
        elif t == "IMAGE":
            out.append({"type": "image", "ref": f.get("imageRef")})
    return out


def text_style(style: dict) -> dict:
    keys = [
        "fontFamily", "fontPostScriptName", "fontWeight", "fontSize",
        "lineHeightPx", "lineHeightPercent", "lineHeightUnit",
        "letterSpacing", "textAlignHorizontal", "textAlignVertical",
        "textCase", "italic",
    ]
    return {k: style[k] for k in keys if k in style}


def effects_summary(effects: list) -> list:
    out = []
    for e in effects or []:
        if e.get("visible") is False:
            continue
        item = {"type": e["type"]}
        if "radius" in e:
            item["radius"] = round(e["radius"], 2)
        if "color" in e:
            item["color"] = rgba(e["color"])
        if "offset" in e:
            item["offset"] = {k: round(v, 2) for k, v in e["offset"].items()}
        out.append(item)
    return out


def walk(node: dict, frame_origin: tuple[float, float] | None, depth: int) -> dict:
    """Рекурсивно собирает узел. Координаты — глобальные и локальные (от фрейма)."""
    bbox = node.get("absoluteBoundingBox")
    out: dict = {
        "id": node["id"],
        "name": node.get("name"),
        "type": node.get("type"),
        "depth": depth,
    }

    # У первого FRAME фиксируем origin для пересчёта локальных координат
    if frame_origin is None and node.get("type") in ("FRAME", "COMPONENT", "INSTANCE") and bbox:
        frame_origin = (bbox["x"], bbox["y"])

    if bbox:
        out["abs"] = {k: round(bbox[k], 2) for k in ("x", "y", "width", "height")}
        if frame_origin:
            out["xywh"] = {
                "x": round(bbox["x"] - frame_origin[0], 2),
                "y": round(bbox["y"] - frame_origin[1], 2),
                "w": round(bbox["width"], 2),
                "h": round(bbox["height"], 2),
            }

    if node.get("rotation"):
        import math
        out["rotation_deg"] = round(math.degrees(node["rotation"]), 2)

    if node.get("type") == "TEXT":
        out["text"] = node.get("characters")
        if node.get("style"):
            out["font"] = text_style(node["style"])

    colors = fills_to_colors(node.get("fills"))
    if colors:
        out["fills"] = colors
    if node.get("strokes"):
        out["strokes"] = fills_to_colors(node["strokes"])
        out["strokeWeight"] = node.get("strokeWeight")
    if node.get("cornerRadius"):
        out["cornerRadius"] = node["cornerRadius"]
    if node.get("rectangleCornerRadii"):
        out["cornerRadii"] = node["rectangleCornerRadii"]
    if node.get("effects"):
        eff = effects_summary(node["effects"])
        if eff:
            out["effects"] = eff
    if node.get("opacity") is not None:
        out["opacity"] = node["opacity"]

    # Auto-layout метрики
    for k in ("layoutMode", "itemSpacing", "paddingLeft", "paddingRight",
              "paddingTop", "paddingBottom"):
        if node.get(k):
            out.setdefault("layout", {})[k] = node[k]

    children = node.get("children")
    if children:
        out["children"] = [walk(c, frame_origin, depth + 1) for c in children]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file_key")
    ap.add_argument("--node", action="append", dest="nodes", default=[],
                    help="ID ноды (можно несколько). Без --node тянется весь файл.")
    ap.add_argument("--token", default=os.environ.get("FIGMA_TOKEN"))
    ap.add_argument("--out", default="figma_dump.json")
    args = ap.parse_args()

    if not args.token:
        print("Нужен токен: --token или FIGMA_TOKEN", file=sys.stderr)
        return 1

    if args.nodes:
        ids = ",".join(args.nodes)
        data = fetch(f"files/{args.file_key}/nodes?ids={urllib.parse.quote(ids)}", args.token)
        roots = [v["document"] for v in data["nodes"].values()]
    else:
        data = fetch(f"files/{args.file_key}", args.token)
        roots = data["document"]["children"]

    result = {
        "file": data.get("name"),
        "lastModified": data.get("lastModified"),
        "frames": [walk(r, None, 0) for r in roots],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # краткая сводка
    def count(n, acc):
        acc[n.get("type", "?")] = acc.get(n.get("type", "?"), 0) + 1
        for c in n.get("children", []):
            count(c, acc)
        return acc

    acc: dict = {}
    for r in result["frames"]:
        count(r, acc)
    print(f"✓ {args.out}: {sum(acc.values())} нод — " +
          ", ".join(f"{k}:{v}" for k, v in sorted(acc.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
