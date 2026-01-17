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
    NamesExtractor,
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
_names_extractor = NamesExtractor(_morph_vocab)

ProcessingMode = Literal['normal', 'mats', 'person']


def extract_person_names(text: str) -> list[str]:
    """
    Извлекает имена людей из текста с помощью NamesExtractor из natasha.

    Использует строгую проверку: только сущности, которые natasha
    распознала как имя (first), фамилию (last) или отчество (middle).
    Игнорирует прилагательные и существительные в начале предложений.

    Args:
        text: Исходный текст для обработки.

    Returns:
        Список нормализованных имён (в именительном падеже).
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

        # Обрабатываем только сущности типа PER (Person)
        for span in doc.spans:
            if span.type != 'PER':
                continue

            # Нормализуем span
            span.normalize(_morph_vocab)

            # КЛЮЧЕВОЙ ШАГ: используем NamesExtractor для разбора имени
            span.extract_fact(_names_extractor)

            # СТРОГАЯ ПРОВЕРКА: должно быть распознано как реальное имя
            if not span.fact or not span.fact.slots:
                # NamesExtractor не смог разобрать — это не настоящее имя
                continue

            # Извлекаем компоненты имени из slots
            first_name = None
            last_name = None
            for slot in span.fact.slots:
                if slot.key == 'first':
                    first_name = slot.value
                elif slot.key == 'last':
                    last_name = slot.value

            # Должен быть хотя бы first (имя) или last (фамилия)
            if not first_name and not last_name:
                continue

            # Собираем нормализованное имя в именительном падеже
            name_parts = []
            if first_name:
                name_parts.append(first_name.capitalize())
            if last_name:
                name_parts.append(last_name.capitalize())

            name = ' '.join(name_parts)

            # Пропускаем слишком короткие
            if len(name) < 2:
                continue

            # Проверяем чёрный список
            if name.lower() in PERSON_BLACKLIST:
                continue

            # Проверяем каждое слово отдельно в чёрном списке
            skip = False
            for word in name.lower().split():
                if word in PERSON_BLACKLIST:
                    skip = True
                    break
            if skip:
                continue

            names.append(name)

    except Exception as e:
        logger.warning(f"Ошибка NER обработки: {e}")
        # НЕ используем fallback — лучше пустой список чем мусорные данные
        return []

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
