"""Схемы запросов и ответов API."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Ответ проверки здоровья сервиса."""

    status: str
    db: str


class VersionResponse(BaseModel):
    """Версия приложения."""

    version: str
    env: str
