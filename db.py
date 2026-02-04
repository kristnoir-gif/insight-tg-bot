"""
Модуль для работы с SQLite базой данных.
Отслеживание пользователей, лимитов и платежей.
"""
import sqlite3
import json
import logging
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict

from config import ADMIN_ID, ADMIN_IDS

logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = Path(__file__).parent / "users.db"


@contextmanager
def get_db_connection():
    """Контекстный менеджер для безопасной работы с БД."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    # WAL mode для высокой нагрузки (+3-5x пропускная способность)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    finally:
        conn.close()

# Лимиты
# Бесплатный анализ для виральности (если нет очереди)
FREE_DAILY_LIMIT = 1  # Бесплатных анализов в день (для новых пользователей)

# Кэш
CACHE_TTL_HOURS = 12  # Время жизни кэша в часах (увеличено для агрессивного кэширования)


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
        with get_db_connection() as conn:
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
                    last_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    subscribers INTEGER DEFAULT 0,
                    analyzed_by INTEGER
                )
            """)

            # Таблица событий FloodWait / перегрузки
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS floodwait_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    channel_key TEXT,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Таблица незавершённых анализов (для переотправки при ошибках)
            # priority: 2 = платный, 1 = premium, 0 = бесплатный
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    channel_key TEXT,
                    channel_username TEXT,
                    status TEXT DEFAULT 'pending',
                    priority INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, channel_key)
                )
            """)

            # Таблица платежей (история всех платежей)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    stars INTEGER,
                    payment_method TEXT,
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT
                )
            """)

            # Таблица кликов по кнопкам покупки (воронка)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS buy_clicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

            # Миграция channel_stats: добавляем колонки subscribers и analyzed_by
            cursor.execute("PRAGMA table_info(channel_stats)")
            cs_columns = [col[1] for col in cursor.fetchall()]
            if 'subscribers' not in cs_columns:
                cursor.execute("ALTER TABLE channel_stats ADD COLUMN subscribers INTEGER DEFAULT 0")
            if 'analyzed_by' not in cs_columns:
                cursor.execute("ALTER TABLE channel_stats ADD COLUMN analyzed_by INTEGER")

            # Индексы для floodwait_events
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_floodwait_created_at ON floodwait_events(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_floodwait_user ON floodwait_events(user_id)")

            # Индексы для ускорения запросов
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_last_request ON users(last_request_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_premium ON users(premium_until)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_channel_stats_subs ON channel_stats(subscribers)")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_created_at ON payments(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_user_id ON pending_analyses(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_priority ON pending_analyses(priority DESC, created_at ASC)")

            # Миграция pending_analyses: добавляем колонку priority
            cursor.execute("PRAGMA table_info(pending_analyses)")
            pa_columns = [col[1] for col in cursor.fetchall()]
            if 'priority' not in pa_columns:
                cursor.execute("ALTER TABLE pending_analyses ADD COLUMN priority INTEGER DEFAULT 0")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_buy_clicks_user_id ON buy_clicks(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_buy_clicks_created_at ON buy_clicks(created_at)")

            conn.commit()
            logger.info(f"База данных инициализирована: {DB_PATH}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка инициализации БД: {e}")


def register_user(user_id: int, username: str | None) -> bool:
    """Регистрирует нового пользователя или обновляет username.

    Args:
        user_id: ID пользователя
        username: Username пользователя

    Returns:
        True если это новый пользователь, False если уже существует
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Проверяем существует ли пользователь
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            existing = cursor.fetchone()

            if existing:
                # Просто обновляем username
                cursor.execute("""
                    UPDATE users SET username = ? WHERE user_id = ?
                """, (username, user_id))
                conn.commit()
                return False

            # Новый пользователь
            cursor.execute("""
                INSERT INTO users (user_id, username, request_count, first_seen)
                VALUES (?, ?, 0, ?)
            """, (user_id, username, datetime.now()))

            conn.commit()
            return True

    except sqlite3.Error as e:
        logger.error(f"Ошибка регистрации пользователя {user_id}: {e}")
        return False


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
    if user_id in ADMIN_IDS:
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
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT daily_requests_count, last_request_date, paid_balance, premium_until
                FROM users WHERE user_id = ?
            """, (user_id,))

            row = cursor.fetchone()

        if not row:
            # Новый пользователь — дать 1 бесплатный анализ в день
            return UserStatus(
                can_analyze=True,
                reason="free_daily",
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

        if paid_balance > 0:
            logger.info(f"✅ {user_id} может анализировать (reason=paid, balance={paid_balance})")
            return UserStatus(
                can_analyze=True,
                reason="paid",
                daily_used=daily_count,
                daily_limit=FREE_DAILY_LIMIT,
                paid_balance=paid_balance,
                is_premium=False,
                premium_until=premium_until
            )

        # Бесплатный пользователь — проверяем дневной лимит
        if daily_count < FREE_DAILY_LIMIT:
            logger.info(f"✅ {user_id} может анализировать (reason=free_daily, used={daily_count}/{FREE_DAILY_LIMIT})")
            return UserStatus(
                can_analyze=True,
                reason="free_daily",
                daily_used=daily_count,
                daily_limit=FREE_DAILY_LIMIT,
                paid_balance=paid_balance,
                is_premium=False,
                premium_until=premium_until
            )

        # Лимит исчерпан
        logger.warning(f"❌ {user_id} НЕ может анализировать (reason=limit_reached, balance={paid_balance}, daily={daily_count}/{FREE_DAILY_LIMIT})")
        return UserStatus(
            can_analyze=False,
            reason="limit_reached",
            daily_used=daily_count,
            daily_limit=FREE_DAILY_LIMIT,
            paid_balance=paid_balance,
            is_premium=False,
            premium_until=premium_until
        )

    except sqlite3.Error as e:
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


def consume_analysis(user_id: int, reason: str) -> bool:
    """
    Списывает анализ в зависимости от типа доступа.

    Args:
        user_id: ID пользователя.
        reason: Тип доступа ('free', 'free_daily', 'paid', 'premium', 'admin').

    Returns:
        True если анализ успешно списан, False при ошибке.
    """
    if reason == "admin":
        return True

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            today = date.today().isoformat()

            if reason in ("free", "free_daily"):
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
                # Списываем с платного баланса (только если баланс > 0)
                cursor.execute("""
                    UPDATE users
                    SET paid_balance = CASE
                        WHEN paid_balance > 0 THEN paid_balance - 1
                        ELSE 0
                    END,
                    request_count = request_count + 1
                    WHERE user_id = ? AND paid_balance > 0
                """, (user_id,))

            elif reason == "premium":
                # Premium — просто логируем
                cursor.execute("""
                    UPDATE users
                    SET request_count = request_count + 1
                    WHERE user_id = ?
                """, (user_id,))

            rows_updated = cursor.rowcount
            conn.commit()

        if rows_updated == 0:
            logger.warning(f"consume_analysis: пользователь {user_id} не найден в БД! reason={reason}")
            return False

        logger.info(f"Анализ списан для {user_id}, тип: {reason}")
        return True

    except sqlite3.Error as e:
        logger.error(f"Ошибка списания анализа для {user_id}: {e}")
        return False


def add_paid_balance(user_id: int, amount: int) -> bool:
    """Добавляет платный баланс пользователю. Возвращает True при успехе."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE users SET paid_balance = COALESCE(paid_balance, 0) + ?
                WHERE user_id = ?
            """, (amount, user_id))

            rows_updated = cursor.rowcount
            conn.commit()

        if rows_updated == 0:
            logger.warning(f"add_paid_balance: пользователь {user_id} не найден в БД!")
            return False

        logger.info(f"Добавлен платный баланс {amount} для {user_id}")
        return True

    except sqlite3.Error as e:
        logger.error(f"Ошибка добавления баланса для {user_id}: {e}")
        return False


def process_pack_payment(user_id: int, pack_amount: int, stars: int, payment_method: str, notes: str) -> bool:
    """Атомарно начисляет баланс и логирует платёж в одной транзакции."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET paid_balance = COALESCE(paid_balance, 0) + ? WHERE user_id = ?",
                (pack_amount, user_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                logger.warning(f"process_pack_payment: пользователь {user_id} не найден в БД!")
                return False
            cursor.execute(
                "INSERT INTO payments (user_id, stars, amount, payment_method, status, notes) VALUES (?, ?, '', ?, 'completed', ?)",
                (user_id, stars, payment_method, notes),
            )
            conn.commit()
            logger.info(f"Платёж обработан: user_id={user_id}, pack={pack_amount}, stars={stars}, notes={notes}")
            return True
    except sqlite3.Error as e:
        logger.error(f"Ошибка process_pack_payment для {user_id}: {e}")
        return False


def set_premium(user_id: int, days: int) -> None:
    """Устанавливает premium статус на указанное количество дней."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            premium_until = datetime.now() + timedelta(days=days)

            cursor.execute("""
                UPDATE users SET premium_until = ?
                WHERE user_id = ?
            """, (premium_until.isoformat(), user_id))

            conn.commit()
            logger.info(f"Premium установлен для {user_id} до {premium_until}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка установки premium для {user_id}: {e}")


def get_stats() -> dict:
    """Получает общую статистику использования бота."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]

            # Используем channel_stats как единый источник для общего числа анализов
            cursor.execute("SELECT SUM(analysis_count) FROM channel_stats")
            result = cursor.fetchone()
            total_requests = result[0] if result and result[0] else 0

            # Количество уникальных каналов
            cursor.execute("SELECT COUNT(*) FROM channel_stats")
            total_channels = cursor.fetchone()[0] or 0

            # Активный пользователь - тот, кто делал анализ в последние 30 дней
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE last_request_date >= date('now', '-30 days')
            """)
            active_users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users WHERE premium_until > datetime('now')")
            premium_users = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(paid_balance) FROM users")
            result = cursor.fetchone()
            total_paid_balance = result[0] if result and result[0] else 0

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

        return {
            "total_users": total_users,
            "total_requests": total_requests,
            "total_channels": total_channels,
            "active_users": active_users,
            "premium_users": premium_users,
            "total_paid_balance": total_paid_balance,
            "paid_users": paid_users,
            "top_users": top_users,
        }

    except sqlite3.Error as e:
        logger.error(f"Ошибка получения статистики: {e}", exc_info=True)
        # Попробуем хотя бы получить базовую статистику
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users")
                users_count = cursor.fetchone()[0]
                cursor.execute("SELECT SUM(analysis_count) FROM channel_stats")
                result = cursor.fetchone()
                analyses_count = result[0] if result and result[0] else 0

            return {
                "total_users": users_count,
                "total_requests": analyses_count,
                "total_channels": 0,
                "active_users": 0,
                "premium_users": 0,
                "total_paid_balance": 0,
                "paid_users": 0,
                "top_users": [],
            }
        except Exception as fallback_error:
            logger.error(f"Fallback статистики тоже не удался: {fallback_error}")
            return {
                "total_users": 0,
                "total_requests": 0,
                "total_channels": 0,
                "active_users": 0,
                "premium_users": 0,
                "total_paid_balance": 0,
                "paid_users": 0,
                "top_users": [],
            }


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in ADMIN_IDS


def get_all_user_ids() -> list[int]:
    """Возвращает список всех user_id из базы."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения user_id: {e}")
        return []


def get_paid_user_ids() -> list[int]:
    """Возвращает список user_id с paid_balance > 0."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE paid_balance > 0")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения платных user_id: {e}")
        return []


def log_channel_analysis(channel_key: str, title: str, subscribers: int = 0, analyzed_by: int | None = None) -> None:
    """Записывает анализ канала в статистику."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO channel_stats (channel_key, title, analysis_count, last_analyzed, subscribers, analyzed_by)
                VALUES (?, ?, 1, datetime('now'), ?, ?)
                ON CONFLICT(channel_key) DO UPDATE SET
                    title = excluded.title,
                    analysis_count = analysis_count + 1,
                    last_analyzed = datetime('now'),
                    subscribers = excluded.subscribers,
                    analyzed_by = excluded.analyzed_by
            """, (channel_key.lower(), title, subscribers, analyzed_by))
            conn.commit()
            logger.info(f"Статистика канала записана: {channel_key}, title={title}, subscribers={subscribers}, analyzed_by={analyzed_by}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка записи статистики канала {channel_key}: {e}")


def get_top_channels(limit: int = 5) -> list[tuple[str, str, int]]:
    """Возвращает топ каналов по количеству анализов."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT channel_key, title, analysis_count
                FROM channel_stats
                WHERE analysis_count > 0
                ORDER BY analysis_count DESC
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения топ каналов: {e}")
        return []


def get_top_channels_by_subscribers(limit: int = 10) -> list[tuple[str, str, int]]:
    """Возвращает топ каналов по количеству подписчиков."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT channel_key, title, subscribers
                FROM channel_stats
                WHERE subscribers > 0
                ORDER BY subscribers DESC
                LIMIT ?
            """, (limit,))
            result = cursor.fetchall()
            logger.debug(f"get_top_channels_by_subscribers: найдено {len(result)} каналов")
            return result
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения топ каналов по подписчикам: {e}")
        return []


def log_floodwait_event(user_id: int, channel_key: str, reason: str) -> None:
    """Логирует событие, когда пользователь не получил анализ из-за FloodWait/перегрузки."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO floodwait_events (user_id, channel_key, reason, created_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (user_id, channel_key.lower(), reason),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка записи floodwait-события: {e}")


def get_floodwait_stats(days: int = 1) -> dict:
    """
    Возвращает статистику по событиям FloodWait за последние N дней.

    Returns:
        {
            "total": общее кол-во событий,
            "users": кол-во уникальных пользователей
        }
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            offset = f"-{int(days)} day"
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(DISTINCT user_id) AS users
                FROM floodwait_events
                WHERE created_at >= datetime('now', ?)
                """,
                (offset,),
            )
            row = cursor.fetchone()
        if not row:
            return {"total": 0, "users": 0}
        total, users = row
        return {"total": total or 0, "users": users or 0}
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения статистики floodwait: {e}")
        return {"total": 0, "users": 0}


# --- Кэш анализов каналов ---

def was_analyzed_recently(channel_key: str, hours: int = 6) -> tuple[bool, str | None]:
    """
    Проверяет, анализировался ли канал недавно (для smart caching).
    
    Args:
        channel_key: Ключ канала.
        hours: Количество часов для проверки свежести.
    
    Returns:
        (был_ли_недавно, last_analyzed_timestamp)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT last_analyzed
                FROM channel_stats
                WHERE channel_key = ?
                AND last_analyzed > datetime('now', ?)
            """, (channel_key.lower(), f'-{hours} hours'))
            row = cursor.fetchone()

        if row:
            return True, row[0]
        return False, None
    except sqlite3.Error as e:
        logger.error(f"Ошибка проверки свежести анализа: {e}")
        return False, None


def get_cached_analysis(channel_key: str) -> dict | None:
    """
    Получает кэшированный анализ канала если он не истёк.

    Args:
        channel_key: Ключ канала (username или id).

    Returns:
        Словарь с данными или None если кэш не найден/истёк.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT title, stats_json, top_emojis_json, cached_at
                FROM channel_cache
                WHERE channel_key = ?
            """, (channel_key.lower(),))

            row = cursor.fetchone()

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

    except sqlite3.Error as e:
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
        with get_db_connection() as conn:
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
            logger.info(f"Кэш сохранён для канала: {channel_key}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка сохранения кэша для {channel_key}: {e}")

def add_pending_analysis(user_id: int, channel_key: str, channel_username: str, priority: int = 0) -> int:
    """
    Добавляет незавершённый анализ в очередь с приоритетом.

    Args:
        user_id: ID пользователя
        channel_key: Ключ канала (нормализованный)
        channel_username: Оригинальный юзернейм канала
        priority: Приоритет (2 = платный, 1 = premium, 0 = бесплатный)

    Returns:
        Позиция в очереди (начиная с 1), или 0 при ошибке
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO pending_analyses
                (user_id, channel_key, channel_username, status, priority, created_at)
                VALUES (?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
            """, (user_id, channel_key, channel_username, priority))
            conn.commit()
            logger.info(f"Добавлен незавершённый анализ: user={user_id}, channel={channel_key}, priority={priority}")

            # Возвращаем позицию в очереди
            return get_queue_position(user_id, channel_key)
    except sqlite3.Error as e:
        logger.error(f"Ошибка добавления анализа: {e}")
        return 0


def get_queue_position(user_id: int, channel_key: str) -> int:
    """
    Возвращает позицию анализа в очереди.
    Учитывает приоритеты: платные → premium → бесплатные.

    Returns:
        Позиция в очереди (1 = первый), или 0 если не найден
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Получаем приоритет и время создания текущего анализа
            cursor.execute("""
                SELECT priority, created_at FROM pending_analyses
                WHERE user_id = ? AND channel_key = ? AND status = 'pending'
            """, (user_id, channel_key))
            row = cursor.fetchone()

            if not row:
                return 0

            my_priority, my_created_at = row

            # Считаем сколько анализов впереди:
            # 1. Все с более высоким приоритетом
            # 2. Все с таким же приоритетом, но созданные раньше
            cursor.execute("""
                SELECT COUNT(*) FROM pending_analyses
                WHERE status = 'pending'
                AND (
                    priority > ?
                    OR (priority = ? AND created_at < ?)
                )
            """, (my_priority, my_priority, my_created_at))

            ahead = cursor.fetchone()[0]
            return ahead + 1  # +1 потому что позиция начинается с 1

    except sqlite3.Error as e:
        logger.error(f"Ошибка получения позиции в очереди: {e}")
        return 0


def get_queue_stats() -> dict:
    """
    Возвращает статистику очереди.

    Returns:
        {
            "total": общее количество в очереди,
            "paid": количество платных (priority=2),
            "premium": количество premium (priority=1),
            "free": количество бесплатных (priority=0),
            "processing": количество в обработке
        }
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') as total,
                    COUNT(*) FILTER (WHERE status = 'pending' AND priority = 2) as paid,
                    COUNT(*) FILTER (WHERE status = 'pending' AND priority = 1) as premium,
                    COUNT(*) FILTER (WHERE status = 'pending' AND priority = 0) as free,
                    COUNT(*) FILTER (WHERE status = 'processing') as processing
                FROM pending_analyses
            """)
            row = cursor.fetchone()

            if row:
                return {
                    "total": row[0] or 0,
                    "paid": row[1] or 0,
                    "premium": row[2] or 0,
                    "free": row[3] or 0,
                    "processing": row[4] or 0
                }
            return {"total": 0, "paid": 0, "premium": 0, "free": 0, "processing": 0}

    except sqlite3.Error as e:
        logger.error(f"Ошибка получения статистики очереди: {e}")
        return {"total": 0, "paid": 0, "premium": 0, "free": 0, "processing": 0}


def get_next_pending_batch(limit: int = 5) -> list[tuple]:
    """
    Получает следующую порцию анализов для обработки с учётом приоритетов.

    Порядок: платные (2) → premium (1) → бесплатные (0), затем по времени создания.
    Берёт только записи старше 30 секунд (чтобы не конфликтовать с текущими запросами).

    Returns:
        Список кортежей (id, user_id, channel_key, channel_username, priority)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, channel_key, channel_username, priority
                FROM pending_analyses
                WHERE status = 'pending'
                AND created_at < datetime('now', '-30 seconds')
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения batch из очереди: {e}")
        return []


def get_user_pending_queue(user_id: int) -> list[dict]:
    """
    Получает все анализы пользователя в очереди с их позициями.

    Returns:
        Список словарей с channel_username и position
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Получаем все pending анализы пользователя
            cursor.execute("""
                SELECT channel_key, channel_username, priority, created_at
                FROM pending_analyses
                WHERE user_id = ? AND status = 'pending'
                ORDER BY created_at ASC
            """, (user_id,))

            user_analyses = cursor.fetchall()

            if not user_analyses:
                return []

            result = []
            for channel_key, channel_username, priority, created_at in user_analyses:
                # Считаем позицию для каждого
                cursor.execute("""
                    SELECT COUNT(*) FROM pending_analyses
                    WHERE status = 'pending'
                    AND (
                        priority > ?
                        OR (priority = ? AND created_at < ?)
                    )
                """, (priority, priority, created_at))

                ahead = cursor.fetchone()[0]
                position = ahead + 1

                result.append({
                    "channel_username": channel_username,
                    "position": position,
                    "priority": priority
                })

            return result

    except sqlite3.Error as e:
        logger.error(f"Ошибка получения очереди пользователя: {e}")
        return []


def get_pending_analyses_for_user(user_id: int) -> list[dict]:
    """Получает все незавершённые анализы пользователя."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, channel_key, channel_username 
                FROM pending_analyses 
                WHERE user_id = ? AND status = 'pending'
                ORDER BY created_at DESC
            """, (user_id,))
            results = cursor.fetchall()
            return [
                {"id": row[0], "channel_key": row[1], "channel_username": row[2]}
                for row in results
            ]
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения анализов: {e}")
        return []


def update_pending_status(analysis_id: int, status: str) -> None:
    """Обновляет статус pending анализа."""
    try:
        with get_db_connection() as conn:
            conn.execute("UPDATE pending_analyses SET status = ? WHERE id = ?", (status, analysis_id))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка обновления статуса анализа {analysis_id}: {e}")


def remove_pending_analysis(analysis_id: int) -> None:
    """Удаляет завершённый анализ из очереди."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM pending_analyses WHERE id = ?", (analysis_id,))
            conn.commit()
            logger.info(f"Удалён анализ {analysis_id}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка удаления анализа: {e}")


def get_top_paid_users(limit: int = 10) -> list[dict]:
    """Получает топ платящих пользователей."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    u.user_id,
                    u.username,
                    u.paid_balance,
                    COUNT(p.id) as payment_count,
                    SUM(p.stars) as total_stars
                FROM users u
                LEFT JOIN payments p ON u.user_id = p.user_id
                WHERE u.paid_balance > 0 OR p.id IS NOT NULL
                GROUP BY u.user_id
                ORDER BY SUM(p.stars) DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            return [
                {
                    'user_id': row[0],
                    'username': row[1],
                    'paid_balance': row[2],
                    'payment_count': row[3] or 0,
                    'total_stars': row[4] or 0
                }
                for row in rows
            ]
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения топ платящих: {e}")
        return []


def get_payment_stats() -> dict:
    """Получает статистику по платежам."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Общая статистика
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT user_id) as unique_users,
                    COUNT(*) as total_payments,
                    SUM(stars) as total_stars,
                    AVG(stars) as avg_stars
                FROM payments
            """)
            
            stats = cursor.fetchone()
            return {
                'unique_users': stats[0] or 0,
                'total_payments': stats[1] or 0,
                'total_stars': stats[2] or 0,
                'avg_stars': round(stats[3] or 0, 1)
            }
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения статистики платежей: {e}")
        return {}


def log_buy_click(user_id: int, action: str) -> None:
    """Логирует клик по кнопке покупки (воронка)."""
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO buy_clicks (user_id, action) VALUES (?, ?)",
                (user_id, action),
            )
    except sqlite3.Error as e:
        logger.error(f"Ошибка записи buy_click: {e}")


def get_buy_funnel() -> dict:
    """Возвращает воронку покупок: открыли меню -> выбрали пакет -> оплатили."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT action, COUNT(*) as cnt, COUNT(DISTINCT user_id) as users
                FROM buy_clicks
                GROUP BY action
                ORDER BY cnt DESC
            """)
            rows = cursor.fetchall()
            return {row[0]: {'clicks': row[1], 'users': row[2]} for row in rows}
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения воронки: {e}")
        return {}


def get_users_with_pending_and_balance() -> list[dict]:
    """Получает пользователей с незавершёнными анализами и платёжным балансом."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT 
                    u.user_id,
                    u.username,
                    u.paid_balance,
                    COUNT(pa.id) as pending_count
                FROM users u
                LEFT JOIN pending_analyses pa ON u.user_id = pa.user_id AND pa.status = 'pending'
                LEFT JOIN payments p ON u.user_id = p.user_id
                WHERE (u.paid_balance > 0 OR p.id IS NOT NULL)
                AND pa.id IS NOT NULL
                GROUP BY u.user_id
                ORDER BY COUNT(pa.id) DESC
            """)
            
            rows = cursor.fetchall()
            return [
                {
                    'user_id': row[0],
                    'username': row[1],
                    'paid_balance': row[2],
                    'pending_count': row[3]
                }
                for row in rows
            ]
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения пользователей с ожиданиями: {e}")
        return []


def log_payment(user_id: int, stars: int, amount: str = "", payment_method: str = "telegram_stars", notes: str = "") -> None:
    """Логирует платёж в таблицу payments."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO payments (user_id, stars, amount, payment_method, status, notes)
                VALUES (?, ?, ?, ?, 'completed', ?)
            """, (user_id, stars, amount, payment_method, notes))
            conn.commit()
            logger.info(f"Платёж залогирован: user_id={user_id}, stars={stars}, method={payment_method}")
    except sqlite3.Error as e:
        logger.error(f"Ошибка логирования платежа: {e}")


def get_all_channels_for_admin() -> list[dict]:
    """
    Получает все каналы из базы для админ-панели.
    Возвращает список словарей с channel_key, title, analysis_count, subscribers.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT channel_key, title, analysis_count, subscribers
                FROM channel_stats
                WHERE title IS NOT NULL AND title != ''
                ORDER BY analysis_count DESC, subscribers DESC
            """)
            
            channels = []
            for row in cursor.fetchall():
                channels.append({
                    'channel_key': row[0],
                    'title': row[1],
                    'analysis_count': row[2] or 0,
                    'subscribers': row[3] or 0
                })
            
            return channels
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения списка каналов: {e}")
        return []


async def cleanup_old_records_async(days: int = 30) -> int:
    """Асинхронно удаляет записи floodwait_events батчами по 1000 для избежания блокировки БД.

    Returns:
        Количество удалённых записей.
    """
    import asyncio
    total_deleted = 0
    batch_size = 1000

    try:
        while True:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Удаляем батчами по 1000 записей
                cursor.execute(
                    f"DELETE FROM floodwait_events WHERE rowid IN "
                    f"(SELECT rowid FROM floodwait_events WHERE created_at < datetime('now', ?) LIMIT {batch_size})",
                    (f"-{days} days",),
                )
                deleted = cursor.rowcount
                conn.commit()

            if deleted == 0:
                break

            total_deleted += deleted
            # Пауза между батчами для снижения нагрузки на БД
            await asyncio.sleep(0.1)

        if total_deleted > 0:
            logger.info(f"Очищено {total_deleted} старых floodwait_events (старше {days} дней)")
        return total_deleted
    except sqlite3.Error as e:
        logger.error(f"Ошибка очистки старых записей: {e}")
        return total_deleted


def cleanup_old_records(days: int = 30) -> int:
    """Синхронно удаляет записи floodwait_events батчами по 1000.

    Returns:
        Количество удалённых записей.
    """
    import time
    total_deleted = 0
    batch_size = 1000

    try:
        while True:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM floodwait_events WHERE rowid IN "
                    f"(SELECT rowid FROM floodwait_events WHERE created_at < datetime('now', ?) LIMIT {batch_size})",
                    (f"-{days} days",),
                )
                deleted = cursor.rowcount
                conn.commit()

            if deleted == 0:
                break

            total_deleted += deleted
            time.sleep(0.1)  # Пауза между батчами

        if total_deleted > 0:
            logger.info(f"Очищено {total_deleted} старых floodwait_events (старше {days} дней)")
        return total_deleted
    except sqlite3.Error as e:
        logger.error(f"Ошибка очистки старых записей: {e}")
        return total_deleted
