"""
Генерация облаков слов.
Spotify Wrapped style: тёмный фон, яркие слова, вертикальный формат 9:16.
"""
import logging
import os
from typing import Literal, Callable
import random

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from wordcloud import WordCloud

from config import (
    DPI,
    FIGURE_SIZE,
    MAX_WORDS_CLOUD,
    MAX_WORDS_SENTIMENT,
    CLOUD_WIDTH,
    CLOUD_HEIGHT,
    BACKGROUND_COLOR,
    ACCENT_GREEN,
    ACCENT_PINK,
    ACCENT_PURPLE,
    ACCENT_BLUE,
    TEXT_WHITE,
    TEXT_GRAY,
    WATERMARK_TEXT,
    WATERMARK_COLOR,
)

logger = logging.getLogger(__name__)

SentimentType = Literal['positive', 'aggressive']

# Яркие цвета для облаков (Spotify Wrapped palette)
BRIGHT_COLORS = [ACCENT_GREEN, ACCENT_PINK, ACCENT_PURPLE, ACCENT_BLUE, '#fbbf24']


def _bright_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
    """Яркие случайные цвета из палитры Wrapped."""
    return random.choice(BRIGHT_COLORS)


def _add_watermark(fig: plt.Figure) -> None:
    """Добавляет водяной знак."""
    fig.text(
        0.5, 0.05, WATERMARK_TEXT,
        fontsize=13, ha='center', va='bottom', color=WATERMARK_COLOR,
        alpha=0.8, fontweight='bold', linespacing=1.5
    )


def _add_title(fig: plt.Figure, title: str, channel: str) -> float:
    """Добавляет заголовок + название канала. Возвращает y для следующего элемента."""
    fig.text(0.5, 0.96, title, fontsize=22, fontweight='bold',
             ha='center', color=TEXT_WHITE)
    # Двухстрочные названия опускаем ниже
    has_newline = '\n' in channel
    channel_y = 0.92 if has_newline else 0.93
    fig.text(0.5, channel_y, channel, fontsize=16, ha='center', color=ACCENT_GREEN,
             va='top')
    return (channel_y - 0.05) if has_newline else (channel_y - 0.03)


from visualization.utils import clean_title as _clean_title


def _create_cloud(
    words: list[str],
    path: str,
    title_text: str,
    channel_name: str,
    color_func: Callable = None,
    max_words: int = MAX_WORDS_SENTIMENT,
    mask: np.ndarray | None = None,
) -> str | None:
    """
    Базовая функция создания облака слов (тёмный Wrapped стиль).
    """
    if not words:
        return None

    try:
        if color_func is None:
            color_func = _bright_color_func

        wc_kwargs = dict(
            background_color=BACKGROUND_COLOR,
            color_func=color_func,
            max_words=max_words,
            min_font_size=10,
            prefer_horizontal=True,
            mode='RGB',
        )
        if mask is not None:
            wc_kwargs['mask'] = mask
            wc_kwargs['contour_width'] = 0
        else:
            wc_kwargs['width'] = CLOUD_WIDTH
            wc_kwargs['height'] = CLOUD_HEIGHT

        wc = WordCloud(**wc_kwargs).generate(" ".join(words))

        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        _add_title(fig, title_text, channel_name)

        ax = fig.add_axes([0.04, 0.10, 0.92, 0.75])
        ax.imshow(wc.to_image(), interpolation='bilinear')
        ax.axis("off")

        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
        plt.close(fig)

        logger.info(f"Создано облако слов: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания облака слов: {e}")
        return None


def generate_main_cloud(username: str, words: list[str], title: str) -> str | None:
    """Генерирует основное облако смыслов."""
    path = f"cloud_{username}.png"
    return _create_cloud(
        words=words,
        path=path,
        title_text='Облако смыслов канала',
        channel_name=_clean_title(title),
        max_words=MAX_WORDS_CLOUD,
    )


def _get_skull_mask() -> np.ndarray | None:
    """Загружает маску черепа для облака мата."""
    mask_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'skull_mask.png')
    if os.path.exists(mask_path):
        img = Image.open(mask_path).convert('L')
        # WordCloud: 255 = exclude, 0 = draw. Наша маска наоборот, инвертируем.
        arr = 255 - np.array(img)
        return arr
    return None


def generate_mats_cloud(username: str, words: list[str], title: str) -> str | None:
    """Генерирует облако ненормативной лексики в форме черепа."""
    def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        reds = [ACCENT_PINK, '#ef4444', '#f87171', '#dc2626', '#fbbf24']
        return random.choice(reds)

    path = f"mats_{username}.png"
    skull_mask = _get_skull_mask()
    return _create_cloud(
        words=words,
        path=path,
        title_text='Облако мата канала',
        channel_name=_clean_title(title),
        color_func=color_func,
        mask=skull_mask,
    )


def generate_register_cloud(
    username: str,
    caps_words: list[str],
    lower_words: list[str],
    title: str,
    caps_percent: float,
    lower_percent: float,
) -> str | None:
    """Генерирует облако регистра (CAPS vs lowercase)."""
    if not caps_words and not lower_words:
        return None

    total_words = len(caps_words) + len(lower_words)
    if total_words < 10:
        return None

    try:
        path = f"register_{username}.png"
        clean_title = _clean_title(title)

        all_words = [w.upper() for w in caps_words] + [w.lower() for w in lower_words]
        if not all_words:
            return None

        def register_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
            if word.isupper():
                # CAPS — огненные яркие (розовый, оранжевый)
                return random.choice([ACCENT_PINK, '#f87171', '#fb923c', '#fbbf24'])
            else:
                # lowercase — холодные яркие (синий, фиолетовый, зелёный)
                return random.choice([ACCENT_BLUE, ACCENT_PURPLE, ACCENT_GREEN])

        wc = WordCloud(
            width=CLOUD_WIDTH,
            height=CLOUD_HEIGHT,
            background_color=BACKGROUND_COLOR,
            color_func=register_color_func,
            max_words=MAX_WORDS_CLOUD,
            min_font_size=10,
            prefer_horizontal=True,
            mode='RGB',
        ).generate(" ".join(all_words))

        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        next_y = _add_title(fig, 'Облако регистра', clean_title)

        # Статистика процентов
        stats_text = f"CAPS: {caps_percent:.1f}%  •  lowercase: {lower_percent:.1f}%"
        fig.text(0.5, next_y, stats_text, fontsize=13, ha='center', color=TEXT_GRAY,
                 style='italic')

        ax = fig.add_axes([0.04, 0.10, 0.92, 0.75])
        ax.imshow(wc.to_image(), interpolation='bilinear')
        ax.axis("off")

        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
        plt.close(fig)

        logger.info(f"Создано облако регистра: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания облака регистра: {e}")
        return None


def generate_dichotomy_cloud(
    username: str,
    metaphysics_words: list[str],
    everyday_words: list[str],
    title: str,
    meta_percent: float,
    everyday_percent: float,
) -> str | None:
    """Генерирует облако дихотомии языка (метафизика vs быт). Два облака стопкой."""
    if not metaphysics_words and not everyday_words:
        return None

    total_words = len(metaphysics_words) + len(everyday_words)
    if total_words < 5:
        return None

    try:
        path = f"dichotomy_{username}.png"
        clean_title = _clean_title(title)

        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        next_y = _add_title(fig, 'Глубина vs Повседневность', clean_title)

        # Статистика
        stats_text = f"Абстрактное: {meta_percent:.1f}%  •  Конкретное: {everyday_percent:.1f}%"
        fig.text(0.5, next_y, stats_text, fontsize=13, ha='center', color=TEXT_GRAY,
                 style='italic')

        # Верхнее облако — метафизика (фиолетовый/синий)
        ax1 = fig.add_axes([0.04, 0.49, 0.92, 0.36])
        if metaphysics_words:
            def meta_color(word, font_size, position, orientation, random_state=None, **kwargs):
                return random.choice([ACCENT_PURPLE, ACCENT_BLUE, '#a78bfa', '#818cf8'])

            wc_meta = WordCloud(
                width=800, height=500,
                background_color=BACKGROUND_COLOR,
                color_func=meta_color,
                max_words=50,
                min_font_size=10,
                prefer_horizontal=True,
                mode='RGB',
            ).generate(" ".join(metaphysics_words))
            ax1.imshow(wc_meta.to_image(), interpolation='bilinear')
        ax1.axis("off")
        ax1.set_title("АБСТРАКТНОЕ: ЧУВСТВА, СМЫСЛЫ, ИДЕИ", fontsize=12, fontweight='bold',
                       color=TEXT_WHITE, pad=8)

        # Нижнее облако — быт (зелёный/жёлтый)
        ax2 = fig.add_axes([0.04, 0.10, 0.92, 0.36])
        if everyday_words:
            def everyday_color(word, font_size, position, orientation, random_state=None, **kwargs):
                return random.choice(['#ff6b35', '#ff8c42', '#ffa726', '#ffb74d', '#fbbf24'])

            wc_everyday = WordCloud(
                width=800, height=500,
                background_color=BACKGROUND_COLOR,
                color_func=everyday_color,
                max_words=50,
                min_font_size=10,
                prefer_horizontal=True,
                mode='RGB',
            ).generate(" ".join(everyday_words))
            ax2.imshow(wc_everyday.to_image(), interpolation='bilinear')
        ax2.axis("off")
        ax2.set_title("КОНКРЕТНОЕ: ВЕЩИ, ДЕЙСТВИЯ, БЫТ", fontsize=12, fontweight='bold',
                       color=TEXT_WHITE, pad=8)

        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
        plt.close(fig)

        logger.info(f"Создано облако дихотомии: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания облака дихотомии: {e}")
        return None


def generate_sentiment_dual_cloud(
    username: str,
    pos_words: list[str],
    agg_words: list[str],
    title: str,
    pos_percent: float,
    agg_percent: float,
) -> str | None:
    """Генерирует двойное облако тональности: позитив и негатив (стопкой)."""
    total_words = len(pos_words) + len(agg_words)
    if total_words < 5:
        return None

    try:
        path = f"sentiment_{username}.png"
        clean_title = _clean_title(title)

        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        next_y = _add_title(fig, 'Тональность канала', clean_title)

        # Статистика
        stats_text = f"Позитив: {pos_percent:.1f}%  •  Негатив: {agg_percent:.1f}%"
        fig.text(0.5, next_y, stats_text, fontsize=13, ha='center', color=TEXT_GRAY,
                 style='italic')

        # Верхнее облако — позитив (зелёные оттенки)
        ax1 = fig.add_axes([0.04, 0.49, 0.92, 0.36])
        if pos_words:
            def pos_color(word, font_size, position, orientation, random_state=None, **kwargs):
                return random.choice([ACCENT_GREEN, '#34d399', '#6ee7b7', '#a7f3d0'])

            wc_pos = WordCloud(
                width=800, height=500,
                background_color=BACKGROUND_COLOR,
                color_func=pos_color,
                max_words=50,
                min_font_size=10,
                prefer_horizontal=True,
                mode='RGB',
            ).generate(" ".join(pos_words))
            ax1.imshow(wc_pos.to_image(), interpolation='bilinear')
        ax1.axis("off")
        ax1.set_title("ПОЗИТИВ 😊", fontsize=14, fontweight='bold', color=TEXT_WHITE, pad=14)

        # Нижнее облако — негатив (красно-розовые)
        ax2 = fig.add_axes([0.04, 0.10, 0.92, 0.36])
        if agg_words:
            def agg_color(word, font_size, position, orientation, random_state=None, **kwargs):
                return random.choice([ACCENT_PINK, '#ef4444', '#f87171', '#dc2626'])

            wc_agg = WordCloud(
                width=800, height=500,
                background_color=BACKGROUND_COLOR,
                color_func=agg_color,
                max_words=50,
                min_font_size=10,
                prefer_horizontal=True,
                mode='RGB',
            ).generate(" ".join(agg_words))
            ax2.imshow(wc_agg.to_image(), interpolation='bilinear')
        ax2.axis("off")
        ax2.set_title("НЕГАТИВ 😡", fontsize=14, fontweight='bold', color=TEXT_WHITE, pad=14)

        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
        plt.close(fig)

        logger.info(f"Создано двойное облако тональности: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания облака тональности: {e}")
        return None
