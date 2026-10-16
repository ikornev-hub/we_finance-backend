import os
from pathlib import Path

ALLOWED_ENVS = ("dev", "test", "stage", "prod")


class ConfigError(RuntimeError):
    """Неверная конфигурация приложения"""


def get_app_env() -> str:
    env = os.environ.get("APP_ENV")
    if env not in ALLOWED_ENVS:
        raise ConfigError(f"Недопустимое значение переменной окружения APP_ENV: {env}")
    return env


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("DATABASE_URL не задан")
    return url


def get_credit_data_path() -> Path:
    """Файл с кредитами (JSON). Реальные данные — только в локальном файле из .gitignore."""
    path = os.environ.get("CREDIT_DATA_PATH")
    if not path:
        raise ConfigError("CREDIT_DATA_PATH не задан")
    return Path(path)
