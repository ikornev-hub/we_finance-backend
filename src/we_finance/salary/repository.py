"""Хранилище профиля зарплаты: договор и реализации."""

from typing import Protocol

from we_finance.salary.models import SalaryProfile


class SalaryRepository(Protocol):
    """Что умеет хранилище профиля — без деталей, как именно хранит."""

    def get(self) -> SalaryProfile | None:
        """Профиль или None, если ещё не заведён."""
        ...

    def save(self, profile: SalaryProfile) -> None:
        """Сохранить профиль целиком."""
        ...


class InMemorySalaryRepository:
    """Профиль в памяти процесса: для проверок и как основа файлового."""

    def __init__(self, profile: SalaryProfile | None = None) -> None:
        self._profile = profile

    def get(self) -> SalaryProfile | None:
        """Сохранённый профиль или None."""
        return self._profile

    def save(self, profile: SalaryProfile) -> None:
        """Заменить профиль целиком."""
        self._profile = profile
