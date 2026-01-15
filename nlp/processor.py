"""
Модуль обработки текста.
Извлечение и нормализация слов, эмодзи.
Использует natasha для NER (Named Entity Recognition).
"""
import re
import logging
from typing import Literal

import emoji

try:
    import pymorphy3 as pymorphy
except ImportError:
    import pymorphy2 as pymorphy

# Natasha для NER
from natasha import (
    Segmenter,
    MorphVocab,
    NewsEmbedding,
    NewsMorphTagger,
    NewsNERTagger,
    Doc,
)

from nltk.util import ngrams

from nlp.constants import (
    russian_stopwords,
    OBSCENE_ROOTS,
    PERSON_BLACKLIST,
    PHRASE_STOPWORDS,
)

logger = logging.getLogger(__name__)

# Инициализация морфологического анализатора pymorphy
morph = pymorphy.MorphAnalyzer()

# Инициализация компонентов natasha (один раз при загрузке модуля)
_segmenter = Segmenter()
_morph_vocab = MorphVocab()
_emb = NewsEmbedding()
_morph_tagger = NewsMorphTagger(_emb)
_ner_tagger = NewsNERTagger(_emb)

ProcessingMode = Literal['normal', 'mats', 'person']


def extract_person_names(text: str) -> list[str]:
    """
    Извлекает имена людей из текста с помощью NER (Named Entity Recognition).

    Использует natasha для точного распознавания именованных сущностей типа PER (Person).
    Нормализует имена к именительному падежу.

    Args:
        text: Исходный текст для обработки.

    Returns:
        Список нормализованных имён (в именительном падеже, с заглавной буквы).
    """
    if not text or not text.strip():
        return []

    # Удаляем URL перед обработкой
    text = re.sub(r'http\S+', '', text)

    names: list[str] = []

    try:
        # Создаём документ natasha
        doc = Doc(text)

        # Применяем сегментацию и морфологию
        doc.segment(_segmenter)
        doc.tag_morph(_morph_tagger)

        # Применяем NER
        doc.tag_ner(_ner_tagger)

        # Нормализуем найденные сущности
        for span in doc.spans:
            span.normalize(_morph_vocab)

        # Извлекаем только сущности типа PER (Person)
        for span in doc.spans:
            if span.type != 'PER':
                continue

            # Получаем нормализованное имя
            name = span.normal if span.normal else span.text

            # Очищаем от лишних пробелов
            name = ' '.join(name.split())

            # Пропускаем слишком короткие
            if len(name) < 2:
                continue

            # Проверяем чёрный список
            name_lower = name.lower()
            if name_lower in PERSON_BLACKLIST:
                continue

            # Дополнительная проверка через pymorphy для фильтрации ложных срабатываний
            first_word = name.split()[0].lower()
            parsed = morph.parse(first_word)[0]

            # Проверяем что это не служебное слово
            excluded_pos = {'PREP', 'CONJ', 'PRCL', 'ADVB', 'PRED', 'INTJ'}
            if parsed.tag.POS in excluded_pos:
                continue

            # Проверяем что первое слово не в чёрном списке
            if parsed.normal_form in PERSON_BLACKLIST:
                continue

            # Приводим к правильному регистру (каждое слово с заглавной)
            normalized_name = ' '.join(word.capitalize() for word in name.split())

            names.append(normalized_name)

    except Exception as e:
        logger.warning(f"Ошибка NER обработки: {e}")
        # Fallback на простую логику если NER не сработал
        return _extract_names_fallback(text)

    return names


def _extract_names_fallback(text: str) -> list[str]:
    """
    Запасной метод извлечения имён на основе pymorphy (без NER).
    Используется если natasha недоступна или произошла ошибка.
    """
    words = re.findall(r'[а-яА-ЯёЁ]+', text)
    names: list[str] = []

    for word in words:
        if not word[0].isupper() or len(word) < 3:
            continue

        low_word = word.lower()
        if low_word in PERSON_BLACKLIST:
            continue

        try:
            parsed = morph.parse(low_word)[0]
        except Exception:
            continue

        tags = parsed.tag

        # Только имена, фамилии и отчества по pymorphy
        if 'Name' in tags or 'Surn' in tags or 'Patr' in tags:
            normalized = parsed.normal_form.capitalize()
            names.append(normalized)

    return names


def get_clean_words(text: str, mode: ProcessingMode = 'normal') -> list[str]:
    """
    Извлекает и нормализует слова из текста.

    Args:
        text: Исходный текст для обработки.
        mode: Режим обработки:
            - 'normal': существительные и прилагательные без стоп-слов
            - 'mats': ненормативная лексика
            - 'person': имена людей (использует NER)

    Returns:
        Список обработанных слов.
    """
    # Для режима 'person' используем NER
    if mode == 'person':
        return extract_person_names(text)

    # Удаляем URL
    text = re.sub(r'http\S+', '', text)

    # Извлекаем кириллические слова
    words = re.findall(r'[а-яА-ЯёЁ]+', text)
    clean_words: list[str] = []

    for word in words:
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


def extract_phrases(texts: list[str], n: int = 3) -> list[tuple[tuple[str, ...], int]]:
    """
    Извлекает осмысленные фразы (n-граммы) из текстов.

    Фильтрация:
    - Фразы не начинаются и не заканчиваются стоп-словами
    - Содержат хотя бы одно существительное или глагол
    - Не состоят только из коротких слов (< 3 букв)
    - Очищены от спецсимволов

    Args:
        texts: Список текстов для обработки.
        n: Размер n-граммы (по умолчанию 3 - триграммы).

    Returns:
        Список кортежей (фраза, количество), отсортированный по убыванию.
    """
    from collections import Counter

    # Части речи, которые придают фразе смысл
    MEANINGFUL_POS = {'NOUN', 'VERB', 'INFN', 'ADJF', 'ADJS', 'PRTF', 'PRTS'}

    phrase_counter: Counter[tuple[str, ...]] = Counter()

    for text in texts:
        if not text or not text.strip():
            continue

        # Удаляем URL
        text = re.sub(r'http\S+', '', text)

        # Извлекаем только кириллические слова (без цифр и спецсимволов)
        words = re.findall(r'[а-яА-ЯёЁ]+', text.lower())

        if len(words) < n:
            continue

        # Создаём n-граммы
        for gram in ngrams(words, n):
            first_word = gram[0]
            last_word = gram[-1]

            # Фильтр 1: Не начинается/не заканчивается стоп-словом
            if first_word in PHRASE_STOPWORDS or last_word in PHRASE_STOPWORDS:
                continue

            # Фильтр 2: Не все слова короче 3 букв
            if all(len(w) < 3 for w in gram):
                continue

            # Фильтр 3: Содержит хотя бы одно значимое слово (NOUN/VERB/ADJ)
            has_meaningful = False
            for word in gram:
                try:
                    parsed = morph.parse(word)[0]
                    if parsed.tag.POS in MEANINGFUL_POS:
                        has_meaningful = True
                        break
                except Exception:
                    continue

            if not has_meaningful:
                continue

            # Фильтр 4: Пропускаем фразы где все слова - стоп-слова
            if all(w in PHRASE_STOPWORDS for w in gram):
                continue

            phrase_counter[gram] += 1

    # Возвращаем отсортированный список
    return phrase_counter.most_common()
