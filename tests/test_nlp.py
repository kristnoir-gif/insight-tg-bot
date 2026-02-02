"""Tests for NLP processing — lemmatisation, NER, stopwords, emoji, obscene."""
from nlp.processor import get_clean_words, extract_emojis, extract_person_names
from nlp.constants import russian_stopwords, OBSCENE_ROOTS


def test_lemmatization():
    """pymorphy normalises inflected words to their base form."""
    try:
        import pymorphy3 as pymorphy
    except ImportError:
        import pymorphy2 as pymorphy
    morph = pymorphy.MorphAnalyzer()
    parsed = morph.parse("бежали")[0]
    assert parsed.normal_form == "бежать"


def test_extract_person_names():
    """NER extracts person names from text."""
    names = extract_person_names("Путин сказал, что Медведев согласился")
    # At least one of the names should be extracted
    name_str = " ".join(names).lower()
    assert "путин" in name_str or "медведев" in name_str


def test_stopwords_filtered():
    """Stopwords are absent from get_clean_words result."""
    words = get_clean_words("Это очень просто хороший большой красивый город", "normal")
    for w in words:
        assert w not in russian_stopwords, f"Stopword '{w}' found in clean words"


def test_extract_emojis():
    """Emojis are correctly extracted from text."""
    emojis = extract_emojis("Hello \U0001f525 world \U0001f60a!")
    assert "\U0001f525" in emojis
    assert "\U0001f60a" in emojis
    assert len(emojis) == 2


def test_obscene_detection():
    """Obscene words are detected through OBSCENE_ROOTS."""
    words = get_clean_words("Какой блядский день", "mats")
    # Should detect at least one mat word via root matching
    assert len(words) > 0
    # Verify the root matching mechanism works
    assert any(root in w for w in words for root in OBSCENE_ROOTS)
