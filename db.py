"""
Модуль для работы с SQLite базой данных.
Отслеживание пользователей, лимитов и платежей.
"""
import sqlite3
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = Path(__file__).parent / "users.db"

# ID администратора
ADMIN_ID = 26643106  # Telegram User ID

# Лимиты
FREE_DAILY_LIMIT = 1  # Бесплатных анализов в день

# Кэш
CACHE_TTL_HOURS = 6  # Время жизни кэша в часах


@dataclass
class UserStatus:
    """Статус доступа пользователя."""
    can_analyze: bool
    reason: str
    daily_used: int
    daily_limit: int
    paid_balance: int
    is_premium: bool
    premium_until: datetime | None


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
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                daily_requests_count INTEGER DEFAULT 0,
                last_request_date DATE,
                paid_balance INTEGER DEFAULT 0,
                premium_until TIMESTAMP
            )
        """)

        # Таблица кэша анализов каналов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channel_cache (
                channel_key TEXT PRIMARY KEY,
                title TEXT,
                stats_json TEXT,
                top_emojis_json TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица статистики анализов каналов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channel_stats (
                channel_key TEXT PRIMARY KEY,
                title TEXT,
                analysis_count INTEGER DEFAULT 1,
                last_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграция: добавляем новые колонки если их нет
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'daily_requests_count' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN daily_requests_count INTEGER DEFAULT 0")
        if 'last_request_date' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN last_request_date DATE")
        if 'paid_balance' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN paid_balance INTEGER DEFAULT 0")
        if 'premium_until' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN premium_until TIMESTAMP")

        # Миграция channel_stats: добавляем колонку subscribers
        cursor.execute("PRAGMA table_info(channel_stats)")
        cs_columns = [col[1] for col in cursor.fetchall()]
        if 'subscribers' not in cs_columns:
            cursor.execute("ALTER TABLE channel_stats ADD COLUMN subscribers INTEGER DEFAULT 0")

        # Индексы для ускорения запросов
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_last_request ON users(last_request_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_premium ON users(premium_until)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_channel_stats_subs ON channel_stats(subscribers)")

        conn.commit()
        conn.close()
        logger.info(f"База данных инициализирована: {DB_PATH}")

    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")


def register_user(user_id: int, username: str | None) -> None:
    """Регистрирует нового пользователя или обновляет username."""
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


def check_user_access(user_id: int) -> UserStatus:
    """
    Проверяет доступ пользователя к анализу.

    Приоритет:
    1. Админ — всегда доступ
    2. Premium (premium_until > now) — доступ
    3. Дневной лимит не исчерпан — доступ
    4. Платный баланс > 0 — доступ
    5. Иначе — нет доступа
    """
    # Админ всегда имеет доступ
    if user_id == ADMIN_ID:
        return UserStatus(
            can_analyze=True,
            reason="admin",
            daily_used=0,
            daily_limit=999,
            paid_balance=999,
            is_premium=True,
            premium_until=None
        )

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT daily_requests_count, last_request_date, paid_balance, premium_until
            FROM users WHERE user_id = ?
        """, (user_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            # Новый пользователь
            return UserStatus(
                can_analyze=True,
                reason="free",
                daily_used=0,
                daily_limit=FREE_DAILY_LIMIT,
                paid_balance=0,
                is_premium=False,
                premium_until=None
            )

        daily_count, last_date_str, paid_balance, premium_until_str = row
        daily_count = daily_count or 0
        paid_balance = paid_balance or 0

        # Проверяем premium
        premium_until = None
        is_premium = False
        if premium_until_str:
            premium_until = datetime.fromisoformat(premium_until_str)
            if premium_until > datetime.now():
                is_premium = True

        # Сбрасываем дневной счётчик если новый день
        today = date.today()
        if last_date_str:
            last_date = date.fromisoformat(last_date_str)
            if last_date < today:
                daily_count = 0

        # Проверяем доступ по приоритету
        if is_premium:
            return UserStatus(
                can_analyze=True,
                reason="premium",
                daily_used=daily_count,
                daily_limit=FREE_DAILY_LIMIT,
                paid_balance=paid_balance,
                is_premium=True,
                premium_until=premium_until
            )

        if daily_count < FREE_DAILY_LIMIT:
            return UserStatus(
                can_analyze=True,
                reason="free",
                daily_used=daily_count,
                daily_limit=FREE_DAILY_LIMIT,
                paid_balance=paid_balance,
                is_premium=False,
                premium_until=premium_until
            )

        if paid_balance > 0:
            return UserStatus(
                can_analyze=True,
                reason="paid",
                daily_used=daily_count,
                daily_limit=FREE_DAILY_LIMIT,
                paid_balance=paid_balance,
                is_premium=False,
                premium_until=premium_until
            )

        # Лимит исчерпан
        return UserStatus(
            can_analyze=False,
            reason="limit_reached",
            daily_used=daily_count,
            daily_limit=FREE_DAILY_LIMIT,
            paid_balance=paid_balance,
            is_premium=False,
            premium_until=premium_until
        )

    except Exception as e:
        logger.error(f"Ошибка проверки доступа для {user_id}: {e}")
        return UserStatus(
            can_analyze=False,
            reason="error",
            daily_used=0,
            daily_limit=FREE_DAILY_LIMIT,
            paid_balance=0,
            is_premium=False,
            premium_until=None
        )


def consume_analysis(user_id: int, reason: str) -> None:
    """
    Списывает анализ в зависимости от типа доступа.

    Args:
        user_id: ID пользователя.
        reason: Тип доступа ('free', 'paid', 'premium', 'admin').
    """
    if reason == "admin":
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        today = date.today().isoformat()

        if reason == "free":
            # Увеличиваем дневной счётчик
            cursor.execute("""
                UPDATE users
                SET daily_requests_count = CASE
                    WHEN last_request_date = ? THEN daily_requests_count + 1
                    ELSE 1
                END,
                last_request_date = ?,
                request_count = request_count + 1
                WHERE user_id = ?
            """, (today, today, user_id))

        elif reason == "paid":
            # Списываем с платного баланса
            cursor.execute("""
                UPDATE users
                SET paid_balance = paid_balance - 1,
                request_count = request_count + 1
                WHERE user_id = ?
            """, (user_id,))

        elif reason == "premium":
            # Premium — просто логируем
            cursor.execute("""
                UPDATE users
                SET request_count = request_count + 1
                WHERE user_id = ?
            """, (user_id,))

        conn.commit()
        conn.close()
        logger.debug(f"Анализ списан для {user_id}, тип: {reason}")

    except Exception as e:
        logger.error(f"Ошибка списания анализа для {user_id}: {e}")


def add_paid_balance(user_id: int, amount: int) -> None:
    """Добавляет платный баланс пользователю."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE users SET paid_balance = COALESCE(paid_balance, 0) + ?
            WHERE user_id = ?
        """, (amount, user_id))

        conn.commit()
        conn.close()
        logger.info(f"Добавлен платный баланс {amount} для {user_id}")

    except Exception as e:
        logger.error(f"Ошибка добавления баланса для {user_id}: {e}")


def set_premium(user_id: int, days: int) -> None:
    """Устанавливает premium статус на указанное количество дней."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        premium_until = datetime.now() + timedelta(days=days)

        cursor.execute("""
            UPDATE users SET premium_until = ?
            WHERE user_id = ?
        """, (premium_until.isoformat(), user_id))

        conn.commit()
        conn.close()
        logger.info(f"Premium установлен для {user_id} до {premium_until}")

    except Exception as e:
        logger.error(f"Ошибка установки premium для {user_id}: {e}")


def log_request(user_id: int) -> None:
    """Увеличивает общий счётчик запросов (для совместимости)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE users SET request_count = request_count + 1
            WHERE user_id = ?
        """, (user_id,))

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Ошибка логирования запроса для {user_id}: {e}")


def get_stats() -> dict:
    """Получает общую статистику использования бота."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(request_count) FROM users")
        total_requests = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM users WHERE request_count > 0")
        active_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE premium_until > datetime('now')")
        premium_users = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(paid_balance) FROM users")
        total_paid_balance = cursor.fetchone()[0] or 0

        # Пользователи, которые покупали анализы
        cursor.execute("SELECT COUNT(*) FROM users WHERE paid_balance > 0 OR premium_until > datetime('now')")
        paid_users = cursor.fetchone()[0]

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
            "premium_users": premium_users,
            "total_paid_balance": total_paid_balance,
            "paid_users": paid_users,
            "top_users": top_users,
        }

    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        return {
            "total_users": 0,
            "total_requests": 0,
            "active_users": 0,
            "premium_users": 0,
            "total_paid_balance": 0,
            "paid_users": 0,
            "top_users": [],
        }


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id == ADMIN_ID


def get_all_user_ids() -> list[int]:
    """Возвращает список всех user_id из базы."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        result = [row[0] for row in cursor.fetchall()]
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Ошибка получения user_id: {e}")
        return []


def log_channel_analysis(channel_key: str, title: str, subscribers: int = 0) -> None:
    """Записывает анализ канала в статистику."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO channel_stats (channel_key, title, analysis_count, last_analyzed, subscribers)
            VALUES (?, ?, 1, datetime('now'), ?)
            ON CONFLICT(channel_key) DO UPDATE SET
                title = excluded.title,
                analysis_count = analysis_count + 1,
                last_analyzed = datetime('now'),
                subscribers = excluded.subscribers
        """, (channel_key.lower(), title, subscribers))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка записи статистики канала: {e}")


def get_top_channels(limit: int = 5) -> list[tuple[str, str, int]]:
    """Возвращает топ каналов по количеству подписчиков."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT channel_key, title, subscribers
            FROM channel_stats
            WHERE subscribers > 0
            ORDER BY subscribers DESC
            LIMIT ?
        """, (limit,))
        result = cursor.fetchall()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Ошибка получения топ каналов: {e}")
        return []


# --- Кэш анализов каналов ---

def get_cached_analysis(channel_key: str) -> dict | None:
    """
    Получает кэшированный анализ канала если он не истёк.

    Args:
        channel_key: Ключ канала (username или id).

    Returns:
        Словарь с данными или None если кэш не найден/истёк.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT title, stats_json, top_emojis_json, cached_at
            FROM channel_cache
            WHERE channel_key = ?
        """, (channel_key.lower(),))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        title, stats_json, emojis_json, cached_at_str = row

        # Проверяем TTL
        cached_at = datetime.fromisoformat(cached_at_str)
        age_hours = (datetime.now() - cached_at).total_seconds() / 3600

        if age_hours > CACHE_TTL_HOURS:
            logger.debug(f"Кэш для {channel_key} истёк ({age_hours:.1f}ч)")
            return None

        return {
            "title": title,
            "stats": json.loads(stats_json),
            "top_emojis": json.loads(emojis_json),
            "cached_at": cached_at,
            "age_hours": age_hours,
        }

    except Exception as e:
        logger.error(f"Ошибка чтения кэша для {channel_key}: {e}")
        return None


def save_analysis_cache(
    channel_key: str,
    title: str,
    stats: object,
    top_emojis: list
) -> None:
    """
    Сохраняет результат анализа в кэш.

    Args:
        channel_key: Ключ канала (username или id).
        title: Название канала.
        stats: Объект ChannelStats.
        top_emojis: Список топ эмодзи.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Конвертируем stats в dict если это dataclass
        stats_dict = asdict(stats) if hasattr(stats, '__dataclass_fields__') else stats

        cursor.execute("""
            INSERT INTO channel_cache (channel_key, title, stats_json, top_emojis_json, cached_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel_key) DO UPDATE SET
                title = excluded.title,
                stats_json = excluded.stats_json,
                top_emojis_json = excluded.top_emojis_json,
                cached_at = excluded.cached_at
        """, (
            channel_key.lower(),
            title,
            json.dumps(stats_dict, ensure_ascii=False),
            json.dumps(top_emojis, ensure_ascii=False),
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()
        logger.info(f"Кэш сохранён для канала: {channel_key}")

    except Exception as e:
        logger.error(f"Ошибка сохранения кэша для {channel_key}: {e}")
