"""Хранилище профиля зарплаты: договор и реализации."""

import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from we_finance.salary.models import SalaryProfile

_FILE_FORMAT = TypeAdapter(SalaryProfile)


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


class JsonSalaryRepository(InMemorySalaryRepository):
    """Профиль в JSON-файле. Читает при создании, переписывает файл целиком при сохранении."""

    def __init__(self, path: Path) -> None:
        self._path = path
        profile = _FILE_FORMAT.validate_json(path.read_bytes()) if path.exists() else None
        super().__init__(profile)

    def save(self, profile: SalaryProfile) -> None:
        """Сохранить в памяти и в файл — атомарно: во временный файл рядом, потом замена."""
        super().save(profile)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self._path.parent, delete=False) as tmp:
            tmp.write(_FILE_FORMAT.dump_json(profile, indent=2))
            tmp.write(b"\n")
        os.replace(tmp.name, self._path)
