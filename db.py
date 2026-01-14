"""
Модуль для работы с SQLite базой данных.
Отслеживание пользователей и статистики использования.
"""
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = Path(__file__).parent / "users.db"

# ID администратора (замените на свой Telegram ID)
ADMIN_ID = 123456789  # TODO: Укажите свой Telegram ID


def init_db() -> None:
    """Инициализирует базу данных и создаёт таблицы."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                request_count INTEGER DEFAULT 0,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
        logger.info(f"База данных инициализирована: {DB_PATH}")

    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")


def register_user(user_id: int, username: str | None) -> None:
    """
    Регистрирует нового пользователя или обновляет username существующего.

    Args:
        user_id: Telegram ID пользователя.
        username: Username пользователя (может быть None).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO users (user_id, username, request_count, first_seen)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
        """, (user_id, username, datetime.now()))

        conn.commit()
        conn.close()
        logger.debug(f"Пользователь зарегистрирован: {user_id} (@{username})")

    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user_id}: {e}")


def log_request(user_id: int) -> None:
    """
    Увеличивает счётчик запросов пользователя на 1.

    Args:
        user_id: Telegram ID пользователя.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE users SET request_count = request_count + 1
            WHERE user_id = ?
        """, (user_id,))

        conn.commit()
        conn.close()
        logger.debug(f"Запрос залогирован для пользователя: {user_id}")

    except Exception as e:
        logger.error(f"Ошибка логирования запроса для {user_id}: {e}")


def get_stats() -> dict:
    """
    Получает общую статистику использования бота.

    Returns:
        Словарь со статистикой:
        - total_users: общее количество пользователей
        - total_requests: общее количество запросов
        - active_users: пользователи с хотя бы 1 запросом
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Общее количество пользователей
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        # Общее количество запросов
        cursor.execute("SELECT SUM(request_count) FROM users")
        total_requests = cursor.fetchone()[0] or 0

        # Активные пользователи (с хотя бы 1 запросом)
        cursor.execute("SELECT COUNT(*) FROM users WHERE request_count > 0")
        active_users = cursor.fetchone()[0]

        # Топ-5 пользователей по запросам
        cursor.execute("""
            SELECT user_id, username, request_count
            FROM users
            WHERE request_count > 0
            ORDER BY request_count DESC
            LIMIT 5
        """)
        top_users = cursor.fetchall()

        conn.close()

        return {
            "total_users": total_users,
            "total_requests": total_requests,
            "active_users": active_users,
            "top_users": top_users,
        }

    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        return {
            "total_users": 0,
            "total_requests": 0,
            "active_users": 0,
            "top_users": [],
        }


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id == ADMIN_ID
