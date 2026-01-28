"""Fill subscribers for channels from channel_stats using Telethon.

Uses the main session and proxy from config.py. Updates users.db in place.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
import time
from pathlib import Path

# Add parent directory to path so we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient
from telethon.errors import ChannelInvalidError, ChannelPrivateError, FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest

import config

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_PATH = Path(__file__).resolve().parent.parent / "users.db"


def fetch_channel_keys(limit: int | None = None) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    sql = "SELECT channel_key, subscribers FROM channel_stats ORDER BY analysis_count DESC"
    if limit:
        sql += " LIMIT ?"
        cur.execute(sql, (limit,))
    else:
        cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return rows


def update_subscribers(channel_key: str, subscribers: int | None) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE channel_stats SET subscribers = ? WHERE channel_key = ?",
        (subscribers if subscribers is not None else 0, channel_key),
    )
    conn.commit()
    conn.close()


async def main(limit: int | None = None, delay: float = 1.2) -> None:
    rows = fetch_channel_keys(limit)
    logger.info("Will update %s channels", len(rows))

    client = TelegramClient(
        config.SESSION_NAME,
        config.API_ID,
        config.API_HASH,
        proxy=config.PROXY_MAIN,
    )
    await client.start()

    for idx, (key, subs_existing) in enumerate(rows, start=1):
        if subs_existing and subs_existing > 0:
            logger.info("[%s/%s] %s -> skip (already %s)", idx, len(rows), key, subs_existing)
            continue
        try:
            entity = await client.get_entity(key)
            full = await client(GetFullChannelRequest(entity))
            subs = full.full_chat.participants_count or 0
            update_subscribers(key, subs)
            logger.info("[%s/%s] %s -> %s", idx, len(rows), key, subs)
        except FloodWaitError as e:
            wait = int(e.seconds) + 1
            logger.warning("FloodWaitError %ss on %s; sleeping", wait, key)
            time.sleep(wait)
            # retry once after wait
            try:
                entity = await client.get_entity(key)
                full = await client(GetFullChannelRequest(entity))
                subs = full.full_chat.participants_count or 0
                update_subscribers(key, subs)
                logger.info("[%s/%s] %s -> %s", idx, len(rows), key, subs)
            except Exception as e2:  # noqa: BLE001
                logger.error("Failed after flood wait on %s: %s", key, e2)
        except (ChannelInvalidError, ChannelPrivateError) as e:
            logger.warning("Skip %s: %s", key, e)
            update_subscribers(key, 0)
        except Exception as e:  # noqa: BLE001
            logger.error("Error on %s: %s", key, e)
            update_subscribers(key, 0)
        await asyncio.sleep(delay)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
