"""
PDF экспорт отчёта анализа канала.
Использует matplotlib PdfPages — 0 новых зависимостей.
"""
import logging
import os
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from config import WATERMARK_TEXT

logger = logging.getLogger(__name__)


def generate_pdf_report(
    result,
    channel_name: str,
    output_path: str | None = None,
) -> str | None:
    """
    Генерирует PDF-отчёт из AnalysisResult.

    Собирает все сгенерированные PNG-графики в один PDF.

    Args:
        result: AnalysisResult с путями к графикам.
        channel_name: Название/юзернейм канала.
        output_path: Путь для сохранения PDF (если None — генерируется автоматически).

    Returns:
        Путь к PDF-файлу или None при ошибке.
    """
    if output_path is None:
        safe_name = channel_name.lower().lstrip("@").replace("/", "_")
        output_path = f"report_{safe_name}.pdf"

    try:
        image_paths = result.get_all_paths()
        existing_images = [p for p in image_paths if p and os.path.exists(p)]

        if not existing_images:
            logger.warning(f"PDF: нет изображений для канала {channel_name}")
            return None

        with PdfPages(output_path) as pdf:
            # Титульная страница
            fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape
            fig.patch.set_facecolor('#f8f9fa')

            fig.text(0.5, 0.65, f"Анализ канала", fontsize=16, ha='center',
                     color='#636e72', fontweight='normal')
            fig.text(0.5, 0.55, result.title or channel_name, fontsize=28, ha='center',
                     color='#2d3436', fontweight='bold')

            stats_lines = []
            if result.stats.unique_count > 0:
                stats_lines.append(f"Уникальных слов: {result.stats.unique_count}")
            if result.stats.avg_len > 0:
                stats_lines.append(f"Средняя длина поста: {result.stats.avg_len} слов")
            if result.subscribers > 0:
                stats_lines.append(f"Подписчиков: {result.subscribers:,}".replace(",", " "))

            for i, line in enumerate(stats_lines):
                fig.text(0.5, 0.42 - i * 0.05, line, fontsize=13, ha='center', color='#636e72')

            fig.text(0.5, 0.15, datetime.now().strftime('%d.%m.%Y %H:%M'),
                     fontsize=11, ha='center', color='#b2bec3')
            fig.text(0.5, 0.08, WATERMARK_TEXT, fontsize=10, ha='center',
                     color='#b2bec3', fontweight='bold')
            pdf.savefig(fig)
            plt.close(fig)

            # Страницы с графиками
            for img_path in existing_images:
                fig = plt.figure(figsize=(11.69, 8.27))
                fig.patch.set_facecolor('#f8f9fa')
                try:
                    img = plt.imread(img_path)
                    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
                    ax.imshow(img)
                    ax.axis('off')
                except Exception as e:
                    logger.warning(f"PDF: не удалось добавить {img_path}: {e}")
                    plt.close(fig)
                    continue
                pdf.savefig(fig)
                plt.close(fig)

        logger.info(f"PDF отчёт создан: {output_path} ({len(existing_images)} графиков)")
        return output_path

    except Exception as e:
        logger.error(f"Ошибка генерации PDF для {channel_name}: {e}")
        return None
