"""
Модуль обработки текста.
Извлечение и нормализация слов, эмодзи.
"""
import re
import logging
from typing import Literal
from enum import Enum

import emoji

try:
    import pymorphy3 as pymorphy
except ImportError:
    import pymorphy2 as pymorphy

from nlp.constants import (
    russian_stopwords,
    OBSCENE_ROOTS,
    PERSON_BLACKLIST,
)

logger = logging.getLogger(__name__)

# Инициализация морфологического анализатора
morph = pymorphy.MorphAnalyzer()

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
            pos = tags.POS

            # Фильтруем по части речи: только существительные могут быть именами
            # Исключаем предлоги, союзы, частицы, наречия, глаголы и т.д.
            excluded_pos = {'PREP', 'CONJ', 'PRCL', 'ADVB', 'VERB', 'INFN', 'PRED', 'INTJ'}
            if pos in excluded_pos:
                continue

            # Проверяем что слово начинается с заглавной буквы
            if not original_word[0].isupper():
                continue

            # Минимальная длина
            if len(original_word) < 3:
                continue

            # Пропускаем слова из чёрного списка (проверяем и нормальную форму, и исходное слово)
            if normal in PERSON_BLACKLIST or low_word in PERSON_BLACKLIST:
                continue

            # СТРОГАЯ ЛОГИКА: только морфологические теги pymorphy
            # Name = имя (Анна, Михаил)
            # Surn = фамилия (Иванов, Путин)
            # Patr = отчество (Иванович)
            is_name = 'Name' in tags
            is_surname = 'Surn' in tags
            is_patronymic = 'Patr' in tags

            if is_name or is_surname or is_patronymic:
                # Нормализуем имя (приводим к именительному падежу)
                # но сохраняем заглавную букву
                normalized_name = normal.capitalize()
                clean_words.append(normalized_name)

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
