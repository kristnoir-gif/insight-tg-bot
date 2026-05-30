"""
render_full_v2_gallery(result, channel_key) — рендерит ВСЕ карточки v2 для юзера.

Возвращает список Path в порядке как должны идти в Telegram-альбоме:
01 обложка → 03 в цифрах → 02 главные темы → 06 хронотип → ...

Каждая карточка опционально:
- если у V2CardData есть данные → рендерим
- если нет → пропускаем (например, top_posts пустой → 15 хитов нет)
"""
from __future__ import annotations

import logging
from pathlib import Path

from analyzer import AnalysisResult
from .hybrid import render_card_to_file
from .card_data import CARDS
from .variant_renderer import (
    render_chronotype_card, render_vocab_card, render_toxicity_card,
    render_jungian_card,
)
from .variants import pick_chronotype, pick_vocab, pick_toxicity
from .special_cards import render_hit_post
# Новый рендер на основе твоих чистых PNG-шаблонов от Figma
from .general_cards import (
    render_01_cover, render_02_main_themes, render_03_chanal_in_numbers,
    render_04_sum_of_reactions, render_07_word_cloud, render_08_post_by_days_weeks,
    render_09_bad_word_cloud, render_11_geography, render_12_top_phrases,
    render_13_emotions, render_15_hit_post, render_16_reading_statistics,
    render_17_most_used_word, render_18_top_person,
)

logger = logging.getLogger(__name__)


def render_full_v2_gallery(result: AnalysisResult, channel_key: str,
                            *, out_dir: Path | None = None,
                            jungian: str | None = None) -> list[Path]:
    """Рендерит все доступные v2 карточки. Порядок: сначала градиентные общие
    карточки (1080×1920 с фиолетово-розовым фоном), потом per-variant архетипы
    с 3D-иллюстрациями (хронотип, vocab, токсичность, Юнгианский) в конце."""
    out_dir = (out_dir or Path("/tmp/v2_gallery")) / channel_key
    out_dir.mkdir(parents=True, exist_ok=True)
    v = result.v2
    paths: list[Path] = []
    archetype_paths: list[Path] = []  # архетипы с 3D — в конец

    # 01 обложка (твой Figma PNG + PIL)
    try:
        out = out_dir / "01_cover.png"
        out.write_bytes(render_01_cover(result))
        paths.append(out)
    except Exception as e: logger.warning(f"01_cover failed: {e}")

    # 03 в цифрах (твой Figma PNG + PIL)
    try:
        out = out_dir / "03_chanal_in_numbers.png"
        out.write_bytes(render_03_chanal_in_numbers(result))
        paths.append(out)
    except Exception as e: logger.warning(f"03 failed: {e}")

    # 02 главные темы (твой Figma PNG + PIL pills)
    if result.topics:
        try:
            out = out_dir / "02_main_themes.png"
            out.write_bytes(render_02_main_themes(result))
            paths.append(out)
        except Exception as e: logger.warning(f"02 failed: {e}")

    # 04 суммарные реакции (твой Figma PNG + PIL)
    if v.total_reactions > 0:
        try:
            out = out_dir / "04_sum_of_reactions.png"
            out.write_bytes(render_04_sum_of_reactions(result))
            paths.append(out)
        except Exception as e: logger.warning(f"04 failed: {e}")

    # 06 хронотип (per-variant) — В КОНЕЦ
    try:
        out = out_dir / "06_chronotype.png"
        out.write_bytes(render_chronotype_card(
            peak_hour=v.peak_hour,
            peak_share=v.peak_bucket_share,
            total_posts=v.total_posts,
        ))
        archetype_paths.append(out)
    except Exception as e: logger.warning(f"06 chronotype failed: {e}")

    # 05 архетип словаря (per-variant) — только если достаточно слов
    if result.stats.unique_count >= 6000:
        try:
            out = out_dir / "05_archetype_vocab.png"
            out.write_bytes(render_vocab_card(unique_count=result.stats.unique_count))
            archetype_paths.append(out)
        except Exception as e: logger.warning(f"05 vocab failed: {e}")

    # 07 облако слов — твой PNG-шаблон + встроенное wordcloud
    if result.cloud_path:
        try:
            out = out_dir / "07_word_cloud.png"
            out.write_bytes(render_07_word_cloud(result))
            paths.append(out)
        except Exception as e: logger.warning(f"07 cloud failed: {e}")

    # 08 дни недели (твой Figma PNG + встраивает legacy bar chart)
    try:
        out = out_dir / "08_post_by_days_weeks.png"
        out.write_bytes(render_08_post_by_days_weeks(result))
        paths.append(out)
    except Exception as e: logger.warning(f"08 failed: {e}")

    # 13 эмоции (Figma PNG + PIL)
    try:
        out = out_dir / "13_emotions.png"
        out.write_bytes(render_13_emotions(result))
        paths.append(out)
    except Exception as e: logger.warning(f"13 emotions failed: {e}")

    # 17 топ-слово (Figma PNG + PIL)
    if v.top_word:
        try:
            out = out_dir / "17_most_used_word.png"
            out.write_bytes(render_17_most_used_word(result))
            paths.append(out)
        except Exception as e: logger.warning(f"17 failed: {e}")

    # 11 география (твой Figma PNG + PIL)
    if v.top_cities:
        try:
            out = out_dir / "11_geography.png"
            out.write_bytes(render_11_geography(result))
            paths.append(out)
        except Exception as e: logger.warning(f"11 failed: {e}")

    # 18 топ-имена (Figma PNG + PIL)
    if v.top_names_with_counts:
        try:
            out = out_dir / "18_top_person.png"
            out.write_bytes(render_18_top_person(result))
            paths.append(out)
        except Exception as e: logger.warning(f"18 failed: {e}")

    # 10 токсичность (per-variant) — В КОНЕЦ
    try:
        out = out_dir / "10_archetype_bad.png"
        out.write_bytes(render_toxicity_card(
            mat_percent=v.mat_percent_of_text,
            posts_with_mat_percent=v.posts_with_mat_percent,
        ))
        archetype_paths.append(out)
    except Exception as e: logger.warning(f"10 toxicity failed: {e}")

    # 09 облако мата (твой Figma PNG + встроенное wordcloud)
    if result.mats_path:
        try:
            out = out_dir / "09_bad_word_cloud.png"
            out.write_bytes(render_09_bad_word_cloud(result))
            paths.append(out)
        except Exception as e: logger.warning(f"09 bad cloud failed: {e}")

    # 16 статистика чтения (Figma PNG + PIL)
    if v.reading_time_hours > 0:
        try:
            out = out_dir / "16_reading_statistics.png"
            out.write_bytes(render_16_reading_statistics(result))
            paths.append(out)
        except Exception as e: logger.warning(f"16 failed: {e}")

    # 14 канал в одной фразе (LLM) — нужна phrase
    if v.one_phrase_llm or (result.content_analysis_text and len(result.content_analysis_text) > 30):
        try:
            out = out_dir / "14_one_phrase.png"
            render_card_to_file("14_one_phrase", CARDS["14_one_phrase"](result), out)
            paths.append(out)
        except Exception as e: logger.warning(f"14 failed: {e}")

    # 15 хит-посты (твой Figma PNG + PIL post boxes)
    if v.top_posts:
        try:
            out = out_dir / "15_hit_post.png"
            out.write_bytes(render_15_hit_post(result))
            paths.append(out)
        except Exception as e: logger.warning(f"15 failed: {e}")

    # Юнгианский (большой архетип) — В КОНЕЦ
    jung_name = jungian or v.jungian_archetype
    if jung_name:
        try:
            out = out_dir / "big_jungian.png"
            sage_pct = 78
            outlaw_pct = int(v.posts_with_mat_percent) or 15
            out.write_bytes(render_jungian_card(jung_name, sage_pct=sage_pct, outlaw_pct=outlaw_pct))
            archetype_paths.append(out)
        except Exception as e: logger.warning(f"jungian failed: {e}")

    # В конец прицепляем все архетип-карточки с 3D-иллюстрациями
    paths.extend(archetype_paths)

    return paths
