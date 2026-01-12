"""
Генерация облаков слов.
"""
import re
import logging
from typing import Literal

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from wordcloud import WordCloud

from config import (
    DPI,
    MAX_WORDS_CLOUD,
    MAX_WORDS_SENTIMENT,
    CLOUD_WIDTH,
    CLOUD_HEIGHT,
    WATERMARK_TEXT,
    WATERMARK_COLOR,
)

logger = logging.getLogger(__name__)

SentimentType = Literal['positive', 'aggressive']


def _clean_title(title: str) -> str:
    """Очищает название канала от спецсимволов."""
    return re.sub(r'[^\w\s-]', '', title).strip()


def _create_cloud(
    words: list[str],
    path: str,
    title_text: str,
    colormap: str,
    max_words: int = MAX_WORDS_SENTIMENT,
) -> str | None:
    """
    Базовая функция создания облака слов.

    Args:
        words: Список слов.
        path: Путь для сохранения изображения.
        title_text: Заголовок.
        colormap: Цветовая схема matplotlib.
        max_words: Максимальное количество слов.

    Returns:
        Путь к файлу или None при ошибке.
    """
    if not words:
        return None

    try:
        wc = WordCloud(
            width=CLOUD_WIDTH,
            height=CLOUD_HEIGHT,
            background_color='white',
            colormap=colormap,
            max_words=max_words,
            min_font_size=10,
            prefer_horizontal=True,
        ).generate(" ".join(words))

        fig = plt.figure(figsize=(12, 7), facecolor='white')
        ax = fig.add_axes([0.0, 0.08, 1.0, 0.82])
        ax.imshow(wc.to_image(), interpolation='bilinear')
        ax.axis("off")

        fig.text(
            0.5, 0.95, title_text,
            fontsize=24, fontweight='bold', ha='center', color='#1a1a1a'
        )
        fig.text(
            0.5, 0.03, WATERMARK_TEXT,
            fontsize=14, ha='center', color=WATERMARK_COLOR, alpha=0.9, fontweight='bold'
        )

        plt.savefig(path, dpi=DPI, facecolor='white')
        plt.close()

        logger.info(f"Создано облако слов: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания облака слов: {e}")
        return None


def generate_main_cloud(username: str, words: list[str], title: str) -> str | None:
    """
    Генерирует основное облако смыслов.

    Args:
        username: Имя пользователя/канала.
        words: Список слов.
        title: Название канала.

    Returns:
        Путь к файлу или None.
    """
    path = f"cloud_{username}.png"
    clean_title = _clean_title(title)
    return _create_cloud(
        words=words,
        path=path,
        title_text=f"Облако смыслов канала: {clean_title}",
        colormap='magma',
        max_words=MAX_WORDS_CLOUD,
    )


def generate_sentiment_cloud(
    username: str,
    words: list[str],
    title: str,
    sentiment: SentimentType = 'positive'
) -> str | None:
    """
    Генерирует облако слов по настроению.

    Args:
        username: Имя пользователя/канала.
        words: Список слов.
        title: Название канала.
        sentiment: Тип настроения ('positive' или 'aggressive').

    Returns:
        Путь к файлу или None.
    """
    colormap = 'YlGn' if sentiment == 'positive' else 'OrRd'
    header = "Облако позитивных слов" if sentiment == 'positive' else "Облако негативных слов"

    path = f"{sentiment}_{username}.png"
    clean_title = _clean_title(title)

    return _create_cloud(
        words=words,
        path=path,
        title_text=f"{header} канала: {clean_title}",
        colormap=colormap,
    )


def generate_mats_cloud(username: str, words: list[str], title: str) -> str | None:
    """
    Генерирует облако ненормативной лексики.

    Args:
        username: Имя пользователя/канала.
        words: Список слов.
        title: Название канала.

    Returns:
        Путь к файлу или None.
    """
    path = f"mats_{username}.png"
    clean_title = _clean_title(title)

    return _create_cloud(
        words=words,
        path=path,
        title_text=f"Облако мата канала: {clean_title}",
        colormap='autumn',
    )
