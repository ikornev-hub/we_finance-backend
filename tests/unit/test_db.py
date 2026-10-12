import pytest

from we_finance.db import check_db
from we_finance.settings import ConfigError


def test_check_db_failure(monkeypatch):
    # Assuming the database is running and accessible
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")
    assert check_db() is False


def test_check_db_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError):
        check_db()
