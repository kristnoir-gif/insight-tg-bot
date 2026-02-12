"""Одноразовый скрипт для генерации кэша канала polozhnyak."""

import asyncio

from telethon import TelegramClient

from analyzer import analyze_channel
from config import API_ID, API_HASH, SESSION_NAME


async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()
    result = await analyze_channel(client, "polozhnyak", lite_mode=False)
    if result:
        s = result.stats
        print(f"title: {result.title}")
        print(f"unique_count: {s.unique_count}, avg_len: {s.avg_len}, "
              f"scream_index: {s.scream_index}, unique_names_count: {s.unique_names_count}")
    else:
        print("Анализ не удался")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
