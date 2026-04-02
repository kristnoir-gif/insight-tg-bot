"""
Конфигурация приложения.
Загружает настройки из переменных окружения.
"""
import os
import ssl
import logging
from datetime import timezone, timedelta
from typing import Final

from dotenv import load_dotenv

load_dotenv()

# --- Логирование ---
LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_LEVEL: Final[int] = logging.INFO
LOG_FILE: Final[str] = os.getenv("LOG_FILE", "bot.log")
LOG_MAX_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT: Final[int] = 5               # 5 ротаций = 50 MB макс

# --- Telegram API ---
API_ID: Final[int] = int(os.getenv("API_ID", "0"))
API_HASH: Final[str] = os.getenv("API_HASH", "")
BOT_TOKEN: Final[str] = os.getenv("BOT_TOKEN", "")
SESSION_NAME: Final[str] = os.getenv("SESSION_NAME", "")
BACKUP_SESSION_NAME: Final[str] = os.getenv("BACKUP_SESSION_NAME", "")
THIRD_SESSION_NAME: Final[str] = os.getenv("THIRD_SESSION_NAME", "")

# --- Прокси для избежания FloodWait (опционально) ---
# Формат: socks5://user:pass@host:port или socks5://host:port или http://host:port
# Оставьте пустым если прокси не нужен
_PROXY_MAIN_STR: Final[str | None] = os.getenv("PROXY_MAIN")
_PROXY_BACKUP_STR: Final[str | None] = os.getenv("PROXY_BACKUP")
_PROXY_THIRD_STR: Final[str | None] = os.getenv("PROXY_THIRD")


def _parse_proxy(proxy_str: str | None) -> dict | None:
    """
    Парсит строку прокси в формат для Telethon.

    Формат: protocol://[user:pass@]host:port
    Примеры:
        socks5://1.2.3.4:1080
        socks5://user:password@1.2.3.4:1080
        http://1.2.3.4:8080

    Returns:
        dict для Telethon или None если прокси не задан
    """
    if not proxy_str:
        return None

    try:
        # Убираем пробелы
        proxy_str = proxy_str.strip()

        # Определяем тип прокси
        if proxy_str.startswith('socks5://'):
            proxy_type = 'socks5'
            rest = proxy_str[9:]
        elif proxy_str.startswith('socks4://'):
            proxy_type = 'socks4'
            rest = proxy_str[9:]
        elif proxy_str.startswith('http://'):
            proxy_type = 'http'
            rest = proxy_str[7:]
        elif proxy_str.startswith('https://'):
            proxy_type = 'http'
            rest = proxy_str[8:]
        else:
            # Если нет протокола - считаем socks5
            proxy_type = 'socks5'
            rest = proxy_str

        # Парсим user:pass@host:port или host:port
        username = None
        password = None

        if '@' in rest:
            auth, hostport = rest.rsplit('@', 1)
            if ':' in auth:
                username, password = auth.split(':', 1)
            else:
                username = auth
        else:
            hostport = rest

        # Парсим host:port
        if ':' in hostport:
            host, port_str = hostport.rsplit(':', 1)
            port = int(port_str)
        else:
            host = hostport
            port = 1080 if proxy_type.startswith('socks') else 8080

        result = {
            'proxy_type': proxy_type,
            'addr': host,
            'port': port,
        }

        if username:
            result['username'] = username
        if password:
            result['password'] = password

        logging.info(f"Прокси настроен: {proxy_type}://{host}:{port}" +
                    (f" (auth: {username})" if username else ""))

        return result

    except (ValueError, IndexError) as e:
        logging.error(f"Ошибка парсинга прокси '{proxy_str}': {e}")
        return None


# Прокси для клиентов (в формате Telethon)
PROXY_MAIN: Final[dict | None] = _parse_proxy(_PROXY_MAIN_STR)
PROXY_BACKUP: Final[dict | None] = _parse_proxy(_PROXY_BACKUP_STR)
PROXY_THIRD: Final[dict | None] = _parse_proxy(_PROXY_THIRD_STR)

# --- Временная зона ---
MOSCOW_TZ: Final[timezone] = timezone(timedelta(hours=3))

# --- Визуализация (Spotify Wrapped style) ---
DPI: Final[int] = 150
MAX_WORDS_CLOUD: Final[int] = 200
MAX_WORDS_SENTIMENT: Final[int] = 100
CLOUD_WIDTH: Final[int] = 900
CLOUD_HEIGHT: Final[int] = 1100
FIGURE_SIZE: Final[tuple[float, float]] = (7.2, 12.8)  # 1080×1920 stories format (9:16)
BACKGROUND_COLOR: Final[str] = "#0d1117"
ACCENT_GREEN: Final[str] = "#1DB954"
ACCENT_PINK: Final[str] = "#e91e8c"
ACCENT_PURPLE: Final[str] = "#8b5cf6"
ACCENT_BLUE: Final[str] = "#58a6ff"
TEXT_WHITE: Final[str] = "#f0f6fc"
TEXT_GRAY: Final[str] = "#8b949e"
WATERMARK_TEXT: Final[str] = "Создано с помощью бота\n@insight_tg_bot"
WATERMARK_COLOR: Final[str] = "#58a6ff"

# --- Анализ ---
# Лимиты сообщений для анализа
DEFAULT_MESSAGE_LIMIT: Final[int] = 500  # Полный анализ (платные пользователи)
FREE_MESSAGE_LIMIT: Final[int] = 150     # Облегчённый анализ (бесплатные пользователи)

# --- Тайминги и кэш ---
RATE_LIMIT_SECONDS: Final[int] = 120            # Между запросами пользователя (снижено для высокой нагрузки)
RATE_LIMIT_NEW_USER_SECONDS: Final[int] = 300   # Рейт-лимит для новых юзеров (< 1 анализа) — 5 мин
FLOODWAIT_PENALTY_SECONDS: Final[int] = 3600    # После FloodWait для пользователя
CACHE_TTL_LITE: Final[int] = 3600               # In-memory кэш lite (1 час)
CACHE_TTL_FULL: Final[int] = 14400              # In-memory кэш full (4 часа)
DISK_CACHE_TTL: Final[int] = 86400              # Дисковый кэш (24 часа)
DISK_CACHE_TTL_LITE: Final[int] = 172800        # Дисковый кэш lite (48 часов)
FETCH_DELAY_EVERY_N: Final[int] = 100           # Пауза каждые N сообщений
FETCH_DELAY_SECONDS: Final[float] = 1.0         # Длительность паузы
PENDING_CHECK_INTERVAL: Final[int] = 15         # Проверка pending каждые 15 сек
PENDING_BATCH_SIZE: Final[int] = 10             # Количество анализов за раз

# --- HTTP / Метрики ---
METRICS_PORT: Final[int] = 8080                  # Порт для /health и /metrics
MAX_CONCURRENT_ANALYSES: Final[int] = 20         # Максимум параллельных анализов
BOT_VERSION: Final[str] = "2.0.0"

# --- Веб-парсинг ---
WEB_PARSER_MAX_PAGES: Final[int] = 50            # Максимум страниц при веб-парсинге
CACHE_DIR: Final[str] = "cache"                   # Директория дискового кэша


# --- LLM (OpenAI-совместимый API: Groq, Alibaba DashScope, OpenRouter и др.) ---
LLM_API_KEY: Final[str] = os.getenv("LLM_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
LLM_MODEL: Final[str] = os.getenv("LLM_MODEL", "qwen-max")
LLM_BASE_URL: Final[str] = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MAX_TOKENS: Final[int] = 4000  # Макс длина ответа
LLM_TIMEOUT: Final[int] = 120      # Таймаут запроса к LLM (секунды)

# --- Sentry (опционально, DSN из .env) ---
SENTRY_DSN: Final[str] = os.getenv("SENTRY_DSN", "")

# --- Базовые оффсеты статистики (потеряны при миграции сервера 2026-02-12) ---
STATS_OFFSET_USERS: Final[int] = 2837
STATS_OFFSET_ANALYSES: Final[int] = 2130
STATS_OFFSET_STARS: Final[int] = 1734

# --- Администраторы ---
_admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: Final[set[int]] = set(int(x.strip()) for x in _admin_ids_str.split(",") if x.strip())
ADMIN_ID: Final[int] = int(os.getenv("ADMIN_ID", "0"))


def validate_config() -> bool:
    """Проверяет наличие обязательных настроек."""
    if not API_ID or not API_HASH or not BOT_TOKEN:
        logging.error("Не заданы API_ID, API_HASH или BOT_TOKEN. Проверьте .env файл.")
        return False
    if not SESSION_NAME:
        logging.warning("SESSION_NAME не задан. Укажите имя сессии в .env файле.")
    return True
