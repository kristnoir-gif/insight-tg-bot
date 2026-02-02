"""Tests for payment-related db functions."""
from unittest.mock import patch

from db import (
    register_user,
    add_paid_balance,
    consume_analysis,
    check_user_access,
    log_payment,
    get_payment_stats,
)


def test_log_payment(temp_db):
    """log_payment writes a record to the payments table."""
    import sqlite3

    with patch("db.DB_PATH", temp_db):
        register_user(100, "payuser")
        log_payment(100, stars=50, payment_method="telegram_stars", notes="pack_3_a")

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, stars, notes FROM payments")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 100
        assert row[1] == 50
        assert row[2] == "pack_3_a"


def test_record_payment(temp_db):
    """log_payment + add_paid_balance combo works correctly."""
    with patch("db.DB_PATH", temp_db):
        register_user(101, "combo")
        log_payment(101, stars=20, payment_method="telegram_stars", notes="pack_1_a")
        add_paid_balance(101, 1)

        status = check_user_access(101)
        assert status.paid_balance == 1


def test_balance_after_purchase(temp_db):
    """register -> add_paid -> consume -> check balance."""
    with patch("db.DB_PATH", temp_db):
        register_user(102, "flowuser")
        add_paid_balance(102, 3)
        consume_analysis(102, "paid")
        status = check_user_access(102)
        assert status.paid_balance == 2


def test_get_payment_stats(temp_db):
    """get_payment_stats doesn't crash on empty or populated DB."""
    with patch("db.DB_PATH", temp_db):
        # Empty DB
        stats = get_payment_stats()
        assert isinstance(stats, dict)
        assert stats.get("total_payments", 0) == 0

        # After a payment
        register_user(103, "statsuser")
        log_payment(103, stars=10, payment_method="telegram_stars")
        stats = get_payment_stats()
        assert stats["total_payments"] == 1
        assert stats["total_stars"] == 10


def test_double_consume_no_negative(temp_db):
    """paid_balance never goes below 0."""
    with patch("db.DB_PATH", temp_db):
        register_user(104, "neguser")
        add_paid_balance(104, 1)
        consume_analysis(104, "paid")
        consume_analysis(104, "paid")  # Should not go below 0
        status = check_user_access(104)
        assert status.paid_balance >= 0
