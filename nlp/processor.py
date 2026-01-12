"""
Модуль обработки текста.
Извлечение и нормализация слов, эмодзи.
"""
import re
import logging
from typing import Literal
from enum import Enum

import emoji
import pymorphy2

from nlp.constants import (
    russian_stopwords,
    OBSCENE_ROOTS,
    PERSON_BLACKLIST,
)

logger = logging.getLogger(__name__)

# Инициализация морфологического анализатора
morph = pymorphy2.MorphAnalyzer()

ProcessingMode = Literal['normal', 'mats', 'person']


def get_clean_words(text: str, mode: ProcessingMode = 'normal') -> list[str]:
    """
    Извлекает и нормализует слова из текста.

    Args:
        text: Исходный текст для обработки.
        mode: Режим обработки:
            - 'normal': существительные и прилагательные без стоп-слов
            - 'mats': ненормативная лексика
            - 'person': имена собственные

    Returns:
        Список обработанных слов.
    """
    # Удаляем URL
    text = re.sub(r'http\S+', '', text)

    # Извлекаем кириллические слова
    words = re.findall(r'[а-яА-ЯёЁ]+', text)
    clean_words: list[str] = []

    for word in words:
        original_word = word
        low_word = word.lower()

        try:
            parsed = morph.parse(low_word)[0]
        except Exception as e:
            logger.debug(f"Ошибка парсинга слова '{low_word}': {e}")
            continue

        normal = parsed.normal_form

        # Исправление известных ошибок лемматизации
        if normal == 'деньга':
            normal = 'деньги'

        if mode == 'normal':
            if (len(normal) > 2
                and normal not in russian_stopwords
                and parsed.tag.POS in ('NOUN', 'ADJF')):
                clean_words.append(normal)

        elif mode == 'mats':
            if any(root in normal for root in OBSCENE_ROOTS):
                clean_words.append(normal)

        elif mode == 'person':
            tags = parsed.tag
            if (original_word[0].isupper()
                and len(normal) > 2
                and 'Name' in tags
                and normal not in PERSON_BLACKLIST):
                clean_words.append(original_word)

    return clean_words


def extract_emojis(text: str) -> list[str]:
    """
    Извлекает все эмодзи из текста.

    Args:
        text: Исходный текст.

    Returns:
        Список найденных эмодзи.
    """
    return [c for c in text if emoji.is_emoji(c)]
