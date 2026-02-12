"""Tests for handlers/common.py — rate limiting logic."""
import time
import asyncio
from unittest.mock import patch

from handlers.common import (
    _check_rate_limit,
    _update_rate_limit,
    _mark_user_floodwait,
    check_and_update_rate_limit,
    cleanup_rate_limits,
    _user_last_request,
    _user_got_floodwait,
)
from config import RATE_LIMIT_SECONDS, FLOODWAIT_PENALTY_SECONDS


def _clear_rate_limits():
    """Helper to clear rate limit state between tests."""
    _user_last_request.clear()
    _user_got_floodwait.clear()


def test_rate_limit_allows_first_request():
    """First request from a user should always be allowed."""
    _clear_rate_limits()
    can_proceed, wait = _check_rate_limit(12345)
    assert can_proceed is True
    assert wait == 0


def test_rate_limit_blocks_rapid_request():
    """Second request within RATE_LIMIT_SECONDS should be blocked."""
    _clear_rate_limits()
    _update_rate_limit(12345)
    can_proceed, wait = _check_rate_limit(12345)
    assert can_proceed is False
    assert wait > 0


def test_rate_limit_allows_after_expiry():
    """Request after rate limit period should be allowed."""
    _clear_rate_limits()
    _user_last_request[12345] = time.time() - RATE_LIMIT_SECONDS - 1
    can_proceed, wait = _check_rate_limit(12345)
    assert can_proceed is True


def test_floodwait_penalty():
    """User marked with floodwait should be blocked for FLOODWAIT_PENALTY_SECONDS."""
    _clear_rate_limits()
    _mark_user_floodwait(12345)
    can_proceed, wait = _check_rate_limit(12345)
    assert can_proceed is False
    assert wait > 0


def test_floodwait_expires():
    """Floodwait penalty should expire after FLOODWAIT_PENALTY_SECONDS."""
    _clear_rate_limits()
    _user_got_floodwait[12345] = time.time() - FLOODWAIT_PENALTY_SECONDS - 1
    can_proceed, wait = _check_rate_limit(12345)
    assert can_proceed is True
    # TTLCache автоматически удаляет записи по TTL, не при доступе


def test_admin_bypasses_rate_limit():
    """Admin users should always bypass rate limits."""
    _clear_rate_limits()
    from config import ADMIN_IDS
    admin_id = next(iter(ADMIN_IDS))
    _update_rate_limit(admin_id)
    can_proceed, wait = _check_rate_limit(admin_id)
    assert can_proceed is True


def test_cleanup_rate_limits():
    """cleanup_rate_limits removes expired entries via TTLCache.expire()."""
    _clear_rate_limits()
    # TTLCache удаляет записи по TTL (1 час для _user_last_request, 2 часа для _user_got_floodwait)
    # Добавляем свежие записи - они не будут удалены
    _user_last_request[222] = time.time()
    _user_got_floodwait[444] = time.time()

    removed = cleanup_rate_limits()
    # Свежие записи не удаляются, expire() удаляет только истёкшие по TTL кэша
    assert removed == 0
    assert 222 in _user_last_request
    assert 444 in _user_got_floodwait
    _clear_rate_limits()


def test_check_and_update_rate_limit_atomic():
    """check_and_update_rate_limit atomically checks and updates."""
    _clear_rate_limits()

    async def _run():
        can_proceed, wait = await check_and_update_rate_limit(77777)
        assert can_proceed is True
        # Second call should be blocked (already updated)
        can_proceed2, wait2 = await check_and_update_rate_limit(77777)
        assert can_proceed2 is False

    asyncio.run(_run())
    _clear_rate_limits()


