"""Хранилище профиля зарплаты: договор и реализации."""

import os
import tempfile
from pathlib import Path
from typing import Protocol

import psycopg2
from pydantic import TypeAdapter

from we_finance.salary.models import Absence, AbsenceKind, HistoryMonth, SalaryProfile, SalaryTerms

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


class PostgresSalaryRepository:
    """Профиль зарплаты в Postgres. Один профиль на пользователя."""

    def __init__(self, database_url: str, user_id: str) -> None:
        self._url = database_url
        self._user_id = user_id

    def get(self) -> SalaryProfile | None:
        """Профиль или None, если ещё не заведён."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT stage_start FROM salary_profiles WHERE user_id = %s",
                        (self._user_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None

                    cur.execute(
                        "SELECT start_date, salary, meal_per_day FROM salary_terms"
                        " WHERE user_id = %s ORDER BY start_date",
                        (self._user_id,),
                    )
                    terms = tuple(
                        SalaryTerms(start=start, salary=salary, meal_per_day=meal)
                        for start, salary, meal in cur.fetchall()
                    )

                    cur.execute(
                        "SELECT kind, start_date, end_date FROM absences"
                        " WHERE user_id = %s ORDER BY start_date",
                        (self._user_id,),
                    )
                    absences = tuple(
                        Absence(kind=AbsenceKind(kind), start=start, end=end)
                        for kind, start, end in cur.fetchall()
                    )

                    cur.execute(
                        "SELECT year, month, salary, vacation_pay, excluded_days"
                        " FROM salary_history WHERE user_id = %s ORDER BY year, month",
                        (self._user_id,),
                    )
                    history = tuple(
                        HistoryMonth(year=y, month=m, salary=s, vacation_pay=v, excluded_days=d)
                        for y, m, s, v, d in cur.fetchall()
                    )
                    return SalaryProfile(
                        terms=terms, stage_start=row[0], absences=absences, history=history
                    )
        finally:
            conn.close()

    def save(self, profile: SalaryProfile) -> None:
        """Заменить профиль целиком: стереть старое и записать новое — в одной транзакции."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM salary_history WHERE user_id = %s", (self._user_id,))
                    cur.execute("DELETE FROM absences WHERE user_id = %s", (self._user_id,))
                    cur.execute("DELETE FROM salary_terms WHERE user_id = %s", (self._user_id,))
                    cur.execute(
                        "INSERT INTO salary_profiles (user_id, stage_start) VALUES (%s, %s)"
                        " ON CONFLICT (user_id) DO UPDATE"
                        " SET stage_start = EXCLUDED.stage_start, updated_at = now()",
                        (self._user_id, profile.stage_start),
                    )
                    for terms in profile.terms:
                        cur.execute(
                            "INSERT INTO salary_terms (user_id, start_date, salary, meal_per_day)"
                            " VALUES (%s, %s, %s, %s)",
                            (self._user_id, terms.start, terms.salary, terms.meal_per_day),
                        )
                    for absence in profile.absences:
                        cur.execute(
                            "INSERT INTO absences (user_id, kind, start_date, end_date)"
                            " VALUES (%s, %s, %s, %s)",
                            (self._user_id, absence.kind, absence.start, absence.end),
                        )
                    for month in profile.history:
                        cur.execute(
                            "INSERT INTO salary_history"
                            " (user_id, year, month, salary, vacation_pay, excluded_days)"
                            " VALUES (%s, %s, %s, %s, %s, %s)",
                            (
                                self._user_id,
                                month.year,
                                month.month,
                                month.salary,
                                month.vacation_pay,
                                month.excluded_days,
                            ),
                        )
        finally:
            conn.close()
