"""Хранилище кредитов: интерфейс и реализации (требования, раздел 4).

Сервис и API работают с интерфейсом LoanRepository и не знают, что внутри:
словарь в памяти (тесты), JSON-файл (сейчас) или Postgres (фаза 2).
"""

import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import psycopg2
from pydantic import TypeAdapter

from we_finance.credit.models import (
    DayCount,
    Loan,
    LoanStatus,
    PaymentDayChange,
    Prepayment,
    PrepaymentMode,
    RatePeriod,
    StatusChange,
    StoredLoan,
)

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

    def add_status(self, loan_id: str, status: LoanStatus) -> None:
        """Записать переход состояния (С8): удалён, завершён, снова активен."""
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

    def add_status(self, loan_id: str, status: LoanStatus) -> None:
        """Переход состояния: к истории добавляется запись."""
        stored = self._loans[loan_id]
        change = StatusChange(status=status, changed_at=datetime.now(UTC))
        self._loans[loan_id] = replace(stored, status_history=(*stored.status_history, change))
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


class PostgresLoanRepository:
    """Кредитыв postgres. Видит и пишет только кредиты одного пользователя"""

    def __init__(self, database_url: str, user_id: str) -> None:
        self._url = database_url
        self._user_id = user_id

    def add(self, loan: Loan) -> None:
        """Сохранить новый кредит со ставками и сменами дня - все или ничего."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO loans (id, user_id, name, principal, payment, months,
                                           issue_date, first_payment_date, day_count,
                                           weekend_shift, monthly_fee)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            loan.id,
                            self._user_id,
                            loan.name,
                            loan.principal,
                            loan.payment,
                            loan.months,
                            loan.issue_date,
                            loan.first_payment_date,
                            loan.day_count,
                            loan.weekend_shift,
                            loan.monthly_fee,
                        ),
                    )

                    for rate in loan.rates:
                        cur.execute(
                            "INSERT INTO rate_periods (loan_id, start_date, annual_rate)"
                            " VALUES (%s, %s, %s)",
                            (loan.id, rate.start, rate.annual_rate),
                        )

                    for change in loan.payment_day_changes:
                        cur.execute(
                            "INSERT INTO payment_day_changes (loan_id, start_date, day)"
                            " VALUES (%s, %s, %s)",
                            (loan.id, change.start, change.day),
                        )
        finally:
            conn.close()

    def get(self, loan_id: str) -> StoredLoan | None:
        """Кредит по id или None, если такого нет или он чужой"""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, name, principal, payment, months, issue_date,
                               first_payment_date, day_count, weekend_shift, monthly_fee
                        FROM loans
                        WHERE id = %s AND user_id = %s
                        """,
                        (loan_id, self._user_id),
                    )

                    row = cur.fetchone()
                    if row is None:
                        return None

                    cur.execute(
                        "SELECT start_date, annual_rate FROM rate_periods"
                        " WHERE loan_id = %s ORDER BY start_date",
                        (loan_id,),
                    )
                    rates = tuple(
                        RatePeriod(start=start, annual_rate=rate) for start, rate in cur.fetchall()
                    )

                    cur.execute(
                        "SELECT start_date, day FROM payment_day_changes"
                        " WHERE loan_id = %s ORDER BY start_date",
                        (loan_id,),
                    )
                    day_changes = tuple(
                        PaymentDayChange(start=start, day=day) for start, day in cur.fetchall()
                    )

                    # Две ЧДП в один день — в том порядке, в каком их вносили.
                    cur.execute(
                        """
                        SELECT prepayment_date, amount, mode
                        FROM prepayments
                        WHERE loan_id = %s
                        ORDER BY prepayment_date, created_at
                        """,
                        (loan_id,),
                    )
                    prepayments = tuple(
                        Prepayment(date=paid_on, amount=amount, mode=PrepaymentMode(mode))
                        for paid_on, amount, mode in cur.fetchall()
                    )

                    loan = Loan(
                        id=row[0],
                        name=row[1],
                        principal=row[2],
                        rates=rates,
                        payment=row[3],
                        months=row[4],
                        issue_date=row[5],
                        first_payment_date=row[6],
                        day_count=DayCount(row[7]),
                        weekend_shift=row[8],
                        monthly_fee=row[9],
                        payment_day_changes=day_changes,
                    )
                    cur.execute(
                        "SELECT status, changed_at FROM loan_status_changes"
                        " WHERE loan_id = %s ORDER BY id",
                        (loan_id,),
                    )
                    history = tuple(
                        StatusChange(status=LoanStatus(status), changed_at=changed_at)
                        for status, changed_at in cur.fetchall()
                    )
                    return StoredLoan(loan=loan, prepayments=prepayments, status_history=history)
        finally:
            conn.close()

    def add_prepayment(self, loan_id: str, prepayment: Prepayment) -> None:
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO prepayments (id, loan_id, prepayment_date, amount, mode)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            uuid4().hex,
                            loan_id,
                            prepayment.date,
                            prepayment.amount,
                            prepayment.mode,
                        ),
                    )
        finally:
            conn.close()

    def list_loans(self) -> list[StoredLoan]:
        """Все кредиты пользователя в порядке добавления."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM loans WHERE user_id = %s ORDER BY created_at",
                        (self._user_id,),
                    )
                    ids = [row[0] for row in cur.fetchall()]
        finally:
            conn.close()
        return [self.get(loan_id) for loan_id in ids]

    def add_status(self, loan_id: str, status: LoanStatus) -> None:
        """Записать переход состояния (С8). Таблица только для добавления."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO loan_status_changes (loan_id, status) VALUES (%s, %s)",
                        (loan_id, status),
                    )
        finally:
            conn.close()
