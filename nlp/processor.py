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
            # Проверяем что слово начинается с заглавной и достаточно длинное
            if original_word[0].isupper() and len(original_word) > 2:
                # Пропускаем слова из чёрного списка
                if normal in PERSON_BLACKLIST or low_word in PERSON_BLACKLIST:
                    continue

                # 1. Проверяем теги pymorphy: имена (Name), фамилии (Surn), отчества (Patr)
                is_person_tag = 'Name' in tags or 'Surn' in tags or 'Patr' in tags

                # 2. Эвристика для фамилий на -ский/-цкий/-ный/-ов/-ев/-ин/-ых
                #    (Навальный, Зеленский, Шуфутинский, Иванов и т.д.)
                #    Включая падежные формы (-а, -у, -ом, -е, -ого, -ому и т.д.)
                surname_endings = (
                    # Именительный падеж
                    'ский', 'цкий', 'ный', 'ной',  # прилагательные-фамилии
                    'ов', 'ев', 'ёв', 'ин', 'ын',  # классические фамилии
                    'ко', 'ук', 'юк', 'як', 'ак',  # украинские
                    'ич', 'вич', 'ых', 'их',       # другие
                    # Падежные формы (родительный, дательный, винительный, творительный)
                    'ова', 'ева', 'ёва', 'ина', 'ына',  # родительный -ов/-ев/-ин
                    'ову', 'еву', 'ёву', 'ину', 'ыну',  # дательный
                    'овым', 'евым', 'иным', 'ыным',     # творительный
                    'ском', 'цком', 'ного', 'ному',     # падежи -ский
                    'ским', 'цким',                      # творительный -ский
                    'ерна', 'ерну', 'ерном', 'ерне',    # иностранные (Моргенштерн)
                    'анна', 'анну', 'анном', 'анне',    # иностранные (Бекхэм -> Бекхэма)
                )
                looks_like_surname = low_word.endswith(surname_endings)

                # 3. Эвристика для иностранных имён и неизвестных слов:
                #    - Слово не распознано (UNKN) или имеет низкую вероятность
                #    - Слово одушевлённое (anim)
                is_unknown = 'UNKN' in tags or parsed.score < 0.15
                is_animated = 'anim' in tags

                # 4. Короткие слова с заглавной (Маск, Дудь и т.д.) - потенциальные имена
                #    если не распознаны как что-то конкретное
                is_short_capitalized = (
                    len(original_word) <= 6
                    and original_word[0].isupper()
                    and parsed.score < 0.5
                )

                # Собираем если подходит под один из критериев
                if is_person_tag or looks_like_surname or is_unknown or is_animated or is_short_capitalized:
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
