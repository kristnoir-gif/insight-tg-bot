"""Общие утилиты для модуля визуализации."""
import re


def clean_title(title: str, max_line_length: int = 25) -> str:
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
