"""Tests for visualization/archetype.py — archetype classification and fun facts."""
import os

import pytest

from visualization.archetype import classify_archetype, generate_fun_facts, ARCHETYPES


class TestClassifyArchetype:
    """Tests for archetype classification logic."""

    def _classify(self, **overrides):
        defaults = dict(
            scream_index=3.0, avg_len=50.0, unique_count=1500,
            mat_count=5, pos_percent=50.0, agg_percent=50.0,
            meta_percent=30.0, everyday_percent=70.0,
            names_count=10, emoji_count=30, repost_percent=5.0,
            night_post_percent=10.0, total_posts=200,
        )
        defaults.update(overrides)
        return classify_archetype(**defaults)

    def test_reposter(self):
        result = self._classify(repost_percent=60)
        assert result.name == "Куратор"

    def test_rebel(self):
        result = self._classify(mat_count=50, scream_index=6)
        assert result.name == "Бунтарь"

    def test_night_owl(self):
        result = self._classify(night_post_percent=45)
        assert result.name == "Сова-инсомник"

    def test_gossiper(self):
        result = self._classify(names_count=50, avg_len=40, mat_count=10)
        assert result.name == "Тусовщик"

    def test_agitator(self):
        result = self._classify(scream_index=8)
        assert result.name == "Агитатор"

    def test_philosopher(self):
        result = self._classify(avg_len=80, meta_percent=60)
        assert result.name == "Философ"

    def test_default_machine(self):
        """Default fallback — Контент-машина."""
        result = self._classify()
        assert result.name == "Контент-машина"

    def test_all_archetypes_have_required_fields(self):
        for key, arch in ARCHETYPES.items():
            assert arch.name, f"{key} missing name"
            assert arch.emoji, f"{key} missing emoji"
            assert arch.tagline, f"{key} missing tagline"
            assert arch.color, f"{key} missing color"
            assert arch.description, f"{key} missing description"
            assert arch.bg_file, f"{key} missing bg_file"


class TestFunFacts:
    """Tests for fun facts generation."""

    def _facts(self, **overrides):
        defaults = dict(
            scream_index=3.0, avg_len=50.0, unique_count=1500,
            total_posts=200, top_word="жизнь", top_word_count=80,
            mat_count=10, pos_percent=50.0, agg_percent=50.0,
            night_post_percent=10.0, peak_hour=14, peak_weekday=2,
            names_count=15, repost_percent=5.0, emoji_count=50,
            top_emoji="❤️",
        )
        defaults.update(overrides)
        return generate_fun_facts(**defaults)

    def test_returns_list(self):
        facts = self._facts()
        assert isinstance(facts, list)

    def test_max_5_facts(self):
        facts = self._facts()
        assert len(facts) <= 5

    def test_night_owl_fact(self):
        facts = self._facts(night_post_percent=40, peak_hour=2)
        texts = " ".join(facts)
        assert "ночью" in texts or "сова" in texts.lower()

    def test_zero_mat_fact(self):
        facts = self._facts(mat_count=0, total_posts=100)
        texts = " ".join(facts)
        assert "мат" in texts.lower() or "карма" in texts.lower()

    def test_high_scream_fact(self):
        facts = self._facts(scream_index=10)
        texts = " ".join(facts)
        assert "КРИЧИТ" in texts or "Scream" in texts
