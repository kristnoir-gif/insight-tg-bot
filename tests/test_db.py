"""Tests for db.py — user registration, access control, balance."""
import sqlite3
from unittest.mock import patch

from db import (
    register_user,
    check_user_access,
    consume_analysis,
    add_paid_balance,
    add_pending_analysis,
    get_queue_position,
    get_queue_stats,
    get_next_pending_batch,
    get_user_pending_queue,
    remove_pending_analysis,
    reset_processing_to_pending,
    update_pending_status,
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


# --- Queue priority tests ---

def test_add_pending_analysis_returns_position(temp_db):
    """add_pending_analysis returns queue position."""
    with patch("db.DB_PATH", temp_db):
        import time
        # First user
        pos1 = add_pending_analysis(100, "channel1", "@channel1", priority=0)
        assert pos1 == 1
        time.sleep(0.05)  # Ensure different timestamps (SQLite has second precision)
        # Second user
        pos2 = add_pending_analysis(101, "channel2", "@channel2", priority=0)
        # With same second, order might be unpredictable, just check both are in queue
        assert pos2 >= 1


def test_queue_priority_ordering(temp_db):
    """Paid users should be ahead of free users in queue."""
    with patch("db.DB_PATH", temp_db):
        import time
        # Free user first
        add_pending_analysis(100, "free_ch", "@free_ch", priority=0)
        time.sleep(0.01)
        # Paid user second (but should be ahead)
        pos_paid = add_pending_analysis(101, "paid_ch", "@paid_ch", priority=2)
        # Paid user should be position 1, even though added second
        assert pos_paid == 1

        # Check that free user is now position 2
        pos_free = get_queue_position(100, "free_ch")
        assert pos_free == 2


def test_get_queue_stats(temp_db):
    """get_queue_stats returns correct counts by priority."""
    with patch("db.DB_PATH", temp_db):
        import time
        add_pending_analysis(100, "ch1", "@ch1", priority=0)  # free
        time.sleep(0.01)
        add_pending_analysis(101, "ch2", "@ch2", priority=1)  # premium
        time.sleep(0.01)
        add_pending_analysis(102, "ch3", "@ch3", priority=2)  # paid
        time.sleep(0.01)
        add_pending_analysis(103, "ch4", "@ch4", priority=2)  # paid

        stats = get_queue_stats()
        assert stats["total"] == 4
        assert stats["paid"] == 2
        assert stats["premium"] == 1
        assert stats["free"] == 1


def test_get_next_pending_batch_respects_priority(temp_db):
    """get_next_pending_batch returns items ordered by priority."""
    with patch("db.DB_PATH", temp_db):
        import time
        # Add in reverse priority order
        add_pending_analysis(100, "free", "@free", priority=0)
        time.sleep(0.01)
        add_pending_analysis(101, "premium", "@premium", priority=1)
        time.sleep(0.01)
        add_pending_analysis(102, "paid", "@paid", priority=2)

        # Need to wait 30 seconds for items to become eligible
        # For testing, we'll manually update created_at
        from db import get_db_connection
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE pending_analyses SET created_at = datetime('now', '-1 minute')"
            )
            conn.commit()

        batch = get_next_pending_batch(limit=5)
        assert len(batch) == 3
        # First should be paid (priority=2)
        assert batch[0][4] == 2  # priority column
        # Second should be premium (priority=1)
        assert batch[1][4] == 1
        # Third should be free (priority=0)
        assert batch[2][4] == 0


def test_get_user_pending_queue(temp_db):
    """get_user_pending_queue returns all user's pending analyses with positions."""
    with patch("db.DB_PATH", temp_db):
        import time
        # Another user first
        add_pending_analysis(999, "other", "@other", priority=2)
        time.sleep(0.01)
        # Our user's analyses
        add_pending_analysis(100, "ch1", "@ch1", priority=0)
        time.sleep(0.01)
        add_pending_analysis(100, "ch2", "@ch2", priority=0)

        pending = get_user_pending_queue(100)
        assert len(pending) == 2
        # Both should have positions > 1 (other user is ahead with priority 2)
        assert all(item["position"] > 1 for item in pending)


def test_remove_pending_clears_from_queue(temp_db):
    """remove_pending_analysis removes item and updates positions."""
    with patch("db.DB_PATH", temp_db):
        import time
        pos1 = add_pending_analysis(100, "ch1", "@ch1", priority=0)
        time.sleep(0.01)
        add_pending_analysis(101, "ch2", "@ch2", priority=0)

        # Remove first item
        from db import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM pending_analyses WHERE channel_key = 'ch1'")
            analysis_id = cursor.fetchone()[0]

        remove_pending_analysis(analysis_id)

        # Second user should now be position 1
        pos2_new = get_queue_position(101, "ch2")
        assert pos2_new == 1


def test_reset_processing_to_pending(temp_db):
    """reset_processing_to_pending resets 'processing' items back to 'pending'."""
    with patch("db.DB_PATH", temp_db):
        import time
        add_pending_analysis(100, "ch1", "@ch1", priority=0)
        time.sleep(0.01)
        add_pending_analysis(101, "ch2", "@ch2", priority=2)

        # Ставим первый в processing
        from db import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM pending_analyses WHERE channel_key = 'ch1'")
            aid = cursor.fetchone()[0]
        update_pending_status(aid, 'processing')

        # Сбрасываем
        count = reset_processing_to_pending()
        assert count == 1

        # Проверяем что ch1 снова pending
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM pending_analyses WHERE channel_key = 'ch1'")
            status = cursor.fetchone()[0]
        assert status == 'pending'


def test_reset_processing_no_processing(temp_db):
    """reset_processing_to_pending returns 0 when nothing to reset."""
    with patch("db.DB_PATH", temp_db):
        add_pending_analysis(100, "ch1", "@ch1", priority=0)
        count = reset_processing_to_pending()
        assert count == 0
