#!/usr/bin/env python3
"""Терпеливая выгрузка фреймов templates_clean из Figma с бэкоффом на 429.

Тянет по одному представителю на каждую уникальную раскладку, складывает
сырые ответы в figma_slots_raw/<name>.json. Запускать в фоне.
"""
import json
import os
import ssl
import time
import urllib.request

import certifi

TOKEN = os.environ["FIGMA_TOKEN"]
KEY = "WTIDPiGDCiIiD3swdbdNKl"
CTX = ssl.create_default_context(cafile=certifi.where())
OUT = "figma_slots_raw"
os.makedirs(OUT, exist_ok=True)

# name -> node-id (по одному представителю на раскладку)
FRAMES = {
    "best":               "252:247",
    "main_themes":        "258:1528",
    "sum_of_reactions":   "256:126",
    "post_by_days_weeks": "334:222",
    "geography":          "95:245",
    "top_phrases":        "334:82",
    "emotions":           "327:549",
    "chanal_in_one_phrase": "312:492",
    "hit_post":           "330:96",
    "reading_statisticks": "330:161",
    "the_most_used_word": "334:108",
    "top_person":         "341:279",
    "archetype":          "355:2824",
    "bad_words":          "383:521",
    "vocabulary":         "383:645",
    "chronotype":         "383:992",
    "word_cloude":        "94:2234",
    "bad_word_cloude":    "94:2245",
}


def fetch(node_id):
    url = f"https://api.figma.com/v1/files/{KEY}/nodes?ids={urllib.parse.quote(node_id)}"
    req = urllib.request.Request(url, headers={"X-Figma-Token": TOKEN})
    with urllib.request.urlopen(req, context=CTX) as r:
        return json.loads(r.read().decode())


import urllib.parse  # noqa: E402

done, failed = [], []
for name, nid in FRAMES.items():
    path = os.path.join(OUT, f"{name}.json")
    if os.path.exists(path):
        done.append(name)
        continue
    ok = False
    for attempt in range(8):
        try:
            data = fetch(nid)
            if data.get("status") == 429 or data.get("err") == "Rate limit exceeded":
                raise RuntimeError("429")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"OK {name} ({nid})", flush=True)
            ok = True
            break
        except Exception as e:
            wait = 30 * (attempt + 1)
            print(f"retry {name}: {e} -> sleep {wait}s", flush=True)
            time.sleep(wait)
    (done if ok else failed).append(name)
    time.sleep(8)  # вежливая пауза между удачными запросами

print(f"\nГОТОВО. done={len(done)} failed={failed}", flush=True)
