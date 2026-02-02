import pytest
from unittest.mock import patch
from pathlib import Path


@pytest.fixture
def temp_db(tmp_path):
    """Creates a temporary DB with full schema."""
    db_path = tmp_path / "test_users.db"
    with patch("db.DB_PATH", db_path):
        from db import init_db
        init_db()
        yield db_path
