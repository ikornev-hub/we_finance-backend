import os

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
