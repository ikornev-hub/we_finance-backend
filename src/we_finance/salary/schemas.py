"""Схемы API зарплаты: что принимает и что отдаёт HTTP (pydantic).

Проверки одного поля — через Field; проверки нескольких полей — model_validator.
"""

from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from we_finance.salary.models import AbsenceKind, PaymentKind

EXAMPLE_PROFILE = {
    "terms": [
        {"start": "2025-01-01", "salary": "120000.00", "meal_per_day": "400.00"},
        {"start": "2026-07-01", "salary": "150000.00", "meal_per_day": "400.00"},
    ],
    "absences": [
        {"kind": "unpaid", "start": "2026-03-20", "end": "2026-03-20"},
        {"kind": "vacation", "start": "2026-07-06", "end": "2026-07-19"},
        {"kind": "sick", "start": "2026-10-12", "end": "2026-10-16"},
    ],
    "history": [
        {"year": year, "month": month, "salary": salary}
        for year, salary in ((2024, "110000.00"), (2025, "120000.00"))
        for month in range(1, 13)
    ],
    "stage_start": "2022-03-01",
}


class SalaryTermsIn(BaseModel):
    """Условия: с даты start действуют этот оклад и компенсация питания за день."""

    start: date
    salary: Decimal = Field(gt=0, decimal_places=2)
    meal_per_day: Decimal = Field(ge=0, decimal_places=2)


class AbsenceIn(BaseModel):
    """Отсутствие: вид и даты с–по включительно."""

    kind: AbsenceKind
    start: date
    end: date

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        """Конец не раньше начала."""
        if self.end < self.start:
            raise ValueError(f"Конец {self.end} раньше начала {self.start}")
        return self


class HistoryMonthIn(BaseModel):
    """Месяц истории до начала учёта: оклад, отпускные, исключённые дни."""

    year: int = Field(ge=2000)
    month: int = Field(ge=1, le=12)
    salary: Decimal = Field(ge=0, decimal_places=2)
    vacation_pay: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    excluded_days: int = Field(default=0, ge=0, le=31)


class SalaryProfileIn(BaseModel):
    """Профиль зарплаты: условия, отсутствия, история до начала учёта, начало стажа."""

    model_config = ConfigDict(json_schema_extra={"examples": [EXAMPLE_PROFILE]})

    terms: list[SalaryTermsIn] = Field(min_length=1)
    absences: list[AbsenceIn] = []
    history: list[HistoryMonthIn] = []
    stage_start: date

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        """Проверки, связывающие несколько записей."""
        for earlier, later in pairwise(self.terms):
            if later.start <= earlier.start:
                raise ValueError(
                    f"Условия: даты должны строго возрастать ({earlier.start} → {later.start})"
                )

        ordered = sorted(self.absences, key=lambda a: a.start)
        for earlier, later in pairwise(ordered):
            if later.start <= earlier.end:
                raise ValueError(
                    f"Отсутствия {earlier.start}–{earlier.end}"
                    f" и {later.start}–{later.end} пересекаются"
                )

        seen = set()
        for month in self.history:
            key = (month.year, month.month)
            if key in seen:
                raise ValueError(f"В истории дважды {month.year}-{month.month:02}")
            seen.add(key)
        return self


class SalaryCalculationIn(BaseModel):
    """Профиль и год, за который посчитать выплаты."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"profile": EXAMPLE_PROFILE, "year": 2026}]}
    )
    profile: SalaryProfileIn
    year: int = Field(ge=2000, le=2100)


# ---------- ответ ----------


class PaymentOut(BaseModel):
    """Выплата: когда, что, за какой месяц, начислено, НДФЛ, на руки."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    kind: PaymentKind
    for_month: int
    gross: Decimal
    tax: Decimal
    net: Decimal


class MonthTotalOut(BaseModel):
    """Итог месяца по всем выплатам за него."""

    model_config = ConfigDict(from_attributes=True)

    month: int
    gross: Decimal
    tax: Decimal
    net: Decimal


class YearReportOut(BaseModel):
    """Отчёт за год: все выплаты, итоги по месяцам и за год."""

    year: int
    payments: list[PaymentOut]
    months: list[MonthTotalOut]
    gross: Decimal
    tax: Decimal
    net: Decimal
