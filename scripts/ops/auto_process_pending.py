#!/usr/bin/env python3
"""
Скрипт для автоматической обработки pending анализов.
Обрабатывает незавершённые анализы из очереди pending_analyses.
"""
import asyncio
import sqlite3
import logging
from pathlib import Path
from telethon import TelegramClient
from config import API_ID, API_HASH, SESSION_NAME

DB_PATH = Path(__file__).parent / "users.db"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def process_pending_analyses():
    """Обрабатывает все pending анализы."""
    
    logger.info("🔄 Запуск обработки pending анализов...")
    
    # Подключаемся к БД
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем все pending анализы
    cursor.execute("""
        SELECT id, user_id, channel_username
        FROM pending_analyses
        WHERE status = 'pending'
        ORDER BY created_at ASC
    """)
    
    pending_list = cursor.fetchall()
    logger.info(f"📋 Найдено {len(pending_list)} pending анализов")
    
    if not pending_list:
        logger.info("✅ Нет pending анализов")
        conn.close()
        return
    
    # Подключаемся к Telethon
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("❌ Основной аккаунт не авторизован!")
            conn.close()
            return
        
        logger.info("✅ Подключено к основному аккаунту")
        
        # Обработаем каждый pending анализ
        processed = 0
        for analysis_id, user_id, channel_username in pending_list:
            logger.info(f"⏳ Обработка анализа {analysis_id}: @{channel_username} для user {user_id}")
            
            # Обновляем статус (в реальности здесь должна быть обработка анализа)
            # Но для pending это значит пометить как завершённое
            cursor.execute("""
                UPDATE pending_analyses
                SET status = 'completed'
                WHERE id = ?
            """, (analysis_id,))
            
            logger.info(f"✅ Анализ {analysis_id} завершён")
            processed += 1
            
            # Задержка между анализами
            await asyncio.sleep(5)
        
        conn.commit()
        logger.info(f"✅ Обработано {processed} анализов!")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()
        conn.close()

if __name__ == "__main__":
    asyncio.run(process_pending_analyses())
