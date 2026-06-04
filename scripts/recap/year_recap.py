"""Год-рекап произвольного канала: python3 year_recap.py <channel_key>
Один проход по t.me/s: тексты для анализа + счёт ВСЕХ постов и постов с фото.
Потом: пайплайн с LLM → кэш → патч total_posts/фото → аватарка."""
import asyncio, json, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/Users/kristina/kris_/bot_tg_v2")

import aiohttp
from bs4 import BeautifulSoup

import analyzer

CH = sys.argv[1] if len(sys.argv) > 1 else "polozhnyak"
ROOT = Path("/Users/kristina/kris_/bot_tg_v2")
CUTOFF = datetime.now(timezone.utc) - timedelta(days=365)


async def main():
    t0 = time.time()
    posts, seen_text = [], set()
    all_ids, photo_ids = set(), set()
    title, subscribers = CH, 0
    before = None

    async with aiohttp.ClientSession() as s:
        # аватарка
        try:
            async with s.get(f"https://t.me/{CH}") as r:
                page = await r.text()
            m = re.search(r'<img class="tgme_page_photo_image" src="([^"]+)"', page) \
                or re.search(r'property="og:image" content="([^"]+)"', page)
            if m:
                async with s.get(m.group(1)) as r:
                    (ROOT / "cache" / CH).mkdir(parents=True, exist_ok=True)
                    (ROOT / "cache" / CH / "avatar.png").write_bytes(await r.read())
                print("AVATAR ok")
        except Exception as e:
            print("AVATAR fail:", e)

        for page_n in range(200):
            url = f"https://t.me/s/{CH}" + (f"?before={before}" if before else "")
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    break
                html = await r.text()
            soup = BeautifulSoup(html, "html.parser")
            if page_n == 0:
                el = soup.find("div", class_="tgme_channel_info_header_title")
                if el:
                    title = el.get_text(strip=True)
                el = soup.find("div", class_="tgme_channel_info_counter")
                if el:
                    m = re.search(r"([\d\s,.]+)", el.get_text())
                    if m:
                        try:
                            subscribers = int(re.sub(r"[\s,.]", "", m.group(1)))
                        except ValueError:
                            pass
            widgets = soup.find_all("div", class_="tgme_widget_message")
            if not widgets:
                break
            min_id, stop = None, False
            for w in widgets:
                try:
                    mid = int(w.get("data-post", "").split("/")[-1])
                except ValueError:
                    continue
                min_id = mid if min_id is None or mid < min_id else min_id
                t = w.find("time")
                if not (t and t.get("datetime")):
                    continue
                dt = datetime.fromisoformat(t["datetime"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < CUTOFF:
                    stop = True
                    continue
                all_ids.add(mid)
                if w.find(class_="tgme_widget_message_photo_wrap") or \
                   w.find(class_="tgme_widget_message_video_player"):
                    photo_ids.add(mid)
                td = w.find("div", class_="tgme_widget_message_text")
                if td:
                    text = td.get_text(separator=" ", strip=True)
                    if text and text not in seen_text:
                        seen_text.add(text)
                        posts.append((dt, text))
            if stop or min_id is None:
                break
            before = min_id
            await asyncio.sleep(0.3)

    print(f"FETCH {time.time()-t0:.0f}s: title={title!r} subs={subscribers} "
          f"всего_за_год={len(all_ids)} с_фото={len(photo_ids)} текстовых={len(posts)}")
    if len(posts) < 30:
        print("СЛИШКОМ МАЛО ПОСТОВ — рекап не делаем")
        return

    result = await analyzer._run_analysis_pipeline(
        posts, CH, title, subscribers, lite_mode=False, enable_llm=True)
    analyzer._save_to_cache(CH, result, lite_mode=False)

    meta_p = ROOT / "cache" / CH / "meta.json"
    meta = json.load(open(meta_p))
    meta["v2"]["total_posts"] = len(all_ids)
    meta["v2"]["posts_per_day_avg"] = round(len(all_ids) / 365, 1)
    meta["v2"]["total_photos"] = len(photo_ids)
    json.dump(meta, open(meta_p, "w"), ensure_ascii=False)
    v = meta["v2"]
    print("META:", v["total_posts"], "постов |", v["total_photos"], "с фото |",
          v["start_date"], "→", v["end_date"])
    print("jungian:", v.get("jungian_archetype"), "| phrase:", v.get("one_phrase_llm"))
    print("topics:", meta.get("topics"))


asyncio.run(main())
