"""Год-рекап через Telethon (тест-сессия v2_local): python3 year_recap_tg.py <channel>
Даёт всё, что веб + РЕАКЦИИ + ХИТ-ПОСТЫ → полный сет 19 карточек."""
import asyncio, json, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/Users/kristina/kris_/bot_tg_v2")
import os
from dotenv import load_dotenv
load_dotenv("/Users/kristina/kris_/bot_tg_v2/.env")

from telethon import TelegramClient
import analyzer

CH = sys.argv[1] if len(sys.argv) > 1 else "polozhnyak"
ROOT = Path("/Users/kristina/kris_/bot_tg_v2")
CUTOFF = datetime.now(timezone.utc) - timedelta(days=365)
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def msg_reactions(m) -> int:
    if not m.reactions or not m.reactions.results:
        return 0
    return sum(r.count for r in m.reactions.results)


async def main():
    t0 = time.time()
    client = TelegramClient(str(ROOT / "v2_local"),
                            int(os.environ["API_ID"]), os.environ["API_HASH"])
    await client.connect()
    if not await client.is_user_authorized():
        print("СЕССИЯ НЕ АВТОРИЗОВАНА")
        return

    entity = await client.get_entity(CH)
    title = getattr(entity, "title", CH)
    from telethon.tl.functions.channels import GetFullChannelRequest
    full = await client(GetFullChannelRequest(entity))
    subscribers = full.full_chat.participants_count or 0

    cache_dir = ROOT / "cache" / CH
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        await client.download_profile_photo(entity, file=str(cache_dir / "avatar.png"))
        print("AVATAR ok")
    except Exception as e:
        print("AVATAR fail:", e)

    posts, seen_text = [], set()
    groups, photo_groups = set(), set()
    total_reactions = 0
    candidates = []  # (reactions, text, date)
    n_msgs = 0
    async for m in client.iter_messages(entity):
        if m.date < CUTOFF:
            break
        n_msgs += 1
        gid = m.grouped_id or m.id  # альбом = 1 пост (как видит юзер)
        groups.add(gid)
        if m.photo or m.video:
            photo_groups.add(gid)
        r = msg_reactions(m)
        total_reactions += r
        text = (m.message or "").strip()
        if text:
            if text not in seen_text:
                seen_text.add(text)
                posts.append((m.date, text))
            if r > 0 and len(text) > 15:
                candidates.append((r, text, m.date))

    await client.disconnect()
    candidates.sort(key=lambda x: -x[0])
    top_posts = [
        {"reactions": r, "text": t,
         "date": f"{d.day} {MONTHS[d.month - 1]}"}
        for r, t, d in candidates[:3]
    ]
    print(f"FETCH {time.time()-t0:.0f}s: {title!r} subs={subscribers} | "
          f"сообщений={n_msgs} постов={len(groups)} с_фото={len(photo_groups)} "
          f"текстовых={len(posts)} реакций={total_reactions}")
    if len(posts) < 30:
        print("СЛИШКОМ МАЛО ПОСТОВ")
        return

    result = await analyzer._run_analysis_pipeline(
        posts, CH, title, subscribers, lite_mode=False, enable_llm=True,
        total_photos=len(photo_groups), total_reactions=total_reactions,
        top_posts=top_posts)
    analyzer._save_to_cache(CH, result, lite_mode=False)

    meta_p = cache_dir / "meta.json"
    meta = json.load(open(meta_p))
    meta["v2"]["total_posts"] = len(groups)
    meta["v2"]["posts_per_day_avg"] = round(len(groups) / 365, 1)
    json.dump(meta, open(meta_p, "w"), ensure_ascii=False)
    v = meta["v2"]
    print("META:", v["total_posts"], "постов |", v["total_photos"], "с фото |",
          v["total_reactions"], "реакций | top_posts:", len(v["top_posts"]))
    print("jungian:", v.get("jungian_archetype"), "| phrase:", v.get("one_phrase_llm"))
    print("topics:", meta.get("topics"))


asyncio.run(main())
