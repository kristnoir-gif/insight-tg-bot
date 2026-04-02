"""
Генерация графиков и диаграмм.
Spotify Wrapped style: тёмный фон, яркие градиенты, вертикальный формат 9:16.
"""
import logging
from collections import Counter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np

from config import (
    DPI, FIGURE_SIZE, BACKGROUND_COLOR, WATERMARK_TEXT, WATERMARK_COLOR,
    ACCENT_GREEN, ACCENT_BLUE, ACCENT_PINK, TEXT_WHITE, TEXT_GRAY,
)
from visualization.utils import clean_title as _clean_title

logger = logging.getLogger(__name__)


def _add_watermark(fig: plt.Figure) -> None:
    """Добавляет водяной знак."""
    fig.text(
        0.5, 0.05, WATERMARK_TEXT,
        fontsize=13, ha='center', va='bottom', color=WATERMARK_COLOR,
        alpha=0.8, fontweight='bold', linespacing=1.5
    )


def _style_axes(ax: plt.Axes) -> None:
    """Применяет тёмный стиль к осям."""
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(TEXT_GRAY)
    ax.spines['left'].set_color(TEXT_GRAY)


def _add_title(fig: plt.Figure, title: str, channel: str) -> float:
    """Добавляет заголовок + название канала. Возвращает y для следующего элемента."""
    fig.text(0.5, 0.96, title, fontsize=22, fontweight='bold',
             ha='center', color=TEXT_WHITE)
    has_newline = '\n' in channel
    channel_y = 0.92 if has_newline else 0.93
    fig.text(0.5, channel_y, channel, fontsize=16, ha='center', color=ACCENT_GREEN,
             va='top')
    return (channel_y - 0.05) if has_newline else (channel_y - 0.03)


def generate_top_words_chart(
    username: str,
    word_counter: Counter,
    title: str,
    top_n: int = 15
) -> str | None:
    """Генерирует график топ-N ключевых слов."""
    try:
        top_words = word_counter.most_common(top_n)
        if not top_words:
            return None

        raw_labels = [x[0].upper() for x in top_words][::-1]
        counts = [x[1] for x in top_words][::-1]

        # Длинные слова переносим на две строки
        max_line = 14
        labels = []
        for l in raw_labels:
            if len(l) <= max_line:
                labels.append(l)
            else:
                words = l.split()
                line1, line2 = [], []
                cur = 0
                for w in words:
                    if cur + len(w) + 1 <= max_line:
                        line1.append(w)
                        cur += len(w) + 1
                    else:
                        line2.append(w)
                labels.append(' '.join(line1) + '\n' + ' '.join(line2))

        path = f"graph_{username}.png"
        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        _add_title(fig, f'Топ-{top_n} ключевых слов', _clean_title(title))

        ax = fig.add_axes([0.24, 0.12, 0.69, 0.76])
        ax.set_facecolor(BACKGROUND_COLOR)

        colors = [plt.cm.cool(i / len(labels)) for i in range(len(labels))]
        bars = ax.barh(labels, counts, color=colors, height=0.65, edgecolor='none')

        for bar in bars:
            width = bar.get_width()
            ax.text(width + max(counts) * 0.02, bar.get_y() + bar.get_height() / 2,
                    f'{int(width)}', va='center', fontsize=11, fontweight='bold',
                    color=TEXT_GRAY)

        ax.tick_params(axis='y', labelsize=11, colors=TEXT_WHITE, pad=8)
        ax.tick_params(axis='x', colors=TEXT_GRAY, labelsize=9)
        ax.set_xlim(0, max(counts) * 1.15)
        _style_axes(ax)
        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
        plt.close(fig)
        logger.info(f"Создан график топ слов: {path}")
        return path
    except Exception as e:
        logger.error(f"Ошибка создания графика топ слов: {e}")
        return None


def generate_weekday_chart(
    username: str,
    counts: dict[int, int],
    title: str
) -> str | None:
    """Генерирует график количества постов по дням недели."""
    try:
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        values = [counts.get(i, 0) for i in range(7)]

        path = f"weekday_{username}.png"
        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        _add_title(fig, 'Посты по дням недели', _clean_title(title))

        ax = fig.add_axes([0.12, 0.12, 0.80, 0.72])
        ax.set_facecolor(BACKGROUND_COLOR)

        colors = [plt.cm.cool(i / 6) for i in range(7)]
        bars = ax.bar(days, values, color=colors, width=0.6, edgecolor='none')

        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, height + max(values) * 0.02,
                    f'{int(height)}', ha='center', fontsize=14, fontweight='bold',
                    color=TEXT_WHITE)

        ax.tick_params(axis='x', labelsize=14, colors=TEXT_WHITE)
        ax.tick_params(axis='y', colors=TEXT_GRAY, labelsize=10)
        _style_axes(ax)
        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
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
    """Генерирует график времени публикаций."""
    try:
        hours = list(range(24))
        values = [hour_counts.get(h, 0) for h in hours]
        max_val = max(values) if values else 1

        path = f"hour_{username}.png"
        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        _add_title(fig, 'Время публикаций', _clean_title(title))

        ax = fig.add_axes([0.15, 0.12, 0.78, 0.76])
        ax.set_facecolor(BACKGROUND_COLOR)

        colors = [plt.cm.cool(v / max_val) if max_val > 0 else plt.cm.cool(0) for v in values]
        hour_labels = [f'{h:02d}:00' for h in hours]
        bars = ax.barh(hour_labels, values, color=colors, height=0.7, edgecolor='none')

        for bar in bars:
            width = bar.get_width()
            if width > 0:
                ax.text(width + max_val * 0.02, bar.get_y() + bar.get_height() / 2,
                        f'{int(width)}', va='center', fontsize=9, color=TEXT_GRAY)

        ax.invert_yaxis()
        ax.tick_params(axis='y', labelsize=9, colors=TEXT_WHITE, pad=5)
        ax.tick_params(axis='x', colors=TEXT_GRAY, labelsize=9)
        ax.set_xlim(0, max_val * 1.15)
        _style_axes(ax)
        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
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
    """Генерирует график топ упомянутых личностей."""
    try:
        if len(top_names) < 2:
            return None

        filtered = [item for item in top_names if item[1] >= min_mentions] or top_names[:max_entries]
        filtered = sorted(filtered, key=lambda x: x[1], reverse=True)[:max_entries]
        if not filtered:
            return None

        # Ограничиваем до 15 чтобы помещалось в стандартный формат 9:16
        filtered = filtered[:15]

        raw_labels = [x[0] for x in filtered][::-1]
        counts = [x[1] for x in filtered][::-1]

        # Длинные имена переносим на две строки
        max_line = 14
        labels = []
        for l in raw_labels:
            if len(l) <= max_line:
                labels.append(l)
            else:
                words = l.split()
                line1, line2 = [], []
                cur = 0
                for w in words:
                    if cur + len(w) + 1 <= max_line:
                        line1.append(w)
                        cur += len(w) + 1
                    else:
                        line2.append(w)
                labels.append(' '.join(line1) + '\n' + ' '.join(line2))

        path = f"names_{username}.png"
        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)

        # Заголовок
        next_y = _add_title(fig, 'Топ упомянутых личностей', _clean_title(title))

        # Подзаголовок со статистикой
        if total_unique_names > 0:
            subtitle = f"Уникальных: {total_unique_names}"
            if total_mentions > 0:
                subtitle += f" • Упоминаний: {total_mentions}"
            fig.text(0.5, next_y, subtitle, fontsize=11, ha='center', color=TEXT_GRAY,
                     style='italic')

        ax = fig.add_axes([0.28, 0.12, 0.67, 0.73])
        ax.set_facecolor(BACKGROUND_COLOR)

        colors = [plt.cm.cool(i / len(labels)) for i in range(len(labels))]
        bars = ax.barh(labels, counts, color=colors, height=0.65, edgecolor='none')

        for bar in bars:
            width = bar.get_width()
            ax.text(width + max(counts) * 0.02, bar.get_y() + bar.get_height() / 2,
                    f'{int(width)}', va='center', fontsize=10, fontweight='bold',
                    color=TEXT_GRAY)

        ax.set_xlim(0, max(counts) * 1.15)
        ax.tick_params(axis='y', labelsize=10, colors=TEXT_WHITE, pad=8)
        ax.tick_params(axis='x', colors=TEXT_GRAY, labelsize=9)
        ax.grid(axis='x', linestyle='--', alpha=0.15, color=TEXT_GRAY)
        _style_axes(ax)
        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
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
    """Генерирует график топ фраз (триграмм)."""
    try:
        if not top_phrases:
            return None

        top_phrases = top_phrases[:top_n]
        # Без капса, длинные фразы переносим на две строки
        max_line = 16
        raw_labels = [' '.join(x[0]) for x in top_phrases][::-1]
        labels = []
        for l in raw_labels:
            if len(l) <= max_line:
                labels.append(l)
            else:
                words = l.split()
                line1, line2 = [], []
                cur = 0
                for w in words:
                    if cur + len(w) + 1 <= max_line:
                        line1.append(w)
                        cur += len(w) + 1
                    else:
                        line2.append(w)
                labels.append(' '.join(line1) + '\n' + ' '.join(line2))
        counts = [x[1] for x in top_phrases][::-1]

        path = f"phrases_{username}.png"
        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        _add_title(fig, f'Топ-{top_n} частых фраз', _clean_title(title))

        ax = fig.add_axes([0.32, 0.12, 0.62, 0.76])
        ax.set_facecolor(BACKGROUND_COLOR)

        colors = [plt.cm.cool(i / len(labels)) for i in range(len(labels))]
        bars = ax.barh(labels, counts, color=colors, height=0.65, edgecolor='none')

        for bar in bars:
            width = bar.get_width()
            ax.text(width + max(counts) * 0.02, bar.get_y() + bar.get_height() / 2,
                    f'{int(width)}', va='center', fontsize=12, fontweight='bold',
                    color=TEXT_GRAY)

        font_size = 9
        ax.tick_params(axis='y', pad=10, labelsize=font_size, colors=TEXT_WHITE)
        ax.tick_params(axis='x', colors=TEXT_GRAY, labelsize=9)
        ax.set_xlim(0, max(counts) * 1.15)
        _style_axes(ax)
        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
        plt.close(fig)
        logger.info(f"Создан график фраз: {path}")
        return path
    except Exception as e:
        logger.error(f"Ошибка создания графика фраз: {e}")
        return None


def generate_heatmap_chart(
    username: str,
    posts_times: list[tuple[int, int]],
    title: str
) -> str | None:
    """Генерирует тепловую карту активности (день недели × час)."""
    try:
        if not posts_times:
            return None

        matrix = np.zeros((7, 24), dtype=int)
        for weekday, hour in posts_times:
            matrix[weekday][hour] += 1

        path = f"heatmap_{username}.png"
        fig = plt.figure(figsize=FIGURE_SIZE, facecolor=BACKGROUND_COLOR)
        _add_title(fig, 'Тепловая карта активности', _clean_title(title))

        ax = fig.add_axes([0.12, 0.18, 0.82, 0.70])
        ax.set_facecolor(BACKGROUND_COLOR)

        im = ax.imshow(matrix, cmap='inferno', aspect='auto', interpolation='nearest')

        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        ax.set_yticks(range(7))
        ax.set_yticklabels(days, fontsize=12, fontweight='bold', color=TEXT_WHITE)
        ax.set_xticks(range(0, 24, 2))
        ax.set_xticklabels([f'{h:02d}' for h in range(0, 24, 2)], fontsize=10, color=TEXT_GRAY)
        ax.set_xlabel('Час (МСК)', fontsize=11, color=TEXT_GRAY, labelpad=8)
        ax.tick_params(axis='both', length=0)

        for i in range(7):
            for j in range(24):
                val = matrix[i][j]
                if val > 0:
                    color = TEXT_WHITE if val > matrix.max() * 0.5 else TEXT_GRAY
                    ax.text(j, i, str(val), ha='center', va='center',
                            fontsize=7, fontweight='bold', color=color)

        cbar = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.08, orientation='horizontal',
                            location='bottom', aspect=30)
        cbar.ax.tick_params(colors=TEXT_GRAY, labelsize=9)
        cbar.outline.set_edgecolor(TEXT_GRAY)

        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
        plt.close(fig)
        logger.info(f"Создана тепловая карта: {path}")
        return path
    except Exception as e:
        logger.error(f"Ошибка создания тепловой карты: {e}")
        return None


def generate_comparison_chart(
    channel1_name: str,
    channel2_name: str,
    stats1: dict,
    stats2: dict,
) -> str | None:
    """Генерирует радарную диаграмму сравнения двух каналов."""
    try:
        categories = ['Scream Index', 'Словарный запас', 'Длина постов', 'Репосты']
        n_cats = len(categories)

        raw1 = [stats1['scream'], stats1['vocab'], stats1['length'], stats1['reposts']]
        raw2 = [stats2['scream'], stats2['vocab'], stats2['length'], stats2['reposts']]

        normalized1 = []
        normalized2 = []
        for v1, v2 in zip(raw1, raw2):
            max_val = max(v1, v2, 1)
            normalized1.append(v1 / max_val * 100)
            normalized2.append(v2 / max_val * 100)

        angles = np.linspace(0, 2 * np.pi, n_cats, endpoint=False).tolist()
        normalized1 += [normalized1[0]]
        normalized2 += [normalized2[0]]
        angles += [angles[0]]

        path = "comparison_chart.png"
        fig, ax = plt.subplots(figsize=FIGURE_SIZE, subplot_kw=dict(polar=True),
                               facecolor=BACKGROUND_COLOR)
        ax.set_facecolor(BACKGROUND_COLOR)

        ax.fill(angles, normalized1, color=ACCENT_BLUE, alpha=0.25,
                label=_clean_title(channel1_name, 20))
        ax.plot(angles, normalized1, color=ACCENT_BLUE, linewidth=2)
        ax.fill(angles, normalized2, color=ACCENT_PINK, alpha=0.25,
                label=_clean_title(channel2_name, 20))
        ax.plot(angles, normalized2, color=ACCENT_PINK, linewidth=2)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontsize=12, fontweight='bold', color=TEXT_WHITE)
        ax.set_ylim(0, 110)
        ax.set_yticks([25, 50, 75, 100])
        ax.set_yticklabels(['25%', '50%', '75%', '100%'], fontsize=9, color=TEXT_GRAY)
        ax.tick_params(colors=TEXT_GRAY)
        ax.grid(color=TEXT_GRAY, alpha=0.3)

        clean1 = _clean_title(channel1_name, 15)
        clean2 = _clean_title(channel2_name, 15)
        fig.text(0.5, 0.94, f'Сравнение', fontsize=22, fontweight='bold',
                 ha='center', color=TEXT_WHITE)
        fig.text(0.5, 0.91, f'{clean1} vs {clean2}', fontsize=16,
                 ha='center', color=ACCENT_GREEN)

        ax.legend(loc='upper right', bbox_to_anchor=(1.15, 1.1), fontsize=11,
                  facecolor=BACKGROUND_COLOR, edgecolor=TEXT_GRAY, labelcolor=TEXT_WHITE)

        _add_watermark(fig)

        fig.savefig(path, dpi=DPI, bbox_inches='tight', facecolor=BACKGROUND_COLOR)
        plt.close(fig)
        logger.info(f"Создана радарная диаграмма сравнения: {path}")
        return path
    except Exception as e:
        logger.error(f"Ошибка создания радарной диаграммы: {e}")
        return None


def generate_mentions_chart(
    username: str,
    animal_counter: Counter,
    food_counter: Counter,
    city_counter: Counter,
    title: str,
    top_n: int = 10
) -> str | None:
    """Генерирует комбинированный квадратный график: животные, еда, города — три столбца."""
    try:
        sections = [
            ('Животные', animal_counter, plt.cm.cool),
            ('Еда и напитки', food_counter, plt.cm.autumn),
            ('Города', city_counter, plt.cm.winter),
        ]

        # Проверяем что хотя бы одна секция непустая
        has_data = any(c for _, c, _ in sections)
        if not has_data:
            return None

        path = f"mentions_{username}.png"
        # Квадратный формат
        fig_size = (12.8, 12.8)
        fig = plt.figure(figsize=fig_size, facecolor=BACKGROUND_COLOR)

        # Заголовок
        fig.text(0.5, 0.96, 'Что упоминается в канале', fontsize=24, fontweight='bold',
                 ha='center', color=TEXT_WHITE)
        fig.text(0.5, 0.93, _clean_title(title), fontsize=16, ha='center', color=ACCENT_GREEN)

        # Водяной знак
        fig.text(0.5, 0.02, WATERMARK_TEXT, fontsize=13, ha='center', va='bottom',
                 color=WATERMARK_COLOR, alpha=0.8, fontweight='bold', linespacing=1.5)

        for col_idx, (subtitle, counter, cmap) in enumerate(sections):
            top_items = counter.most_common(top_n)

            # Позиция столбца: три столбца
            col_width = 1.0 / 3
            left = col_idx * col_width
            ax = fig.add_axes([left + 0.09, 0.08, col_width - 0.10, 0.80])
            ax.set_facecolor(BACKGROUND_COLOR)

            if not top_items:
                ax.text(0.5, 0.5, 'Нет данных', ha='center', va='center',
                        fontsize=13, color=TEXT_GRAY, transform=ax.transAxes)
                ax.set_xticks([])
                ax.set_yticks([])
                for spine in ax.spines.values():
                    spine.set_visible(False)
            else:
                labels = [x[0] for x in top_items][::-1]
                counts = [x[1] for x in top_items][::-1]

                colors = [cmap(i / max(len(labels) - 1, 1)) for i in range(len(labels))]
                bars = ax.barh(labels, counts, color=colors, height=0.6, edgecolor='none')

                max_val = max(counts)
                for bar in bars:
                    width = bar.get_width()
                    # Число внутри бара если бар длинный, иначе справа
                    if width > max_val * 0.3:
                        ax.text(width - max_val * 0.03, bar.get_y() + bar.get_height() / 2,
                                f'{int(width)}', va='center', ha='right',
                                fontsize=10, fontweight='bold', color=BACKGROUND_COLOR)
                    else:
                        ax.text(width + max_val * 0.03, bar.get_y() + bar.get_height() / 2,
                                f'{int(width)}', va='center', ha='left',
                                fontsize=10, fontweight='bold', color=TEXT_GRAY)

                ax.tick_params(axis='y', labelsize=9, colors=TEXT_WHITE, pad=3)
                ax.set_xticks([])
                ax.set_xlim(0, max_val * 1.05)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['bottom'].set_visible(False)
                ax.spines['left'].set_color(TEXT_GRAY)

            # Подзаголовок секции
            ax.set_title(subtitle, fontsize=15, fontweight='bold', color=TEXT_WHITE, pad=12)

        fig.savefig(path, dpi=DPI, facecolor=BACKGROUND_COLOR)
        plt.close(fig)
        logger.info(f"Создан комбинированный график упоминаний: {path}")
        return path
    except Exception as e:
        logger.error(f"Ошибка создания графика упоминаний: {e}")
        return None
