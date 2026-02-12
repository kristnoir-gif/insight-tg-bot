"""Tests for heatmap and comparison chart generation."""
import os

from visualization.charts import generate_heatmap_chart, generate_comparison_chart


def test_heatmap_chart_creates_file():
    """generate_heatmap_chart returns a path and creates a PNG file."""
    data = [(0, 10), (0, 10), (1, 15), (6, 23)]
    path = generate_heatmap_chart("test", data, "Test Channel")
    assert path is not None
    assert os.path.exists(path)
    os.remove(path)


def test_heatmap_chart_empty_data():
    """generate_heatmap_chart returns None for empty data."""
    result = generate_heatmap_chart("test", [], "Test Channel")
    assert result is None


def test_comparison_chart_creates_file():
    """generate_comparison_chart returns a path and creates a PNG file."""
    stats1 = {'scream': 3.2, 'vocab': 2450, 'length': 45, 'reposts': 12.0}
    stats2 = {'scream': 7.8, 'vocab': 1890, 'length': 120, 'reposts': 45.0}
    path = generate_comparison_chart("Channel1", "Channel2", stats1, stats2)
    assert path is not None
    assert os.path.exists(path)
    os.remove(path)


def test_comparison_chart_equal_values():
    """generate_comparison_chart handles equal values without division by zero."""
    stats1 = {'scream': 5.0, 'vocab': 1000, 'length': 50, 'reposts': 20.0}
    stats2 = {'scream': 5.0, 'vocab': 1000, 'length': 50, 'reposts': 20.0}
    path = generate_comparison_chart("Ch1", "Ch2", stats1, stats2)
    assert path is not None
    assert os.path.exists(path)
    os.remove(path)


def test_comparison_chart_zero_values():
    """generate_comparison_chart handles zero values."""
    stats1 = {'scream': 0.0, 'vocab': 0, 'length': 0, 'reposts': 0.0}
    stats2 = {'scream': 1.0, 'vocab': 100, 'length': 10, 'reposts': 5.0}
    path = generate_comparison_chart("Empty", "Active", stats1, stats2)
    assert path is not None
    assert os.path.exists(path)
    os.remove(path)
