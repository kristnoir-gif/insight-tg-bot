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

# --- SSL обход для macOS ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# --- Telegram API ---
API_ID: Final[int] = int(os.getenv("API_ID", "0"))
API_HASH: Final[str] = os.getenv("API_HASH", "")
BOT_TOKEN: Final[str] = os.getenv("BOT_TOKEN", "")
SESSION_NAME: Final[str] = os.getenv("SESSION_NAME", "user_session")

# --- Временная зона ---
MOSCOW_TZ: Final[timezone] = timezone(timedelta(hours=3))

# --- Визуализация ---
DPI: Final[int] = 150
MAX_WORDS_CLOUD: Final[int] = 200
MAX_WORDS_SENTIMENT: Final[int] = 100
CLOUD_WIDTH: Final[int] = 1000
CLOUD_HEIGHT: Final[int] = 600
FIGURE_SIZE: Final[tuple[int, int]] = (12, 7)
BACKGROUND_COLOR: Final[str] = "#f8f9fa"
WATERMARK_TEXT: Final[str] = "@insight_tg_bot"
WATERMARK_COLOR: Final[str] = "#FFC0CB"

# --- Анализ ---
DEFAULT_MESSAGE_LIMIT: Final[int] = 500


def validate_config() -> bool:
    """Проверяет наличие обязательных настроек."""
    if not API_ID or not API_HASH or not BOT_TOKEN:
        logging.error("Не заданы API_ID, API_HASH или BOT_TOKEN. Проверьте .env файл.")
        return False
    return True
