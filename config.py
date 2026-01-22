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
SESSION_NAME: Final[str] = os.getenv("SESSION_NAME", "ltdnt_session")
BACKUP_SESSION_NAME: Final[str] = os.getenv("BACKUP_SESSION_NAME", "211766470_telethon")
THIRD_SESSION_NAME: Final[str] = os.getenv("THIRD_SESSION_NAME", "kristina_user")

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

# --- Визуализация ---
DPI: Final[int] = 150
MAX_WORDS_CLOUD: Final[int] = 200
MAX_WORDS_SENTIMENT: Final[int] = 100
CLOUD_WIDTH: Final[int] = 1000
CLOUD_HEIGHT: Final[int] = 600
FIGURE_SIZE: Final[tuple[int, int]] = (12, 7)
BACKGROUND_COLOR: Final[str] = "#f8f9fa"
WATERMARK_TEXT: Final[str] = "@insight_tg_bot"
WATERMARK_COLOR: Final[str] = "#752E53"

# --- Анализ ---
# Баланс между качеством и нагрузкой: 400 сообщений на анализ.
DEFAULT_MESSAGE_LIMIT: Final[int] = 400  # было 300


def validate_config() -> bool:
    """Проверяет наличие обязательных настроек."""
    if not API_ID or not API_HASH or not BOT_TOKEN:
        logging.error("Не заданы API_ID, API_HASH или BOT_TOKEN. Проверьте .env файл.")
        return False
    return True
