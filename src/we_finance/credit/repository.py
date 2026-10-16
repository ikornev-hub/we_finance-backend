"""Хранилище кредитов: интерфейс и реализации (требования, раздел 4).

Сервис и API работают с интерфейсом LoanRepository и не знают, что внутри:
словарь в памяти (тесты), JSON-файл (сейчас) или Postgres (фаза 2).
"""

import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from we_finance.credit.models import Loan, Prepayment, StoredLoan

# pydantic умеет проверять и сериализовать обычные dataclass-ы: Decimal → строка, date → ISO.
_FILE_FORMAT = TypeAdapter(list[StoredLoan])


class LoanRepository(Protocol):
    """Что умеет хранилище кредитов — без деталей, как именно хранит."""

    def list_loans(self) -> list[StoredLoan]:
        """Все кредиты."""
        ...

    def get(self, loan_id: str) -> StoredLoan | None:
        """Кредит по id или None, если такого нет."""
        ...

    def add(self, loan: Loan) -> None:
        """Сохранить новый кредит (id уже задан)."""
        ...

    def add_prepayment(self, loan_id: str, prepayment: Prepayment) -> None:
        """Добавить ЧДП к кредиту. Удалять и менять ЧДП нельзя (сценарий С7)."""
        ...


class InMemoryLoanRepository:
    """Хранилище в памяти процесса: для тестов и как основа файлового."""

    def __init__(self, loans: list[StoredLoan] | None = None) -> None:
        self._loans: dict[str, StoredLoan] = {stored.loan.id: stored for stored in loans or []}

    def list_loans(self) -> list[StoredLoan]:
        """Все кредиты в порядке добавления."""
        return list(self._loans.values())

    def get(self, loan_id: str) -> StoredLoan | None:
        """Кредит по id или None."""
        return self._loans.get(loan_id)

    def add(self, loan: Loan) -> None:
        """Сохранить новый кредит; повтор id — ошибка программиста."""
        if loan.id in self._loans:
            raise ValueError(f"Кредит {loan.id} уже есть")
        self._loans[loan.id] = StoredLoan(loan=loan)
        self._save()

    def add_prepayment(self, loan_id: str, prepayment: Prepayment) -> None:
        """Добавить ЧДП: хранимое не меняется, а заменяется новой версией."""
        stored = self._loans[loan_id]
        self._loans[loan_id] = replace(stored, prepayments=(*stored.prepayments, prepayment))
        self._save()

    def _save(self) -> None:
        """В памяти сохранять некуда; файловое хранилище переопределяет."""


class JsonLoanRepository(InMemoryLoanRepository):
    """Хранилище в JSON-файле. Читает при создании, переписывает файл целиком при изменении."""

    def __init__(self, path: Path) -> None:
        self._path = path
        loans = _FILE_FORMAT.validate_json(path.read_bytes()) if path.exists() else []
        super().__init__(loans)

    def _save(self) -> None:
        """Атомарная запись: во временный файл рядом, потом замена одним действием."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = _FILE_FORMAT.dump_json(self.list_loans(), indent=2)
        with tempfile.NamedTemporaryFile(dir=self._path.parent, delete=False) as tmp:
            tmp.write(data)
            tmp.write(b"\n")  # файл заканчивается переводом строки
        os.replace(tmp.name, self._path)
