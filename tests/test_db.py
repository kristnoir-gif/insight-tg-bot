"""Tests for db.py — user registration, access control, balance."""
import sqlite3
from unittest.mock import patch

from db import (
    register_user,
    check_user_access,
    consume_analysis,
    add_paid_balance,
)
from config import ADMIN_IDS


def test_register_new_user(temp_db):
    """register_user returns True for a new user."""
    with patch("db.DB_PATH", temp_db):
        result = register_user(111, "testuser")
        assert result is True


def test_register_existing_user(temp_db):
    """register_user returns False for an already-registered user."""
    with patch("db.DB_PATH", temp_db):
        register_user(111, "testuser")
        result = register_user(111, "testuser")
        assert result is False


def test_check_access_admin(temp_db):
    """Admin user always has access."""
    admin_id = next(iter(ADMIN_IDS))
    with patch("db.DB_PATH", temp_db):
        status = check_user_access(admin_id)
        assert status.can_analyze is True
        assert status.reason == "admin"


def test_check_access_new_user(temp_db):
    """New (unregistered) user gets free daily access."""
    with patch("db.DB_PATH", temp_db):
        status = check_user_access(999999)
        assert status.can_analyze is True
        assert status.reason == "free_daily"


def test_check_access_limit_reached(temp_db):
    """After consuming the free daily analysis, access is denied."""
    with patch("db.DB_PATH", temp_db):
        register_user(222, "limituser")
        consume_analysis(222, "free_daily")
        status = check_user_access(222)
        assert status.can_analyze is False
        assert status.reason == "limit_reached"


def test_check_access_paid_balance(temp_db):
    """User with paid balance can analyze."""
    with patch("db.DB_PATH", temp_db):
        register_user(333, "paiduser")
        add_paid_balance(333, 5)
        status = check_user_access(333)
        assert status.can_analyze is True
        assert status.reason == "paid"


def test_add_paid_balance(temp_db):
    """add_paid_balance increases the user's balance."""
    with patch("db.DB_PATH", temp_db):
        register_user(444, "balanceuser")
        add_paid_balance(444, 3)
        status = check_user_access(444)
        assert status.paid_balance == 3


def test_consume_analysis_paid(temp_db):
    """consume_analysis decreases paid_balance by 1."""
    with patch("db.DB_PATH", temp_db):
        register_user(555, "consumeuser")
        add_paid_balance(555, 2)
        consume_analysis(555, "paid")
        status = check_user_access(555)
        assert status.paid_balance == 1
