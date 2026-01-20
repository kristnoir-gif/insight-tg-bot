"""
Модуль обработки текста.
Извлечение и нормализация слов, эмодзи.
Использует natasha для NER (Named Entity Recognition).
"""
import re
import logging
from typing import Literal
from collections import Counter

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


def _is_valid_phrase(gram: tuple[str, ...], meaningful_pos: set[str]) -> bool:
    """
    Проверяет качество фразы.

    Args:
        gram: Кортеж слов (n-грамма).
        meaningful_pos: Набор значимых частей речи.

    Returns:
        True если фраза качественная.
    """
    # Не начинается/не заканчивается стоп-словом
    if gram[0] in PHRASE_STOPWORDS or gram[-1] in PHRASE_STOPWORDS:
        return False

    # Не все слова короткие
    if all(len(w) < 3 for w in gram):
        return False

    # Должен быть хотя бы 1 NOUN или VERB
    has_noun_or_verb = False
    for word in gram:
        try:
            parsed = morph.parse(word)[0]
            if parsed.tag.POS in {'NOUN', 'VERB', 'INFN'}:
                has_noun_or_verb = True
                break
        except Exception:
            pass

    return has_noun_or_verb


def _merge_and_deduplicate(
    bigrams: Counter[tuple[str, ...]],
    trigrams: Counter[tuple[str, ...]]
) -> Counter[tuple[str, ...]]:
    """
    Объединяет биграммы и триграммы, убирая дубликаты.

    Если биграмма входит в частую триграмму, оставляем только триграмму.
    """
    result: Counter[tuple[str, ...]] = Counter()

    # Добавляем триграммы с минимум 2 вхождениями
    for gram, count in trigrams.items():
        if count >= 2:
            result[gram] = count

    # Создаём набор текстов триграмм для проверки
    trigram_texts = {' '.join(g) for g in trigrams.keys() if trigrams[g] >= 2}

    # Добавляем биграммы, которые не являются частью частых триграмм
    for gram, count in bigrams.items():
        if count >= 2:
            gram_text = ' '.join(gram)
            # Проверяем, не входит ли биграмма в популярную триграмму
            is_part_of_trigram = any(gram_text in t for t in trigram_texts)
            if not is_part_of_trigram:
                result[gram] = count

    return result


def extract_phrases(texts: list[str], n: int = 3) -> list[tuple[tuple[str, ...], int]]:
    """
    Извлекает осмысленные фразы (биграммы и триграммы) из текстов.

    Фильтрация:
    - Фразы не начинаются и не заканчиваются стоп-словами
    - Должен быть хотя бы один NOUN или VERB
    - Биграммы, входящие в частые триграммы, исключаются

    Args:
        texts: Список текстов для обработки.
        n: Игнорируется (для совместимости). Извлекаются и 2- и 3-граммы.

    Returns:
        Список кортежей (фраза, количество), отсортированный по убыванию.
    """
    # Части речи, которые придают фразе смысл
    MEANINGFUL_POS = {'NOUN', 'VERB', 'INFN', 'ADJF', 'ADJS', 'PRTF', 'PRTS'}

    bigram_counter: Counter[tuple[str, ...]] = Counter()
    trigram_counter: Counter[tuple[str, ...]] = Counter()

    for text in texts:
        if not text or not text.strip():
            continue

        # Удаляем URL
        text = re.sub(r'http\S+', '', text)

        # Извлекаем только кириллические слова (без цифр и спецсимволов)
        words = re.findall(r'[а-яА-ЯёЁ]+', text.lower())

        # Собираем биграммы
        if len(words) >= 2:
            for gram in ngrams(words, 2):
                if _is_valid_phrase(gram, MEANINGFUL_POS):
                    bigram_counter[gram] += 1

        # Собираем триграммы
        if len(words) >= 3:
            for gram in ngrams(words, 3):
                if _is_valid_phrase(gram, MEANINGFUL_POS):
                    trigram_counter[gram] += 1

    # Объединяем и фильтруем дубликаты
    combined = _merge_and_deduplicate(bigram_counter, trigram_counter)

    # Возвращаем отсортированный список
    return combined.most_common()
