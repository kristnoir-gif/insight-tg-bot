"""
ClientPool — управление пулом Telegram клиентов с балансировкой и кэшированием.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from collections import OrderedDict

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from analyzer import analyze_channel, AnalysisResult, AnalysisError

logger = logging.getLogger(__name__)


@dataclass
class CachedResult:
    """Кэшированный результат анализа."""
    result: AnalysisResult
    created_at: float

    def is_expired(self, ttl_seconds: int = 1800) -> bool:
        """Проверяет истёк ли TTL (по умолчанию 30 минут)."""
        return time.time() - self.created_at > ttl_seconds


@dataclass
class ClientAccount:
    """Аккаунт Telegram с метаданными."""
    name: str
    client: TelegramClient
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    cooldown_until: float = 0.0  # Unix timestamp когда закончится FloodWait
    total_requests: int = 0
    failed_requests: int = 0
    last_used: float = 0.0

    @property
    def is_available(self) -> bool:
        """Доступен ли аккаунт (не в cooldown и семафор свободен)."""
        return time.time() >= self.cooldown_until

    @property
    def is_busy(self) -> bool:
        """Занят ли аккаунт (семафор заблокирован)."""
        return self.semaphore.locked()

    @property
    def cooldown_remaining(self) -> int:
        """Сколько секунд осталось до конца cooldown."""
        remaining = self.cooldown_until - time.time()
        return max(0, int(remaining))

    def set_cooldown(self, seconds: int) -> None:
        """Устанавливает cooldown на указанное количество секунд."""
        self.cooldown_until = time.time() + seconds + 5  # +5 сек запас
        logger.warning(f"Account {self.name}: cooldown set for {seconds}s")

    def clear_cooldown(self) -> None:
        """Сбрасывает cooldown."""
        self.cooldown_until = 0.0


class AnalysisCache:
    """LRU кэш для результатов анализа."""

    def __init__(self, max_size: int = 100, ttl_seconds: int = 1800):
        self._cache: OrderedDict[str, CachedResult] = OrderedDict()
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds

    def _normalize_key(self, channel: str | int) -> str:
        """Нормализует ключ канала."""
        key = str(channel).lower().lstrip('@').split('/')[-1].strip()
        return key

    def get(self, channel: str | int) -> Optional[AnalysisResult]:
        """Получает результат из кэша если не истёк."""
        key = self._normalize_key(channel)

        if key not in self._cache:
            return None

        cached = self._cache[key]
        if cached.is_expired(self._ttl_seconds):
            del self._cache[key]
            logger.debug(f"Cache expired for {key}")
            return None

        # Перемещаем в конец (LRU)
        self._cache.move_to_end(key)
        logger.info(f"Cache hit for {key}")
        return cached.result

    def set(self, channel: str | int, result: AnalysisResult) -> None:
        """Сохраняет результат в кэш."""
        key = self._normalize_key(channel)

        # Удаляем старые записи если превышен лимит
        while len(self._cache) >= self._max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            logger.debug(f"Cache evicted {oldest_key}")

        self._cache[key] = CachedResult(result=result, created_at=time.time())
        logger.info(f"Cached result for {key}")

    def invalidate(self, channel: str | int) -> None:
        """Удаляет запись из кэша."""
        key = self._normalize_key(channel)
        if key in self._cache:
            del self._cache[key]

    def clear(self) -> None:
        """Очищает весь кэш."""
        self._cache.clear()

    def stats(self) -> dict:
        """Возвращает статистику кэша."""
        now = time.time()
        valid_count = sum(1 for c in self._cache.values() if not c.is_expired(self._ttl_seconds))
        return {
            "total": len(self._cache),
            "valid": valid_count,
            "expired": len(self._cache) - valid_count,
            "max_size": self._max_size,
            "ttl_seconds": self._ttl_seconds,
        }


class ClientPool:
    """
    Пул Telegram клиентов с балансировкой нагрузки.

    Особенности:
    - Кэширование результатов (30 мин TTL)
    - Автоматический выбор наименее загруженного аккаунта
    - Per-account Semaphore(1) — строго один запрос на аккаунт
    - Автоматический переход на следующий аккаунт при FloodWait
    """

    def __init__(self, cache_ttl: int = 7200, cache_max_size: int = 200):  # 2 часа TTL, 200 записей
        self._accounts: list[ClientAccount] = []
        self._cache = AnalysisCache(max_size=cache_max_size, ttl_seconds=cache_ttl)
        self._lock = asyncio.Lock()

    def add_account(self, name: str, client: TelegramClient) -> None:
        """Добавляет аккаунт в пул."""
        account = ClientAccount(name=name, client=client)
        self._accounts.append(account)
        logger.info(f"Added account to pool: {name}")

    def get_account_by_name(self, name: str) -> Optional[ClientAccount]:
        """Получает аккаунт по имени."""
        for acc in self._accounts:
            if acc.name == name:
                return acc
        return None

    def _select_best_account(self) -> Optional[ClientAccount]:
        """
        Выбирает лучший аккаунт для запроса.

        Приоритет:
        1. Доступные и не занятые
        2. Наименьшее количество запросов (балансировка)
        3. Давно не использовавшийся
        """
        now = time.time()

        # Фильтруем доступные аккаунты
        available = [acc for acc in self._accounts if acc.is_available]

        if not available:
            return None

        # Сортируем: сначала свободные, потом по количеству запросов, потом по времени использования
        available.sort(key=lambda a: (
            a.is_busy,  # Свободные первые
            a.total_requests,  # Меньше запросов — лучше
            a.last_used,  # Давно не использовавшийся — лучше
        ))

        return available[0]

    async def analyze(
        self,
        channel: str | int,
        use_cache: bool = True,
        user_id: int = 0,
        is_private: bool = False,
        lite_mode: bool = False,
        message_limit: int = 400,
    ) -> tuple[AnalysisResult | None, str | None]:
        """
        Выполняет анализ канала с балансировкой и кэшированием.

        Args:
            channel: Username или ID канала
            use_cache: Использовать ли кэш
            user_id: ID пользователя (для логирования)
            is_private: Является ли канал приватным (требует присоединения)
            lite_mode: Облегчённый режим — только облако слов (для бесплатных)
            message_limit: Лимит сообщений для анализа

        Returns:
            (result, error_message) — результат или сообщение об ошибке
        """
        # 1. Проверяем кэш
        if use_cache:
            cached = self._cache.get(channel)
            if cached:
                logger.info(f"Returning cached result for {channel} (user={user_id})")
                cached.from_cache = True
                return cached, None

        # 2. Выбираем аккаунт
        account = self._select_best_account()

        if not account:
            # Все аккаунты в cooldown
            min_cooldown = min(acc.cooldown_remaining for acc in self._accounts) if self._accounts else 0
            return None, f"all_cooldown:{min_cooldown}"

        # 3. Пытаемся выполнить анализ с выбранным аккаунтом
        tried_accounts: set[str] = set()

        while account and account.name not in tried_accounts:
            tried_accounts.add(account.name)

            try:
                async with account.semaphore:
                    account.last_used = time.time()
                    account.total_requests += 1

                    mode_str = "lite" if lite_mode else "full"
                    logger.info(f"Analyzing {channel} with account {account.name} (user={user_id}, mode={mode_str}, limit={message_limit})")

                    result = await analyze_channel(
                        account.client,
                        channel,
                        limit=message_limit,
                        is_private=is_private,
                        lite_mode=lite_mode
                    )

                    if result and result.cloud_path:
                        # Успех — кэшируем
                        self._cache.set(channel, result)
                        return result, None
                    else:
                        return None, "empty_result"

            except FloodWaitError as e:
                account.failed_requests += 1
                account.set_cooldown(int(e.seconds))
                logger.warning(f"FloodWait {e.seconds}s on {account.name}, trying next account")

                # Пробуем следующий аккаунт
                account = self._select_best_account()
                if account and account.name in tried_accounts:
                    account = None  # Все аккаунты уже пробовали

            except AnalysisError as e:
                account.failed_requests += 1
                error_str = str(e).lower()

                if "flood" in error_str or "wait of" in error_str:
                    # FloodWait в тексте ошибки
                    account.set_cooldown(300)  # 5 минут по умолчанию
                    account = self._select_best_account()
                    if account and account.name in tried_accounts:
                        account = None
                elif "restricted" in error_str or "api access" in error_str:
                    # Ошибка доступа - канал недоступен для user API
                    return None, "Не удалось проанализировать канал: Канал ограничен для анализа"
                else:
                    # Другая ошибка — не пробуем другие аккаунты
                    return None, str(e)

            except Exception as e:
                account.failed_requests += 1
                logger.exception(f"Unexpected error analyzing {channel} with {account.name}")
                return None, str(e)

        # Все аккаунты в cooldown или пробовали
        if self._accounts:
            min_cooldown = min(acc.cooldown_remaining for acc in self._accounts)
            return None, f"all_cooldown:{min_cooldown}"

        return None, "no_accounts"

    def clear_cooldowns(self) -> None:
        """Сбрасывает cooldown всех аккаунтов."""
        for acc in self._accounts:
            acc.clear_cooldown()
        logger.info("All cooldowns cleared")

    def clear_cache(self) -> None:
        """Очищает кэш результатов."""
        self._cache.clear()
        logger.info("Cache cleared")

    def status(self) -> dict:
        """Возвращает статус пула."""
        now = time.time()
        accounts_status = []

        for acc in self._accounts:
            accounts_status.append({
                "name": acc.name,
                "available": acc.is_available,
                "busy": acc.is_busy,
                "cooldown_remaining": acc.cooldown_remaining,
                "total_requests": acc.total_requests,
                "failed_requests": acc.failed_requests,
            })

        available_count = sum(1 for a in accounts_status if a["available"] and not a["busy"])

        return {
            "accounts": accounts_status,
            "total_accounts": len(self._accounts),
            "available_accounts": available_count,
            "cache": self._cache.stats(),
        }

    def status_text(self) -> str:
        """Возвращает статус пула в виде текста."""
        status = self.status()
        lines = ["📊 *Статус ClientPool:*\n"]

        for i, acc in enumerate(status["accounts"], 1):
            if not acc["available"]:
                icon = "⏳"
                state = f"cooldown {acc['cooldown_remaining']}s"
            elif acc["busy"]:
                icon = "🔄"
                state = "занят"
            else:
                icon = "✅"
                state = "доступен"

            lines.append(
                f"{i}. {acc['name']}: {icon} {state}\n"
                f"   📈 {acc['total_requests']} запросов, {acc['failed_requests']} ошибок"
            )

        lines.append(f"\n🔢 Доступно: {status['available_accounts']}/{status['total_accounts']}")

        cache = status["cache"]
        lines.append(f"💾 Кэш: {cache['valid']}/{cache['max_size']} записей (TTL: {cache['ttl_seconds']//60} мин)")

        return "\n".join(lines)


# Глобальный экземпляр пула
_client_pool: ClientPool | None = None


def get_client_pool() -> ClientPool:
    """Возвращает глобальный пул клиентов."""
    global _client_pool
    if _client_pool is None:
        _client_pool = ClientPool()
    return _client_pool


def init_client_pool(cache_ttl: int = 1800) -> ClientPool:
    """Инициализирует глобальный пул клиентов."""
    global _client_pool
    _client_pool = ClientPool(cache_ttl=cache_ttl)
    return _client_pool
