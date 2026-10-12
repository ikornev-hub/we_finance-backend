import pytest

from we_finance.settings import ConfigError, get_app_env, get_database_url


@pytest.mark.parametrize("env_value", ["dev", "test", "stage", "prod"])
def test_get_app_env(monkeypatch, env_value):
    monkeypatch.setenv("APP_ENV", env_value)
    assert get_app_env() == env_value


def test_without_env_param(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(ConfigError):
        get_app_env()


def test_with_invalid_env_param(monkeypatch):
    monkeypatch.setenv("APP_ENV", "invalid")
    with pytest.raises(ConfigError):
        get_app_env()


def test_get_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    assert get_database_url() == "postgresql://u:p@localhost:5432/db"


def test_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError):
        get_database_url()


def test_with_empty_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    with pytest.raises(ConfigError):
        get_database_url()
