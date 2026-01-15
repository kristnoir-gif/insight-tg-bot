"""
Генерация графиков и диаграмм.
"""
import re
import logging
from collections import Counter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np

from config import DPI, BACKGROUND_COLOR, WATERMARK_TEXT, WATERMARK_COLOR

logger = logging.getLogger(__name__)


def _clean_title(title: str, max_length: int = 30) -> str:
    """
    Очищает название канала от спецсимволов и обрезает длинные названия.

    Args:
        title: Название канала.
        max_length: Максимальная длина (по умолчанию 30 символов).

    Returns:
        Очищенное и обрезанное название.
    """
    cleaned = re.sub(r'[^\w\s-]', '', title).strip()
    if len(cleaned) > max_length:
        return cleaned[:max_length].rstrip() + '...'
    return cleaned


def _setup_figure(figsize: tuple[int, int] = (12, 7)) -> tuple[plt.Figure, plt.Axes]:
    """Создаёт фигуру с базовыми настройками."""
    fig, ax = plt.subplots(figsize=figsize, facecolor=BACKGROUND_COLOR)
    ax.set_facecolor(BACKGROUND_COLOR)
    return fig, ax


def _add_watermark(fig: plt.Figure, y: float = 0.03) -> None:
    """Добавляет водяной знак."""
    fig.text(
        0.5, y, WATERMARK_TEXT,
        fontsize=14, ha='center', color=WATERMARK_COLOR, alpha=0.9, fontweight='bold'
    )


def _style_axes(ax: plt.Axes) -> None:
    """Применяет стандартный стиль к осям."""
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)


def generate_top_words_chart(
    username: str,
    word_counter: Counter,
    title: str,
    top_n: int = 15
) -> str | None:
    """
    Генерирует график топ-N ключевых слов.

    Args:
        username: Имя пользователя/канала.
        word_counter: Counter со словами.
        title: Название канала.
        top_n: Количество слов в топе.

    Returns:
        Путь к файлу или None.
    """
    try:
        top_words = word_counter.most_common(top_n)
        if not top_words:
            return None

        labels = [x[0].upper() for x in top_words][::-1]
        counts = [x[1] for x in top_words][::-1]

        path = f"graph_{username}.png"
        fig, ax = _setup_figure()

        colors = cm.plasma(np.linspace(0.2, 0.8, len(labels)))
        bars = ax.barh(labels, counts, color=colors, edgecolor='white', linewidth=1)

        clean_title = _clean_title(title)
        fig.suptitle(
            f"Топ-{top_n} ключевых слов канала {clean_title}",
            fontsize=20, fontweight='bold', color='#2d3436', y=0.96
        )

        for bar in bars:
            width = bar.get_width()
            ax.text(
                width + (max(counts) * 0.01), bar.get_y() + bar.get_height() / 2,
                f'{int(width)}', va='center', fontsize=13, fontweight='bold', color='#2d3436'
            )

        ax.tick_params(axis='y', pad=10, labelsize=11)
        _add_watermark(fig)
        _style_axes(ax)

        plt.tight_layout(rect=[0.02, 0.08, 0.98, 0.92])
        plt.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
        plt.close(fig)

        logger.info(f"Создан график топ слов: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания графика топ слов: {e}")
        return None


def generate_weekday_chart(
    username: str,
    avg_lens: dict[int, float],
    title: str
) -> str | None:
    """
    Генерирует график средней длины поста по дням недели.

    Args:
        username: Имя пользователя/канала.
        avg_lens: Словарь {день_недели: средняя_длина}.
        title: Название канала.

    Returns:
        Путь к файлу или None.
    """
    try:
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        values = [avg_lens.get(i, 0) for i in range(7)]

        path = f"weekday_{username}.png"
        fig, ax = _setup_figure()

        colors = cm.viridis(np.linspace(0.2, 0.8, 7))
        bars = ax.bar(days, values, color=colors, edgecolor='white', linewidth=1)

        clean_title = _clean_title(title)
        fig.suptitle(
            f"Средняя длина поста по дням недели: {clean_title}",
            fontsize=20, fontweight='bold', color='#2d3436', y=0.96
        )

        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2, height + max(values) * 0.01,
                f'{round(height, 1)}', ha='center', fontsize=13, fontweight='bold', color='#2d3436'
            )

        _add_watermark(fig)
        _style_axes(ax)

        plt.tight_layout(rect=[0.02, 0.08, 0.98, 0.92])
        plt.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
        plt.close(fig)

        logger.info(f"Создан график по дням недели: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания графика по дням: {e}")
        return None


def generate_hour_chart(
    username: str,
    hour_counts: dict[int, int],
    title: str
) -> str | None:
    """
    Генерирует график времени публикаций.

    Args:
        username: Имя пользователя/канала.
        hour_counts: Словарь {час: количество_постов}.
        title: Название канала.

    Returns:
        Путь к файлу или None.
    """
    try:
        hours = list(range(24))
        values = [hour_counts.get(h, 0) for h in hours]
        max_val = max(values) if values else 1

        path = f"hour_{username}.png"
        fig, ax = plt.subplots(figsize=(14, 7.5), facecolor=BACKGROUND_COLOR)
        ax.set_facecolor(BACKGROUND_COLOR)

        # Цвета по времени суток
        colors = []
        for h in hours:
            if 0 <= h < 6 or 21 <= h <= 23:
                colors.append('#4b5563')  # Ночь
            elif 6 <= h < 9 or 18 <= h < 21:
                colors.append('#f59e0b')  # Утро/вечер
            else:
                colors.append('#3b82f6')  # День

        bars = ax.bar(hours, values, color=colors, width=0.82, edgecolor='white', linewidth=0.4)

        clean_title = _clean_title(title)
        fig.suptitle(
            f"Время публикаций постов • {clean_title}",
            fontsize=20, fontweight='bold', color='#2d3436', y=0.96
        )

        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2, height + max_val * 0.03,
                    f'{int(height)}', ha='center', va='bottom', fontsize=10, fontweight='bold', color='#111827'
                )

        ax.set_xticks(hours)
        ax.set_xticklabels([f"{h:02d}:00" for h in hours], fontsize=9, rotation=45, ha='right')
        ax.set_yticks(np.arange(0, max_val + max_val * 0.15, max(5, int(max_val / 5))))

        ax.set_xlabel("Час суток (московское время)", fontsize=12, labelpad=10)
        ax.set_ylabel("Количество постов", fontsize=12, labelpad=10)

        ax.grid(axis='y', linestyle='--', alpha=0.3, color='gray')
        _style_axes(ax)
        _add_watermark(fig)

        plt.tight_layout(rect=[0.04, 0.12, 0.96, 0.92])
        plt.savefig(path, dpi=160, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)

        logger.info(f"Создан график по часам: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания графика по часам: {e}")
        return None


def generate_names_chart(
    username: str,
    top_names: list[tuple[str, int]],
    title: str,
    total_unique_names: int = 0,
    total_mentions: int = 0,
    min_mentions: int = 2,
    max_entries: int = 30
) -> str | None:
    """
    Генерирует график топ упомянутых личностей (писатели, деятели культуры и т.д.).

    Args:
        username: Имя пользователя/канала.
        top_names: Список кортежей (имя, количество).
        title: Название канала.
        total_unique_names: Общее количество уникальных имён.
        total_mentions: Общее количество упоминаний.
        min_mentions: Минимальное количество упоминаний для отображения.
        max_entries: Максимальное количество записей на графике.

    Returns:
        Путь к файлу или None.
    """
    try:
        # Минимум 3 уникальных имени для генерации графика
        if len(top_names) < 3:
            return None

        filtered = [item for item in top_names if item[1] >= min_mentions] or top_names[:max_entries]
        filtered = sorted(filtered, key=lambda x: x[1], reverse=True)[:max_entries]

        if not filtered:
            return None

        labels = [x[0] for x in filtered][::-1]
        counts = [x[1] for x in filtered][::-1]

        # Динамическая высота в зависимости от количества имён
        fig_height = max(8, min(14, len(labels) * 0.4 + 2))
        path = f"names_{username}.png"
        fig, ax = plt.subplots(figsize=(14, fig_height), facecolor=BACKGROUND_COLOR)
        ax.set_facecolor(BACKGROUND_COLOR)

        # Градиент от тёплых к холодным цветам
        colors = cm.plasma(np.linspace(0.15, 0.85, len(labels)))
        bars = ax.barh(labels, counts, color=colors, height=0.7, edgecolor='white', linewidth=0.8)

        clean_title = _clean_title(title)

        # Заголовок
        fig.suptitle(
            f"Топ упомянутых личностей • {clean_title}",
            fontsize=18, fontweight='bold', color='#2d3436', y=0.98
        )

        # Подзаголовок со статистикой
        if total_unique_names > 0:
            subtitle = f"Уникальных имён: {total_unique_names}"
            if total_mentions > 0:
                subtitle += f" • Всего упоминаний: {total_mentions}"
            fig.text(
                0.5, 0.94, subtitle,
                fontsize=11, ha='center', va='center', color='#636e72', style='italic'
            )

        # Подписи значений на барах
        for bar in bars:
            width = bar.get_width()
            ax.text(
                width + max(counts) * 0.015, bar.get_y() + bar.get_height() / 2,
                f'{int(width)}', va='center', fontsize=11, fontweight='bold', color='#2d3436'
            )

        ax.set_xlim(0, max(counts) * 1.12 if counts else 10)
        ax.set_xlabel('Количество упоминаний', fontsize=11, labelpad=10, color='#2d3436')
        ax.tick_params(axis='y', labelsize=10, pad=10)
        ax.tick_params(axis='x', labelsize=9)
        ax.grid(axis='x', linestyle='--', alpha=0.3, color='gray')
        _style_axes(ax)
        _add_watermark(fig)

        plt.tight_layout(rect=[0.02, 0.07, 0.98, 0.91])
        plt.savefig(path, dpi=160, bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)

        logger.info(f"Создан график имён: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания графика имён: {e}")
        return None


def generate_phrases_chart(
    username: str,
    top_phrases: list[tuple[tuple[str, ...], int]],
    title: str,
    top_n: int = 10
) -> str | None:
    """
    Генерирует график топ фраз (триграмм).

    Args:
        username: Имя пользователя/канала.
        top_phrases: Список кортежей (триграмма, количество).
        title: Название канала.
        top_n: Количество фраз в топе.

    Returns:
        Путь к файлу или None.
    """
    try:
        if not top_phrases:
            return None

        top_phrases = top_phrases[:top_n]
        labels = [' '.join(x[0]).upper() for x in top_phrases][::-1]
        counts = [x[1] for x in top_phrases][::-1]

        path = f"phrases_{username}.png"
        fig, ax = _setup_figure()

        colors = cm.viridis(np.linspace(0.2, 0.8, len(labels)))
        bars = ax.barh(labels, counts, color=colors, edgecolor='white', linewidth=1)

        clean_title = _clean_title(title)
        fig.suptitle(
            f"Топ-{top_n} часто используемых фраз: {clean_title}",
            fontsize=20, fontweight='bold', color='#2d3436', y=0.96
        )

        for bar in bars:
            width = bar.get_width()
            ax.text(
                width + max(counts) * 0.01, bar.get_y() + bar.get_height() / 2,
                f'{int(width)}', va='center', fontsize=13, fontweight='bold', color='#2d3436'
            )

        ax.tick_params(axis='y', pad=10, labelsize=10)
        _add_watermark(fig)
        _style_axes(ax)

        plt.tight_layout(rect=[0.02, 0.08, 0.98, 0.92])
        plt.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
        plt.close(fig)

        logger.info(f"Создан график фраз: {path}")
        return path

    except Exception as e:
        logger.error(f"Ошибка создания графика фраз: {e}")
        return None
