"""Fill subscribers for public channels using web scraping (t.me/channel).

No authentication needed, no FloodWait limits from Telegram API.
Only works for public channels with username.
"""
import asyncio
import logging
import re
import sqlite3
import sys
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_PATH = Path(__file__).resolve().parent.parent.parent / "users.db"


def fetch_channel_keys() -> list[tuple[str, int]]:
    """Fetch all channels that need subscriber count (subscribers = 0)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Only fetch channels without subscriber data
    cur.execute(
        "SELECT channel_key, subscribers FROM channel_stats WHERE subscribers = 0 ORDER BY analysis_count DESC"
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def update_subscribers(channel_key: str, subscribers: int) -> None:
    """Update subscriber count in database."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE channel_stats SET subscribers = ? WHERE channel_key = ?",
        (subscribers, channel_key),
    )
    conn.commit()
    conn.close()


async def fetch_subscribers_from_web(session: aiohttp.ClientSession, channel_username: str) -> int | None:
    """Fetch subscriber count from t.me/channel_username page.
    
    Returns:
        int: Number of subscribers, or None if failed/private channel
    """
    try:
        url = f"https://t.me/{channel_username}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                return None
            
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for subscriber count in page_extra div
            # Example: <div class="tgme_page_extra">1.2K subscribers</div>
            extra_div = soup.find('div', class_='tgme_page_extra')
            if not extra_div:
                return None
            
            text = extra_div.get_text(strip=True)
            # Parse "1.2K subscribers" or "123 subscribers"
            match = re.search(r'([\d.]+)([KMkm]?)\s+subscribers?', text, re.IGNORECASE)
            if not match:
                return None
            
            number = float(match.group(1))
            multiplier = match.group(2).upper()
            
            if multiplier == 'K':
                number *= 1000
            elif multiplier == 'M':
                number *= 1000000
            
            return int(number)
    
    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching {channel_username}")
        return None
    except Exception as e:
        logger.debug(f"Error fetching {channel_username}: {e}")
        return None


async def main(concurrency: int = 5) -> None:
    """Main function to process all channels.
    
    Args:
        concurrency: Number of concurrent requests (default 5 to avoid rate limiting)
    """
    rows = fetch_channel_keys()
    logger.info(f"Will update {len(rows)} channels (with 0 subscribers)")
    
    total = len(rows)
    processed = 0
    updated = 0
    skipped = 0
    
    async with aiohttp.ClientSession() as session:
        # Process in batches to control concurrency
        for i in range(0, len(rows), concurrency):
            batch = rows[i:i + concurrency]
            tasks = []
            
            for channel_key, existing_subs in batch:
                # Skip channels that don't look like usernames
                # (private channels have IDs or special formats)
                if channel_key.startswith('+') or channel_key.startswith('-') or channel_key.isdigit():
                    processed += 1
                    skipped += 1
                    logger.debug(f"[{processed}/{total}] {channel_key} -> skip (not username)")
                    continue
                
                tasks.append((channel_key, fetch_subscribers_from_web(session, channel_key)))
            
            # Execute batch concurrently
            results = await asyncio.gather(*[task[1] for task in tasks])
            
            for (channel_key, _), subscribers in zip(tasks, results):
                processed += 1
                
                if subscribers is not None and subscribers > 0:
                    update_subscribers(channel_key, subscribers)
                    updated += 1
                    logger.info(f"[{processed}/{total}] {channel_key} -> {subscribers:,}")
                else:
                    # Mark as checked even if failed (keep 0)
                    logger.info(f"[{processed}/{total}] {channel_key} -> not found or private")
                
                # Small delay between batches to be polite
                await asyncio.sleep(0.2)
    
    logger.info(f"✅ Completed! Processed: {processed}, Updated: {updated}, Skipped: {skipped}")


if __name__ == "__main__":
    concurrency = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    asyncio.run(main(concurrency=concurrency))
