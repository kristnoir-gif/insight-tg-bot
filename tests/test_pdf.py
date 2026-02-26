"""Tests for visualization/pdf_export.py — PDF report generation."""
import os
from collections import Counter

from visualization.pdf_export import generate_pdf_report
from visualization.charts import generate_top_words_chart, generate_weekday_chart
from analyzer import AnalysisResult, ChannelStats


def test_pdf_no_images():
    """generate_pdf_report returns None when no images exist."""
    result = AnalysisResult(title="Empty")
    path = generate_pdf_report(result, "empty")
    assert path is None


def test_pdf_with_real_charts(tmp_path):
    """generate_pdf_report creates a valid PDF from real chart images."""
    os.chdir(tmp_path)

    # Generate real charts
    counter = Counter({"слово": 50, "тест": 30, "анализ": 20, "канал": 15, "привет": 10})
    graph_path = generate_top_words_chart("pdftest", counter, "PDF Test Channel")
    weekday_counts = {0: 10, 1: 15, 2: 20, 3: 25, 4: 30, 5: 5, 6: 8}
    weekday_path = generate_weekday_chart("pdftest", weekday_counts, "PDF Test Channel")

    assert graph_path is not None
    assert weekday_path is not None

    result = AnalysisResult(
        title="PDF Test Channel",
        subscribers=5000,
        stats=ChannelStats(unique_count=150, avg_len=22.5, scream_index=4.2),
        graph_path=graph_path,
        weekday_path=weekday_path,
    )

    pdf_path = generate_pdf_report(result, "pdftest", output_path=str(tmp_path / "report.pdf"))
    assert pdf_path is not None
    assert os.path.exists(pdf_path)
    assert pdf_path.endswith(".pdf")

    # PDF should be non-trivial in size (> 1KB)
    assert os.path.getsize(pdf_path) > 1024

    # Cleanup
    os.remove(graph_path)
    os.remove(weekday_path)


def test_pdf_custom_output_path(tmp_path):
    """generate_pdf_report uses custom output path."""
    os.chdir(tmp_path)

    counter = Counter({"тест": 20, "слово": 15, "пример": 10})
    graph_path = generate_top_words_chart("custompath", counter, "Custom")
    assert graph_path is not None

    result = AnalysisResult(
        title="Custom",
        stats=ChannelStats(unique_count=3),
        graph_path=graph_path,
    )

    custom_path = str(tmp_path / "my_custom_report.pdf")
    pdf_path = generate_pdf_report(result, "custompath", output_path=custom_path)
    assert pdf_path == custom_path
    assert os.path.exists(custom_path)

    os.remove(graph_path)


def test_pdf_missing_images_skipped(tmp_path):
    """generate_pdf_report skips non-existent image paths gracefully."""
    os.chdir(tmp_path)

    counter = Counter({"тест": 20, "слово": 15, "пример": 10})
    graph_path = generate_top_words_chart("skiptest", counter, "Skip Test")
    assert graph_path is not None

    result = AnalysisResult(
        title="Skip Test",
        stats=ChannelStats(unique_count=3),
        graph_path=graph_path,
        # These don't exist but shouldn't crash
        mats_path="/nonexistent/mats.png",
        weekday_path="/nonexistent/weekday.png",
    )

    pdf_path = generate_pdf_report(result, "skiptest", output_path=str(tmp_path / "skip.pdf"))
    assert pdf_path is not None
    assert os.path.exists(pdf_path)

    os.remove(graph_path)
