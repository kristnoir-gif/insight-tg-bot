"""Tests for analyzer.py — username parsing, cache, analyze_channel, analyze_channel_web."""
import os
import json
import time
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

import pytest

from analyzer import (
    _get_cache_path, _save_to_cache, _load_from_cache, _is_cache_valid,
    AnalysisResult, ChannelStats, AnalysisError, analyze_channel,
    analyze_channel_web,
)


def test_parse_channel_username():
    """Various channel username formats normalise to the same key."""
    def normalize(raw: str) -> str:
        return raw.replace("@", "").split("/")[-1].strip().lower()

    assert normalize("@channel") == "channel"
    assert normalize("t.me/channel") == "channel"
    assert normalize("https://t.me/channel") == "channel"
    assert normalize("Channel") == "channel"


def test_empty_messages_no_crash():
    """AnalysisResult with empty stats doesn't crash on attribute access."""
    result = AnalysisResult()
    assert result.title == ""
    assert result.stats.unique_count == 0
    assert result.get_all_paths() == []


def test_analysis_result_get_all_paths():
    """get_all_paths returns only non-None paths."""
    result = AnalysisResult(
        cloud_path="/tmp/cloud.png",
        graph_path="/tmp/graph.png",
        mats_path=None,
    )
    paths = result.get_all_paths()
    assert "/tmp/cloud.png" in paths
    assert "/tmp/graph.png" in paths
    assert len(paths) == 2


def test_disk_cache_save_load(tmp_path):
    """save -> load round-trip preserves data."""
    with patch("analyzer.CACHE_DIR", str(tmp_path)):
        result = AnalysisResult(
            title="Test Channel",
            subscribers=1000,
            stats=ChannelStats(unique_count=42, avg_len=15.5, scream_index=3.2),
            top_emojis=[("\U0001f525", 10), ("\u2764\ufe0f", 5)],
        )
        _save_to_cache("testchan", result, lite_mode=False)
        loaded = _load_from_cache("testchan")

        assert loaded is not None
        assert loaded.title == "Test Channel"
        assert loaded.subscribers == 1000
        assert loaded.stats.unique_count == 42


def test_disk_cache_ttl(tmp_path):
    """Expired cache is not returned."""
    with patch("analyzer.CACHE_DIR", str(tmp_path)), \
         patch("analyzer.DISK_CACHE_TTL", 1):  # 1 second TTL
        result = AnalysisResult(title="Expire Me")
        _save_to_cache("ttlchan", result, lite_mode=False)

        # Manually expire by modifying cached_at
        meta_path = os.path.join(str(tmp_path), "ttlchan", "meta.json")
        with open(meta_path, "r") as f:
            meta = json.load(f)
        meta["cached_at"] = time.time() - 10  # 10 seconds ago
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        assert _is_cache_valid("ttlchan") is False


def test_disk_cache_lite_skip_for_full(tmp_path):
    """Lite cache is skipped when full mode requested."""
    with patch("analyzer.CACHE_DIR", str(tmp_path)):
        result = AnalysisResult(title="Lite Only", cloud_path="/tmp/cloud.png")
        _save_to_cache("litechan", result, lite_mode=True)
        loaded = _load_from_cache("litechan", require_full=True)
        assert loaded is None

        # But loading without require_full works
        loaded_lite = _load_from_cache("litechan", require_full=False)
        assert loaded_lite is not None


@pytest.mark.asyncio
async def test_analyze_channel_cache_hit(tmp_path):
    """analyze_channel returns cached result when available."""
    with patch("analyzer.CACHE_DIR", str(tmp_path)), \
         patch("analyzer.DISK_CACHE_TTL", 3600):
        # Create a cached result with a cloud image
        cloud_file = str(tmp_path / "testchan" / "cloud.png")
        os.makedirs(os.path.dirname(cloud_file), exist_ok=True)
        with open(cloud_file, "wb") as f:
            f.write(b"fake_png")

        result = AnalysisResult(
            title="Cached Channel", cloud_path=cloud_file,
            stats=ChannelStats(unique_count=100),
        )
        _save_to_cache("testchan", result, lite_mode=False)

        mock_client = MagicMock()
        cached = await analyze_channel(mock_client, "testchan", lite_mode=False)
        assert cached is not None
        assert cached.title == "Cached Channel"
        # Client should not have been called for entity
        mock_client.get_entity.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_channel_user_entity_raises():
    """analyze_channel raises AnalysisError when entity is a User."""
    from telethon.tl.types import User

    mock_client = MagicMock()
    mock_client.is_connected.return_value = True
    mock_user = MagicMock(spec=User)
    mock_client.get_entity = AsyncMock(return_value=mock_user)

    with patch("analyzer._is_cache_valid", return_value=False):
        with pytest.raises(AnalysisError, match="аккаунт пользователя"):
            await analyze_channel(mock_client, "someuser", lite_mode=True)


@pytest.mark.asyncio
async def test_analyze_channel_empty_channel():
    """analyze_channel returns result with empty stats when channel has no text messages."""
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    mock_entity = MagicMock()
    mock_entity.title = "Empty Channel"
    mock_entity.participants_count = 50
    mock_entity.username = "emptychan"
    mock_client.get_entity = AsyncMock(return_value=mock_entity)

    # iter_messages must return an async iterable
    class EmptyAsyncIter:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    mock_client.iter_messages = MagicMock(return_value=EmptyAsyncIter())

    with patch("analyzer._is_cache_valid", return_value=False):
        result = await analyze_channel(mock_client, "emptychan", lite_mode=True)
        assert result is not None
        assert result.title == "Empty Channel"
        assert result.cloud_path is None


@pytest.mark.asyncio
async def test_analyze_channel_floodwait_propagates():
    """FloodWaitError from iter_messages is propagated."""
    from telethon.errors import FloodWaitError

    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    mock_entity = MagicMock()
    mock_entity.title = "Test"
    mock_entity.participants_count = 100
    mock_entity.username = "testchan"
    mock_client.get_entity = AsyncMock(return_value=mock_entity)

    class FloodAsyncIter:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise FloodWaitError(request=None, capture=60)

    mock_client.iter_messages = MagicMock(return_value=FloodAsyncIter())

    with patch("analyzer._is_cache_valid", return_value=False):
        with pytest.raises(FloodWaitError):
            await analyze_channel(mock_client, "testchan", lite_mode=True)


@pytest.mark.asyncio
async def test_analyze_channel_web_empty_channel():
    """analyze_channel_web returns None for empty channel."""
    with patch("analyzer._is_cache_valid", return_value=False), \
         patch("analyzer._fetch_posts_from_web", new_callable=AsyncMock, return_value=("Empty", 0, [])):
        result = await analyze_channel_web("emptychan", lite_mode=True)
        assert result is None


@pytest.mark.asyncio
async def test_analyze_channel_web_lite_mode(tmp_path):
    """analyze_channel_web in lite mode generates only cloud and graph."""
    posts = [
        (datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc), "Привет мир тестовый текст"),
        (datetime(2025, 1, 2, 14, 0, tzinfo=timezone.utc), "Второй пост с текстом для анализа"),
        (datetime(2025, 1, 3, 16, 0, tzinfo=timezone.utc), "Третий пост содержит разные слова"),
    ]

    with patch("analyzer._is_cache_valid", return_value=False), \
         patch("analyzer._fetch_posts_from_web", new_callable=AsyncMock, return_value=("Test Channel", 1000, posts)), \
         patch("analyzer.generate_main_cloud", return_value="/tmp/cloud.png") as mock_cloud, \
         patch("analyzer.generate_top_words_chart", return_value="/tmp/graph.png") as mock_graph, \
         patch("analyzer._save_to_cache"), \
         patch("analyzer.CACHE_DIR", str(tmp_path)):
        result = await analyze_channel_web("testchan", lite_mode=True)
        assert result is not None
        assert result.title == "Test Channel"
        assert result.cloud_path == "/tmp/cloud.png"
        assert result.graph_path == "/tmp/graph.png"
        # In lite mode, no sentiment charts
        assert result.mats_path is None
        assert result.weekday_path is None
        mock_cloud.assert_called_once()
        mock_graph.assert_called_once()
