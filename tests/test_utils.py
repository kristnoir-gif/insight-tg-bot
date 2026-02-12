"""Tests for utils.py — format_number, get_bot_stats."""
from unittest.mock import patch

from config import STATS_OFFSET_USERS, STATS_OFFSET_ANALYSES
from utils import format_number, get_bot_stats


def test_format_number_small():
    """Numbers below 1000 are returned as-is."""
    assert format_number(0) == "0"
    assert format_number(150) == "150"
    assert format_number(999) == "999"


def test_format_number_thousands():
    """Numbers >= 1000 are formatted with K suffix."""
    assert format_number(1000) == "1K"
    assert format_number(1500) == "1.5K"
    assert format_number(3000) == "3K"
    assert format_number(10000) == "10K"
    assert format_number(12345) == "12.3K"


def test_get_bot_stats(temp_db):
    """get_bot_stats returns dict with correct keys."""
    with patch("db.DB_PATH", temp_db), patch("utils.DB_PATH", temp_db):
        # Need to re-import to pick up patched DB_PATH
        from db import register_user, log_channel_analysis
        register_user(1, "user1")
        register_user(2, "user2")
        log_channel_analysis("test_ch", "Test Channel", 100, analyzed_by=1)

        stats = get_bot_stats()
        assert stats["total_users"] == 2 + STATS_OFFSET_USERS
        assert stats["total_channels"] == 1
        assert stats["total_analyses"] >= 1 + STATS_OFFSET_ANALYSES


def test_get_bot_stats_empty(temp_db):
    """get_bot_stats works on empty DB."""
    with patch("db.DB_PATH", temp_db), patch("utils.DB_PATH", temp_db):
        stats = get_bot_stats()
        assert stats["total_users"] == STATS_OFFSET_USERS
        assert stats["total_channels"] == 0
        assert stats["total_analyses"] == STATS_OFFSET_ANALYSES
