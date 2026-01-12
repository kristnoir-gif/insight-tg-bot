"""NLP модуль для обработки текста."""
from nlp.processor import get_clean_words, extract_emojis
from nlp.constants import (
    russian_stopwords,
    positive_words,
    aggressive_words,
    OBSCENE_ROOTS,
    PERSON_BLACKLIST,
)

__all__ = [
    "get_clean_words",
    "extract_emojis",
    "russian_stopwords",
    "positive_words",
    "aggressive_words",
    "OBSCENE_ROOTS",
    "PERSON_BLACKLIST",
]
