"""Модель данных расчет заработной платы"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class SalaryTerms:
    """Условия по ЗП"""

    start: date
    salary: Decimal
    meal_per_day: Decimal


class AbsenceKind(StrEnum):
    """Тип отсутствия"""

    VACATION = "vacation"
    SICK = "sick"
    UNPAID = "unpaid"


@dataclass(frozen=True)
class Absence:
    """Статус отсутствия"""

    kind: AbsenceKind
    start: date
    end: date


@dataclass(frozen=True)
class MonthAccrual:
    """Статистика за месяц"""

    year: int
    month: int
    workdays: int
    worked: int
    salary: Decimal
    meal: Decimal
