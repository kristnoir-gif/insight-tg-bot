"""Тесты модуля llm.py — AI-анализ контента канала."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import aiohttp


@pytest.fixture
def sample_posts():
    """Минимальный набор постов для тестирования."""
    return [f"Пост номер {i} с каким-то текстом для анализа" for i in range(20)]


@pytest.fixture
def sample_stats():
    """Текстовая сводка метрик."""
    return (
        "Постов: 100\n"
        "Период: 01.01.2023 — 01.01.2024\n"
        "Пиковый час: 23:00\n"
        "ТОП-10 слов: жизнь, хочу, день, думаю, делать\n"
        "Позитивных слов: 60% | Агрессивных: 40%"
    )


@pytest.fixture
def mock_api_response():
    """Ответ API в формате OpenAI."""
    return {
        "choices": [{
            "message": {
                "content": (
                    "<b>📊 Портрет канала</b>\n"
                    "Личный дневник с фокусом на рефлексию.\n\n"
                    "<b>📈 Что говорят цифры</b>\n"
                    "Ночной паттерн активности."
                )
            }
        }]
    }


@pytest.mark.asyncio
async def test_generate_content_analysis_success(sample_posts, sample_stats, mock_api_response):
    """Успешный вызов LLM возвращает текст."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_api_response)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))
    mock_session_ctx = AsyncMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=False),
    )

    with patch("llm.LLM_API_KEY", "sk-test"), \
         patch("llm.aiohttp.ClientSession", return_value=mock_session_ctx):
        from llm import generate_content_analysis
        result = await generate_content_analysis("Test Channel", 1000, sample_stats, sample_posts)

    assert result is not None
    assert "Портрет канала" in result


@pytest.mark.asyncio
async def test_generate_content_analysis_timeout(sample_posts, sample_stats):
    """Таймаут LLM → None."""
    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=TimeoutError("timeout"))
    mock_session_ctx = AsyncMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=False),
    )

    with patch("llm.LLM_API_KEY", "sk-test"), \
         patch("llm.aiohttp.ClientSession", return_value=mock_session_ctx):
        from llm import generate_content_analysis
        result = await generate_content_analysis("Test Channel", 1000, sample_stats, sample_posts)

    assert result is None


@pytest.mark.asyncio
async def test_generate_content_analysis_api_error(sample_posts, sample_stats):
    """HTTP 500 → None."""
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="Internal Server Error")

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))
    mock_session_ctx = AsyncMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=False),
    )

    with patch("llm.LLM_API_KEY", "sk-test"), \
         patch("llm.aiohttp.ClientSession", return_value=mock_session_ctx):
        from llm import generate_content_analysis
        result = await generate_content_analysis("Test Channel", 1000, sample_stats, sample_posts)

    assert result is None


@pytest.mark.asyncio
async def test_generate_content_analysis_no_api_key(sample_posts, sample_stats):
    """Пустой API ключ → None."""
    with patch("llm.LLM_API_KEY", ""):
        from llm import generate_content_analysis
        result = await generate_content_analysis("Test Channel", 1000, sample_stats, sample_posts)

    assert result is None


@pytest.mark.asyncio
async def test_generate_content_analysis_empty_posts(sample_stats):
    """Менее 10 постов → None."""
    with patch("llm.LLM_API_KEY", "sk-test"):
        from llm import generate_content_analysis

        # Пустой список
        result = await generate_content_analysis("Test Channel", 1000, sample_stats, [])
        assert result is None

        # 5 постов (< 10)
        result = await generate_content_analysis("Test Channel", 1000, sample_stats, ["пост"] * 5)
        assert result is None


@pytest.mark.asyncio
async def test_generate_personality_analysis_returns_none(sample_posts):
    """generate_personality_analysis теперь всегда возвращает None (deprecated)."""
    with patch("llm.LLM_API_KEY", "sk-test"):
        from llm import generate_personality_analysis
        result = await generate_personality_analysis("Test Channel", 1000, sample_posts)

    assert result is None


def test_sanitize_html():
    """Проверка очистки HTML-тегов."""
    from llm import _sanitize_html

    # Допустимые теги остаются
    assert _sanitize_html("<b>жирный</b>") == "<b>жирный</b>"
    assert _sanitize_html("<i>курсив</i>") == "<i>курсив</i>"

    # Недопустимые теги удаляются
    assert _sanitize_html("<div>текст</div>") == "текст"
    assert _sanitize_html('<a href="x">ссылка</a>') == "ссылка"
    assert _sanitize_html("<p>параграф</p>") == "параграф"

    # Смешанный контент
    assert _sanitize_html("<b>жирный</b> и <div>блок</div>") == "<b>жирный</b> и блок"
