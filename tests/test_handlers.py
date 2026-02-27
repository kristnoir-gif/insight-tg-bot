"""Smoke tests for handlers: /start, /help, /balance, /buy, /queue, /admin."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_message(user_id: int = 100, username: str = "testuser", text: str = "/start"):
    """Создаёт мок aiogram Message."""
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.first_name = "Test"

    message = AsyncMock()
    message.from_user = user
    message.text = text
    message.answer = AsyncMock()
    message.answer_photo = AsyncMock()
    message.answer_media_group = AsyncMock()
    message.reply = AsyncMock()
    return message


def _make_callback(user_id: int = 100, data: str = "buy_pack_1"):
    """Создаёт мок aiogram CallbackQuery."""
    user = MagicMock()
    user.id = user_id
    user.username = "testuser"

    callback = AsyncMock()
    callback.from_user = user
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = _make_message(user_id)
    return callback


# --- /start ---

@pytest.mark.asyncio
async def test_cmd_start(temp_db):
    """cmd_start должен отвечать приветственным сообщением."""
    with patch("db.DB_PATH", temp_db), \
         patch("utils.DB_PATH", temp_db), \
         patch("handlers.common.is_admin", return_value=False), \
         patch("handlers.common.check_user_access") as mock_access:
        mock_access.return_value = MagicMock(paid_balance=0, is_premium=False)

        from handlers.user import cmd_start
        message = _make_message()
        await cmd_start(message)

        message.answer.assert_called_once()
        call_text = message.answer.call_args[0][0]
        assert "Добро пожаловать" in call_text


# --- /help ---

@pytest.mark.asyncio
async def test_cmd_help(temp_db):
    """cmd_help должен отвечать инструкциями."""
    with patch("db.DB_PATH", temp_db), \
         patch("utils.DB_PATH", temp_db), \
         patch("handlers.common.is_admin", return_value=False), \
         patch("handlers.common.check_user_access") as mock_access:
        mock_access.return_value = MagicMock(paid_balance=0, is_premium=False)

        from handlers.user import cmd_help
        message = _make_message(text="/help")
        await cmd_help(message)

        message.answer.assert_called_once()
        call_text = message.answer.call_args[0][0]
        assert "Как пользоваться" in call_text


# --- /balance ---

@pytest.mark.asyncio
async def test_cmd_balance(temp_db):
    """cmd_balance должен показывать статус пользователя."""
    with patch("db.DB_PATH", temp_db), \
         patch("utils.DB_PATH", temp_db):
        from db import register_user, add_paid_balance
        register_user(200, "baluser")
        add_paid_balance(200, 5)

        from handlers.user import cmd_balance
        message = _make_message(user_id=200, username="baluser")
        await cmd_balance(message)

        message.answer.assert_called_once()
        call_text = message.answer.call_args[0][0]
        assert "5" in call_text
        assert "Статус" in call_text


# --- /queue (empty) ---

@pytest.mark.asyncio
async def test_cmd_queue_empty(temp_db):
    """cmd_queue при пустой очереди должен говорить об этом."""
    with patch("db.DB_PATH", temp_db), \
         patch("utils.DB_PATH", temp_db), \
         patch("handlers.common.is_admin", return_value=False), \
         patch("handlers.common.check_user_access") as mock_access:
        mock_access.return_value = MagicMock(paid_balance=0, is_premium=False)

        from handlers.user import cmd_queue
        message = _make_message(user_id=300)
        await cmd_queue(message)

        message.answer.assert_called_once()
        call_text = message.answer.call_args[0][0]
        assert "пуста" in call_text.lower() or "Очередь пуста" in call_text


# --- /queue (with pending) ---

@pytest.mark.asyncio
async def test_cmd_queue_with_pending(temp_db):
    """cmd_queue с pending анализами должен показывать их."""
    with patch("db.DB_PATH", temp_db), \
         patch("utils.DB_PATH", temp_db), \
         patch("handlers.common.is_admin", return_value=False), \
         patch("handlers.common.check_user_access") as mock_access:
        mock_access.return_value = MagicMock(paid_balance=0, is_premium=False)

        from db import register_user, add_pending_analysis
        register_user(301, "queueuser")
        add_pending_analysis(301, "testchannel", "testchannel", priority=1)

        from handlers.user import cmd_queue
        message = _make_message(user_id=301)
        await cmd_queue(message)

        message.answer.assert_called_once()
        call_text = message.answer.call_args[0][0]
        assert "testchannel" in call_text


# --- /buy ---

@pytest.mark.asyncio
async def test_cmd_buy(temp_db):
    """cmd_buy должен показывать меню покупок."""
    with patch("db.DB_PATH", temp_db), \
         patch("utils.DB_PATH", temp_db):
        from db import register_user
        register_user(400, "buyuser")

        from handlers.payments import cmd_buy
        # Мокаем _send_example чтобы не искать файлы
        with patch("handlers.payments._send_example", new_callable=AsyncMock):
            message = _make_message(user_id=400, username="buyuser")
            await cmd_buy(message)

            # Должен ответить хотя бы один раз
            assert message.answer.call_count >= 1


# --- common: get_ab_group ---

def test_ab_group_consistency():
    """A/B группа должна быть детерминистической."""
    from handlers.common import get_ab_group
    assert get_ab_group(100) == "a"  # чётный
    assert get_ab_group(101) == "b"  # нечётный
    assert get_ab_group(100) == get_ab_group(100)  # идемпотентно


# --- common: get_prices ---

def test_prices_differ_by_group():
    """Цены должны различаться по A/B группам."""
    from handlers.common import get_prices
    prices_a = get_prices(100)
    prices_b = get_prices(101)
    assert prices_a != prices_b
    assert "pack_1" in prices_a
    assert "pack_1" in prices_b


# --- common: format_wait_time ---

def test_format_wait_time():
    """format_wait_time должен форматировать секунды."""
    from handlers.common import format_wait_time
    assert "мин" in format_wait_time(120)
    assert "сек" in format_wait_time(30)


# --- common: _get_emotional_tone ---

def test_emotional_tone_ranges():
    """_get_emotional_tone должен возвращать правильный тон."""
    from handlers.common import _get_emotional_tone
    assert _get_emotional_tone(0.5) == "Спокойный"
    assert _get_emotional_tone(3.0) == "Умеренный"
    assert _get_emotional_tone(5.0) == "Экспрессивный"
    assert _get_emotional_tone(10.0) == "Взрывной"


# --- pending queue: priority preservation ---

def test_pending_priority_preserved(temp_db):
    """INSERT ON CONFLICT должен сохранять максимальный приоритет."""
    with patch("db.DB_PATH", temp_db):
        from db import register_user, add_pending_analysis
        import sqlite3

        register_user(500, "priouser")

        # Сначала платный запрос (приоритет 2)
        add_pending_analysis(500, "chan1", "chan1", priority=2)

        # Повторный бесплатный запрос (приоритет 0) — не должен затирать
        add_pending_analysis(500, "chan1", "chan1", priority=0)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT priority FROM pending_analyses WHERE user_id = 500 AND channel_key = 'chan1'")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # Приоритет сохранён


# --- payments: successful_payment с проверкой process_pack_payment ---

@pytest.mark.asyncio
async def test_payment_failed_notifies_admin(temp_db):
    """Если process_pack_payment вернул False — админ должен быть уведомлён."""
    with patch("db.DB_PATH", temp_db), \
         patch("utils.DB_PATH", temp_db), \
         patch("handlers.payments.process_pack_payment", return_value=False), \
         patch("handlers.payments.notify_admin_error", new_callable=AsyncMock) as mock_notify, \
         patch("handlers.payments.record_payment"), \
         patch("handlers.payments.log_buy_click"):
        from db import register_user
        register_user(600, "failpay")

        from handlers.payments import handle_successful_payment

        # Мокаем Message с successful_payment
        payment = MagicMock()
        payment.invoice_payload = "pack_1"
        payment.total_amount = 20

        message = _make_message(user_id=600, username="failpay")
        message.successful_payment = payment

        await handle_successful_payment(message)

        # Админ должен быть уведомлён об ошибке
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args[0]
        assert "FAILED" in call_args[0]
        assert "600" in call_args[1]


@pytest.mark.asyncio
async def test_payment_success_flow(temp_db):
    """Успешная оплата должна начислить баланс."""
    with patch("db.DB_PATH", temp_db), \
         patch("utils.DB_PATH", temp_db), \
         patch("handlers.payments.notify_admin_payment", new_callable=AsyncMock), \
         patch("handlers.payments.record_payment"):
        from db import register_user, check_user_access
        register_user(601, "successpay")

        from handlers.payments import handle_successful_payment

        payment = MagicMock()
        payment.invoice_payload = "pack_3"
        payment.total_amount = 40

        message = _make_message(user_id=601, username="successpay")
        message.successful_payment = payment

        await handle_successful_payment(message)

        status = check_user_access(601)
        assert status.paid_balance == 3
