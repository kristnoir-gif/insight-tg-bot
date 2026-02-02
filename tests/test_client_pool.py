"""Tests for client_pool.py — cache, account selection, cooldowns."""
import time
from unittest.mock import MagicMock, patch

from client_pool import AnalysisCache, ClientAccount, ClientPool


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
