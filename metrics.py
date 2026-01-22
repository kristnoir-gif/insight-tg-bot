"""
Prometheus метрики для мониторинга бота.
"""
from prometheus_client import Counter, Gauge, Histogram, Info, generate_latest, CONTENT_TYPE_LATEST
from aiohttp import web

# === Счётчики (Counter) ===

# Общее количество запросов анализа
analysis_requests_total = Counter(
    'bot_analysis_requests_total',
    'Total number of analysis requests',
    ['status']  # success, error, cached, floodwait
)

# Количество FloodWait событий
floodwait_events_total = Counter(
    'bot_floodwait_events_total',
    'Total FloodWait events',
    ['account']  # main, backup, third
)

# Платежи
payments_total = Counter(
    'bot_payments_total',
    'Total payments received',
    ['pack']  # pack_3, pack_10, pack_50, donate
)

payments_stars_total = Counter(
    'bot_payments_stars_total',
    'Total stars received from payments'
)

# === Gauges (текущие значения) ===

# Количество активных пользователей за 24ч
active_users_24h = Gauge(
    'bot_active_users_24h',
    'Active users in last 24 hours'
)

# Статус аккаунтов
account_status = Gauge(
    'bot_account_status',
    'Account availability (1=available, 0=cooldown)',
    ['account']
)

# Cooldown оставшееся время
account_cooldown_seconds = Gauge(
    'bot_account_cooldown_seconds',
    'Remaining cooldown time in seconds',
    ['account']
)

# Размер кэша
cache_size = Gauge(
    'bot_cache_size',
    'Number of cached analysis results'
)

# Количество запросов в очереди
queue_size = Gauge(
    'bot_queue_size',
    'Number of requests waiting in queue'
)

# Pending анализы (не выполненные)
pending_analyses = Gauge(
    'bot_pending_analyses',
    'Number of pending analyses waiting for retry'
)

# === Histograms ===

# Время выполнения анализа
analysis_duration_seconds = Histogram(
    'bot_analysis_duration_seconds',
    'Time spent on channel analysis',
    buckets=[10, 30, 60, 90, 120, 180, 300, 600]
)

# === Info ===

bot_info = Info(
    'bot',
    'Bot information'
)


def init_metrics(bot_username: str = "insight_tg_bot", version: str = "1.0.0"):
    """Инициализирует информацию о боте."""
    bot_info.info({
        'username': bot_username,
        'version': version,
    })


async def metrics_handler(request: web.Request) -> web.Response:
    """HTTP handler для /metrics endpoint."""
    return web.Response(
        body=generate_latest(),
        content_type="text/plain",
        charset="utf-8"
    )


def setup_metrics_endpoint(app: web.Application) -> None:
    """Добавляет /metrics endpoint в aiohttp приложение."""
    app.router.add_get('/metrics', metrics_handler)


# === Вспомогательные функции ===

def record_analysis(status: str, duration: float = None):
    """Записывает результат анализа."""
    analysis_requests_total.labels(status=status).inc()
    if duration is not None:
        analysis_duration_seconds.observe(duration)


def record_floodwait(account: str):
    """Записывает FloodWait событие."""
    floodwait_events_total.labels(account=account).inc()


def record_payment(pack: str, stars: int):
    """Записывает платёж."""
    payments_total.labels(pack=pack).inc()
    payments_stars_total.inc(stars)


def update_account_metrics(accounts_status: list[dict]):
    """Обновляет метрики аккаунтов из ClientPool.status()."""
    for acc in accounts_status:
        name = acc['name']
        is_available = 1 if acc['available'] and not acc['busy'] else 0
        account_status.labels(account=name).set(is_available)
        account_cooldown_seconds.labels(account=name).set(acc['cooldown_remaining'])


def update_cache_metrics(cache_stats: dict):
    """Обновляет метрики кэша."""
    cache_size.set(cache_stats.get('valid', 0))
