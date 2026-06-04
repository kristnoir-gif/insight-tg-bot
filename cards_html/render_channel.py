#!/usr/bin/env python3
"""Dev-скрипт: рендер v2-галереи по кэшу канала + отправка админу на осмотр.

Usage: python3 cards_html/render_channel.py polozhnyak [--no-send]

Использует КАНОНИЧЕСКИЙ рендер render_full_v2_gallery (cards_html/render_gallery.py) —
тот же, что зовёт бот. Тут только: собрать result из cache/<user>/meta.json и отправить.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyzer import AnalysisResult, V2CardData, ChannelStats
from render_gallery import render_full_v2_gallery

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cards_html" / "out"


def _result_from_cache(username: str) -> AnalysisResult:
    meta = json.load(open(ROOT / "cache" / username / "meta.json"))
    # отбрасываем ключи v2, которых нет в текущем V2CardData (старые кэши)
    v2_fields = set(V2CardData.__dataclass_fields__)
    v2 = V2CardData(**{k: val for k, val in meta["v2"].items() if k in v2_fields})
    return AnalysisResult(
        title=meta.get("title", ""),
        topics=meta.get("topics") or [],
        stats=ChannelStats(unique_count=meta.get("unique_count", 0)),
        v2=v2,
    )


def main(username: str, send: bool = True):
    result = _result_from_cache(username)
    paths = render_full_v2_gallery(result, username, out_dir=OUT)
    print("RENDERED:", [p.name for p in paths])
    if send:
        send_to_bot(paths, username)


def send_to_bot(paths, username: str = ""):
    import asyncio
    from config import BOT_TOKEN, ADMIN_ID
    from aiogram import Bot
    from aiogram.types import InputMediaPhoto, FSInputFile

    async def go():
        bot = Bot(BOT_TOKEN)
        try:
            await bot.send_message(ADMIN_ID, f"🎨 Набор v2-карточек по @{username} ({len(paths)} шт) — на осмотр")
            for i in range(0, len(paths), 10):
                chunk = paths[i:i + 10]
                media = [InputMediaPhoto(media=FSInputFile(str(p))) for p in chunk]
                await bot.send_media_group(ADMIN_ID, media)
            print(f"SENT {len(paths)} cards to ADMIN_ID={ADMIN_ID}")
        finally:
            await bot.session.close()

    asyncio.run(go())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "polozhnyak",
         send="--no-send" not in sys.argv)
