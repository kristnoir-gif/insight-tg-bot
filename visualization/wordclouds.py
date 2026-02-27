"""
Генерация облаков слов.
"""
import re
import logging
from typing import Literal, Callable
import random

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.cm as cm
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

# Минимальная яркость цвета (0.0-1.0), чтобы избежать слишком светлых слов
MIN_COLOR_INTENSITY = 0.3


def _make_color_func(colormap_name: str) -> Callable:
    """
    Создаёт функцию окраски слов с ограничением яркости.
    Использует только тёмную часть colormap (от MIN_COLOR_INTENSITY до 1.0).
    """
    cmap = cm.get_cmap(colormap_name)

    def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        # Используем диапазон от MIN_COLOR_INTENSITY до 1.0
        intensity = random.uniform(MIN_COLOR_INTENSITY, 1.0)
        rgba = cmap(intensity)
        # Конвертируем в RGB строку
        return f"rgb({int(rgba[0]*255)}, {int(rgba[1]*255)}, {int(rgba[2]*255)})"

    return color_func


def _clean_title(title: str, max_line_length: int = 25) -> str:
    """
    Очищает название канала и разбивает на 2 строки если слишком длинное.

    Args:
        title: Название канала.
        max_line_length: Максимальная длина строки (по умолчанию 25 символов).

    Returns:
        Очищенное название (с переносом если длинное).
    """
    cleaned = re.sub(r'[^\w\s-]', '', title).strip()

    if len(cleaned) <= max_line_length:
        return cleaned

    # Разбиваем на 2 строки по словам
    words = cleaned.split()
    line1 = []
    line2 = []
    current_len = 0

    for word in words:
        if current_len + len(word) + 1 <= max_line_length:
            line1.append(word)
            current_len += len(word) + 1
        else:
            line2.append(word)

    if line2:
        return ' '.join(line1) + '\n' + ' '.join(line2)
    return ' '.join(line1)


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
        # Используем кастомную функцию окраски для избежания светлых цветов
        color_func = _make_color_func(colormap)

        wc = WordCloud(
            width=CLOUD_WIDTH,
            height=CLOUD_HEIGHT,
            background_color='white',
            color_func=color_func,
            max_words=max_words,
            min_font_size=10,
            prefer_horizontal=True,
        ).generate(" ".join(words))

        fig = plt.figure(figsize=(12, 7), facecolor='white')
        ax = fig.add_axes([0.0, 0.08, 1.0, 0.82])
        ax.imshow(wc.to_image(), interpolation='bilinear')
        ax.axis("off")

        fig.text(
            0.5, 0.94, title_text,
            fontsize=22, fontweight='bold', ha='center', va='center', color='#2d3436'
        )
        fig.text(
            0.5, 0.03, WATERMARK_TEXT,
            fontsize=11, ha='center', color=WATERMARK_COLOR, alpha=0.9, fontweight='bold'
        )

        fig.savefig(path, dpi=DPI, facecolor='white')
        plt.close(fig)

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
    colormap = 'Greens' if sentiment == 'positive' else 'OrRd'
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
        colormap='Reds',
    )


def generate_register_cloud(
    username: str,
    caps_words: list[str],
    lower_words: list[str],
    title: str,
    caps_percent: float,
    lower_percent: float,
) -> str | None:
    """
    Генерирует облако регистра (CAPS vs lowercase).

    Слова окрашиваются по регистру:
    - CAPS слова — красный/огненный цвет
    - lowercase слова — синий/спокойный цвет

    Args:
        username: Имя пользователя/канала.
        caps_words: Список слов в CAPS.
        lower_words: Список слов в lowercase.
        title: Название канала.
        caps_percent: Процент CAPS слов.
        lower_percent: Процент lowercase слов.

    Returns:
        Путь к файлу или None.
    """
    # Нужно хотя бы немного слов
    if not caps_words and not lower_words:
        return None

    # Если слов очень мало
    total_words = len(caps_words) + len(lower_words)
    if total_words < 10:
        return None

    try:
        path = f"register_{username}.png"
        clean_title = _clean_title(title)

        # Создаём словарь слово -> регистр для окраски
        word_register: dict[str, str] = {}
        for word in caps_words:
            word_register[word.upper()] = 'caps'
        for word in lower_words:
            word_register[word.lower()] = 'lower'

        # Объединяем все слова (сохраняя регистр для отображения)
        all_words = [w.upper() for w in caps_words] + [w.lower() for w in lower_words]

        if not all_words:
            return None

        # Функция окраски по регистру
        def register_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
            # Определяем регистр по слову
            if word.isupper():
                # CAPS — огненные оттенки (красный/оранжевый)
                r = random.randint(200, 255)
                g = random.randint(50, 120)
                b = random.randint(30, 80)
            else:
                # lowercase — спокойные оттенки (синий/фиолетовый)
                r = random.randint(60, 130)
                g = random.randint(80, 160)
                b = random.randint(180, 255)
            return f"rgb({r}, {g}, {b})"

        wc = WordCloud(
            width=CLOUD_WIDTH,
            height=CLOUD_HEIGHT,
            background_color='white',
            color_func=register_color_func,
            max_words=MAX_WORDS_CLOUD,
            min_font_size=10,
            prefer_horizontal=True,
        ).generate(" ".join(all_words))

        fig = plt.figure(figsize=(12, 7), facecolor='white')
        ax = fig.add_axes([0.0, 0.08, 1.0, 0.78])
        ax.imshow(wc.to_image(), interpolation='bilinear')
        ax.axis("off")

        # Заголовок
        fig.text(
            0.5, 0.94, f"Облако регистра: {clean_title}",
            fontsize=20, fontweight='bold', ha='center', va='center', color='#2d3436'
        )

        # Статистика процентов
        stats_text = f"🔥 CAPS: {caps_percent:.1f}%  |  💙 lowercase: {lower_percent:.1f}%"
        fig.text(
            0.5, 0.88, stats_text,
            fontsize=14, ha='center', va='center', color='#636e72', style='italic'
        )

        # Водяной знак
        fig.text(
            0.5, 0.03, WATERMARK_TEXT,
            fontsize=11, ha='center', color=WATERMARK_COLOR, alpha=0.9, fontweight='bold'
        )

        fig.savefig(path, dpi=DPI, facecolor='white')
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
    """
    Генерирует облако дихотомии языка (метафизика vs быт).

    Args:
        username: Имя пользователя/канала.
        metaphysics_words: Список слов метафизики.
        everyday_words: Список слов быта.
        title: Название канала.
        meta_percent: Процент метафизических слов.
        everyday_percent: Процент бытовых слов.

    Returns:
        Путь к файлу или None.
    """
    # Нужно хотя бы немного слов в одной из категорий
    if not metaphysics_words and not everyday_words:
        return None

    total_words = len(metaphysics_words) + len(everyday_words)
    if total_words < 5:
        return None

    try:
        path = f"dichotomy_{username}.png"
        clean_title = _clean_title(title)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7), facecolor='white')

        # Функция окраски для метафизики (тёмные оттенки)
        def meta_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
            # Тёмно-коричневый / чёрный
            r = random.randint(30, 80)
            g = random.randint(20, 50)
            b = random.randint(10, 40)
            return f"rgb({r}, {g}, {b})"

        # Функция окраски для быта (серые оттенки)
        def everyday_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
            # Серый
            gray = random.randint(80, 140)
            return f"rgb({gray}, {gray}, {gray})"

        # Левое облако - метафизика
        if metaphysics_words:
            wc_meta = WordCloud(
                width=500,
                height=400,
                background_color='white',
                color_func=meta_color_func,
                max_words=50,
                min_font_size=10,
                prefer_horizontal=True,
            ).generate(" ".join(metaphysics_words))
            ax1.imshow(wc_meta.to_image(), interpolation='bilinear')
        ax1.axis("off")
        ax1.set_title("ВЫСОКИЙ РЕГИСТР\n(МЕТАФИЗИКА)", fontsize=12, fontweight='bold', color='#2d3436', pad=10)

        # Правое облако - быт
        if everyday_words:
            wc_everyday = WordCloud(
                width=500,
                height=400,
                background_color='white',
                color_func=everyday_color_func,
                max_words=50,
                min_font_size=10,
                prefer_horizontal=True,
            ).generate(" ".join(everyday_words))
            ax2.imshow(wc_everyday.to_image(), interpolation='bilinear')
        ax2.axis("off")
        ax2.set_title("НИЗКИЙ РЕГИСТР\n(БЫТ И ВЕЩИ)", fontsize=12, fontweight='bold', color='#636e72', pad=10)

        # Главный заголовок
        fig.suptitle(
            f"Дихотомия языка: {clean_title}",
            fontsize=18, fontweight='bold', color='#2d3436', y=0.96
        )

        # Статистика процентов
        stats_text = f"Метафизика: {meta_percent:.1f}%  |  Быт: {everyday_percent:.1f}%"
        fig.text(
            0.5, 0.88, stats_text,
            fontsize=13, ha='center', va='center', color='#636e72', style='italic'
        )

        # Водяной знак
        fig.text(
            0.5, 0.03, WATERMARK_TEXT,
            fontsize=11, ha='center', color=WATERMARK_COLOR, alpha=0.9, fontweight='bold'
        )

        fig.tight_layout(rect=[0.02, 0.08, 0.98, 0.85])
        fig.savefig(path, dpi=DPI, facecolor='white')
        plt.close(fig)

        logger.info(f"Создано облако дихотомии: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания облака дихотомии: {e}")
        return None
