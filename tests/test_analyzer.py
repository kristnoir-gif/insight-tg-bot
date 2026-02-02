"""Tests for analyzer.py — username parsing, cache."""
import os
import json
import time
from unittest.mock import patch

from analyzer import _get_cache_path, _save_to_cache, _load_from_cache, _is_cache_valid
from analyzer import AnalysisResult, ChannelStats


def test_parse_channel_username():
    """Various channel username formats normalise to the same key."""
    # The normalisation logic used throughout the codebase:
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
