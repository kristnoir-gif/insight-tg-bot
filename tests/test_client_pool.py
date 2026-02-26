"""Tests for client_pool.py — cache, account selection, cooldowns, analyze()."""
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from client_pool import AnalysisCache, ClientAccount, ClientPool
from analyzer import AnalysisResult, ChannelStats


class TestAnalysisCache:
    """Tests for AnalysisCache LRU cache."""

    def test_set_and_get(self):
        cache = AnalysisCache(max_size=10, ttl_seconds=3600)
        mock_result = MagicMock()
        cache.set("test_channel", mock_result)
        assert cache.get("test_channel") is mock_result

    def test_get_missing(self):
        cache = AnalysisCache(max_size=10, ttl_seconds=3600)
        assert cache.get("nonexistent") is None

    def test_expired_entry(self):
        cache = AnalysisCache(max_size=10, ttl_seconds=1)
        mock_result = MagicMock()
        cache.set("chan", mock_result)
        # Manually expire
        cache._cache["chan"].created_at = time.time() - 10
        assert cache.get("chan") is None

    def test_max_size_eviction(self):
        cache = AnalysisCache(max_size=2, ttl_seconds=3600)
        cache.set("ch1", MagicMock())
        cache.set("ch2", MagicMock())
        cache.set("ch3", MagicMock())
        # ch1 should be evicted
        assert cache.get("ch1") is None
        assert cache.get("ch2") is not None
        assert cache.get("ch3") is not None

    def test_normalize_key(self):
        cache = AnalysisCache(max_size=10, ttl_seconds=3600)
        mock_result = MagicMock()
        cache.set("@TestChannel", mock_result)
        assert cache.get("testchannel") is mock_result
        assert cache.get("TestChannel") is mock_result

    def test_clear(self):
        cache = AnalysisCache(max_size=10, ttl_seconds=3600)
        cache.set("ch1", MagicMock())
        cache.clear()
        assert cache.get("ch1") is None

    def test_invalidate(self):
        cache = AnalysisCache(max_size=10, ttl_seconds=3600)
        cache.set("ch1", MagicMock())
        cache.invalidate("ch1")
        assert cache.get("ch1") is None

    def test_stats(self):
        cache = AnalysisCache(max_size=10, ttl_seconds=3600)
        cache.set("ch1", MagicMock())
        cache.set("ch2", MagicMock())
        stats = cache.stats()
        assert stats["total"] == 2
        assert stats["valid"] == 2
        assert stats["max_size"] == 10


class TestClientAccount:
    """Tests for ClientAccount cooldown logic."""

    def test_is_available_no_cooldown(self):
        acc = ClientAccount(name="test", client=MagicMock())
        assert acc.is_available is True

    def test_set_cooldown(self):
        acc = ClientAccount(name="test", client=MagicMock())
        acc.set_cooldown(60)
        assert acc.is_available is False
        assert acc.cooldown_remaining > 0

    def test_clear_cooldown(self):
        acc = ClientAccount(name="test", client=MagicMock())
        acc.set_cooldown(60)
        acc.clear_cooldown()
        assert acc.is_available is True
        assert acc.cooldown_remaining == 0

    def test_cooldown_remaining_expired(self):
        acc = ClientAccount(name="test", client=MagicMock())
        acc.cooldown_until = time.time() - 10
        assert acc.cooldown_remaining == 0
        assert acc.is_available is True


class TestClientPool:
    """Tests for ClientPool account selection and status."""

    def test_add_account(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        pool.add_account("backup", MagicMock())
        assert pool.status()["total_accounts"] == 2

    def test_select_best_account_prefers_available(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        pool.add_account("backup", MagicMock())
        selected = pool._select_best_account()
        assert selected is not None
        assert selected.name in ("main", "backup")

    def test_select_best_account_skips_cooldown(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        pool.add_account("backup", MagicMock())
        # Put main in cooldown
        pool._accounts[0].set_cooldown(300)
        selected = pool._select_best_account()
        assert selected is not None
        assert selected.name == "backup"

    def test_select_best_account_all_cooldown(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        pool._accounts[0].set_cooldown(300)
        selected = pool._select_best_account()
        assert selected is None

    def test_clear_cooldowns(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        pool._accounts[0].set_cooldown(300)
        pool.clear_cooldowns()
        assert pool._accounts[0].is_available is True

    def test_status(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        status = pool.status()
        assert status["total_accounts"] == 1
        assert status["available_accounts"] == 1
        assert "cache" in status

    def test_status_text(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        text = pool.status_text()
        assert "main" in text
        assert "доступен" in text

    def test_select_prefers_less_used(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("busy", MagicMock())
        pool.add_account("fresh", MagicMock())
        pool._accounts[0].total_requests = 100
        pool._accounts[1].total_requests = 0
        selected = pool._select_best_account()
        assert selected.name == "fresh"

    def test_get_account_by_name(self):
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        pool.add_account("backup", MagicMock())
        assert pool.get_account_by_name("main") is not None
        assert pool.get_account_by_name("nonexistent") is None


class TestClientPoolAnalyze:
    """Async tests for ClientPool.analyze()."""

    @pytest.mark.asyncio
    async def test_analyze_returns_cache_hit(self):
        """analyze() returns cached result without calling the client."""
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())

        cached_result = AnalysisResult(
            title="Cached", cloud_path="/tmp/c.png",
            stats=ChannelStats(unique_count=50),
        )
        pool._cache.set("testchan:full", cached_result)

        result, error = await pool.analyze("testchan", use_cache=True, lite_mode=False)
        assert error is None
        assert result is not None
        assert result.title == "Cached"
        assert result.from_cache is True

    @pytest.mark.asyncio
    async def test_analyze_cross_cache_full_for_lite(self):
        """Full cache result is reused for lite request."""
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())

        cached_result = AnalysisResult(
            title="Full Result", cloud_path="/tmp/c.png",
            stats=ChannelStats(unique_count=100),
        )
        pool._cache.set("testchan:full", cached_result)

        result, error = await pool.analyze("testchan", use_cache=True, lite_mode=True)
        assert error is None
        assert result is not None
        assert result.title == "Full Result"

    @pytest.mark.asyncio
    async def test_analyze_all_cooldown(self):
        """analyze() returns all_cooldown error when no accounts available."""
        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        pool._accounts[0].set_cooldown(300)

        result, error = await pool.analyze("testchan", use_cache=False)
        assert result is None
        assert error.startswith("all_cooldown:")

    @pytest.mark.asyncio
    async def test_analyze_success(self):
        """analyze() returns result from analyze_channel on success."""
        pool = ClientPool(cache_ttl=3600)
        mock_client = MagicMock()
        pool.add_account("main", mock_client)

        fake_result = AnalysisResult(
            title="Success", cloud_path="/tmp/c.png",
            stats=ChannelStats(unique_count=42),
        )
        with patch("client_pool.analyze_channel", new_callable=AsyncMock, return_value=fake_result):
            result, error = await pool.analyze("testchan", use_cache=False, lite_mode=True)
            assert error is None
            assert result.title == "Success"

    @pytest.mark.asyncio
    async def test_analyze_rotation_on_floodwait(self):
        """analyze() rotates to next account on FloodWaitError."""
        from telethon.errors import FloodWaitError

        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())
        pool.add_account("backup", MagicMock())

        call_count = 0
        fake_result = AnalysisResult(
            title="Backup OK", cloud_path="/tmp/c.png",
            stats=ChannelStats(unique_count=10),
        )

        async def mock_analyze(client, channel, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FloodWaitError(request=None, capture=60)
            return fake_result

        with patch("client_pool.analyze_channel", side_effect=mock_analyze):
            result, error = await pool.analyze("testchan", use_cache=False, lite_mode=True)
            assert error is None
            assert result.title == "Backup OK"
            assert call_count == 2
            # Main should be in cooldown
            assert pool._accounts[0].is_available is False

    @pytest.mark.asyncio
    async def test_analyze_web_fallback(self):
        """analyze() falls back to web parsing when all accounts fail."""
        from analyzer import AnalysisError

        pool = ClientPool(cache_ttl=3600)
        pool.add_account("main", MagicMock())

        async def mock_analyze(client, channel, **kwargs):
            raise AnalysisError("не найден")

        fake_web_result = AnalysisResult(
            title="Web Result", cloud_path="/tmp/c.png",
            stats=ChannelStats(unique_count=5),
        )

        with patch("client_pool.analyze_channel", side_effect=mock_analyze), \
             patch("client_pool.analyze_channel_web", new_callable=AsyncMock, return_value=fake_web_result):
            result, error = await pool.analyze("testchan", use_cache=False, lite_mode=True)
            assert error is None
            assert result.title == "Web Result"
