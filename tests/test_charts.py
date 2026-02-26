"""Tests for visualization/charts.py — chart generation."""
import os
from collections import Counter

import pytest

from visualization.charts import (
    generate_top_words_chart,
    generate_weekday_chart,
    generate_hour_chart,
    generate_names_chart,
    generate_phrases_chart,
    generate_heatmap_chart,
    generate_comparison_chart,
    _clean_title,
)


class TestCleanTitle:
    """Tests for _clean_title helper."""

    def test_short_title(self):
        assert _clean_title("Short") == "Short"

    def test_long_title_wraps(self):
        result = _clean_title("This Is A Very Long Channel Title That Should Wrap")
        assert "\n" in result

    def test_special_chars_removed(self):
        result = _clean_title("Chan🔥nel!!!")
        assert "🔥" not in result


class TestTopWordsChart:
    """Tests for generate_top_words_chart."""

    def test_generates_file(self, tmp_path):
        os.chdir(tmp_path)
        counter = Counter({"слово": 50, "тест": 30, "анализ": 20, "канал": 15, "привет": 10})
        path = generate_top_words_chart("testuser", counter, "Test Channel")
        assert path is not None
        assert os.path.exists(path)
        assert path.endswith(".png")
        os.remove(path)

    def test_empty_counter_returns_none(self, tmp_path):
        os.chdir(tmp_path)
        counter = Counter()
        path = generate_top_words_chart("testuser", counter, "Empty")
        assert path is None


class TestWeekdayChart:
    """Tests for generate_weekday_chart."""

    def test_generates_file(self, tmp_path):
        os.chdir(tmp_path)
        counts = {0: 10, 1: 15, 2: 20, 3: 25, 4: 30, 5: 5, 6: 8}
        path = generate_weekday_chart("testuser", counts, "Test Channel")
        assert path is not None
        assert os.path.exists(path)
        os.remove(path)

    def test_partial_days(self, tmp_path):
        """Chart handles missing days (not all 7 present)."""
        os.chdir(tmp_path)
        counts = {0: 10, 3: 25}  # Only Monday and Thursday
        path = generate_weekday_chart("testuser", counts, "Partial")
        assert path is not None
        assert os.path.exists(path)
        os.remove(path)

    def test_empty_counts(self, tmp_path):
        """Chart handles all-zero counts."""
        os.chdir(tmp_path)
        counts = {}
        path = generate_weekday_chart("testuser", counts, "Empty")
        assert path is not None  # Still generates a chart with zeros
        assert os.path.exists(path)
        os.remove(path)


class TestHourChart:
    """Tests for generate_hour_chart."""

    def test_generates_file(self, tmp_path):
        os.chdir(tmp_path)
        hour_counts = {h: h * 2 for h in range(24)}
        path = generate_hour_chart("testuser", hour_counts, "Test Channel")
        assert path is not None
        assert os.path.exists(path)
        os.remove(path)


class TestNamesChart:
    """Tests for generate_names_chart."""

    def test_generates_file(self, tmp_path):
        os.chdir(tmp_path)
        names = [("Пушкин", 15), ("Толстой", 10), ("Чехов", 8), ("Достоевский", 5)]
        path = generate_names_chart("testuser", names, "Literary Channel",
                                    total_unique_names=4, total_mentions=38)
        assert path is not None
        assert os.path.exists(path)
        os.remove(path)

    def test_too_few_names_returns_none(self, tmp_path):
        os.chdir(tmp_path)
        names = [("Пушкин", 5), ("Толстой", 3)]  # Only 2, minimum is 3
        path = generate_names_chart("testuser", names, "Few Names")
        assert path is None

    def test_empty_names_returns_none(self, tmp_path):
        os.chdir(tmp_path)
        path = generate_names_chart("testuser", [], "No Names")
        assert path is None


class TestPhrasesChart:
    """Tests for generate_phrases_chart."""

    def test_generates_file(self, tmp_path):
        os.chdir(tmp_path)
        phrases = [
            (("один", "два", "три"), 20),
            (("четыре", "пять", "шесть"), 15),
            (("семь", "восемь", "девять"), 10),
        ]
        path = generate_phrases_chart("testuser", phrases, "Phrases Channel")
        assert path is not None
        assert os.path.exists(path)
        os.remove(path)

    def test_empty_phrases_returns_none(self, tmp_path):
        os.chdir(tmp_path)
        path = generate_phrases_chart("testuser", [], "No Phrases")
        assert path is None


class TestHeatmapChart:
    """Tests for generate_heatmap_chart."""

    def test_generates_file(self, tmp_path):
        os.chdir(tmp_path)
        times = [(0, 12), (0, 13), (1, 14), (2, 15), (3, 10), (4, 11), (5, 9), (6, 8)]
        path = generate_heatmap_chart("testuser", times, "Heatmap Channel")
        assert path is not None
        assert os.path.exists(path)
        os.remove(path)

    def test_empty_times_returns_none(self, tmp_path):
        os.chdir(tmp_path)
        path = generate_heatmap_chart("testuser", [], "Empty Heatmap")
        assert path is None


class TestComparisonChart:
    """Tests for generate_comparison_chart."""

    def test_generates_file(self, tmp_path):
        os.chdir(tmp_path)
        stats1 = {'scream': 3.5, 'vocab': 1000, 'length': 45.2, 'reposts': 10.5}
        stats2 = {'scream': 5.0, 'vocab': 800, 'length': 60.1, 'reposts': 25.0}
        path = generate_comparison_chart("Channel A", "Channel B", stats1, stats2)
        assert path is not None
        assert os.path.exists(path)
        os.remove(path)

    def test_zero_values(self, tmp_path):
        os.chdir(tmp_path)
        stats1 = {'scream': 0, 'vocab': 0, 'length': 0, 'reposts': 0}
        stats2 = {'scream': 0, 'vocab': 0, 'length': 0, 'reposts': 0}
        path = generate_comparison_chart("A", "B", stats1, stats2)
        assert path is not None
        assert os.path.exists(path)
        os.remove(path)
