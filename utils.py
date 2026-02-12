"""
Утилиты общего назначения.
"""
import sqlite3
import logging

from db import DB_PATH, get_db_connection
from config import STATS_OFFSET_USERS, STATS_OFFSET_ANALYSES

logger = logging.getLogger(__name__)


def format_number(n: int) -> str:
    """Форматирует число: 3000 -> '3K', 150 -> '150'."""
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(n)


def get_bot_stats() -> dict:
    """
    Получает базовую статистику бота для описания.

    Returns:
        {'total_users': int, 'total_channels': int, 'total_analyses': int}
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM channel_stats")
            total_channels = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(analysis_count) FROM channel_stats")
            result = cursor.fetchone()
            total_analyses = result[0] if result and result[0] else 0
        return {
            "total_users": total_users + STATS_OFFSET_USERS,
            "total_channels": total_channels,
            "total_analyses": total_analyses + STATS_OFFSET_ANALYSES,
        }
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения статистики бота: {e}")
        return {"total_users": 0, "total_channels": 0, "total_analyses": 0}
