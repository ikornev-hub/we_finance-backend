"""Получение данных на конкретный день"""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from we_finance.salary.models import Absence, MonthAccrual, SalaryTerms
from we_finance.salary.workdays import business_days, month_end


def terms_on(terms: Sequence[SalaryTerms], day: date) -> SalaryTerms:
    """Получить актуальные соглашения на конкретный день"""
    sorted_terms = sorted(terms, key=lambda term: term.start)
    current_term = None
    for term in sorted_terms:
        if term.start <= day:
            current_term = term
    if current_term is None:
        raise ValueError(f"Нет условий на {day}")
    return current_term


def absence_on(absences: Sequence[Absence], day: date) -> Absence | None:
    """Отсутствие, в которое попадает день, или None"""
    for absence in absences:
        if absence.start <= day <= absence.end:
            return absence
    return None


def worked_days(start: date, end: date, absences: Sequence[Absence]) -> list[date]:
    """Рабочие дни отрезка, не попавшие ни в одно отсутствие"""
    dates = business_days(start, end)
    return [day for day in dates if absence_on(absences, day) is None]


def salary_for(days: Sequence[date], terms: Sequence[SalaryTerms], month_workdays: int) -> Decimal:
    """Сумма выплат по зарплате за каждый день"""
    return sum([terms_on(terms, day).salary / month_workdays for day in days], Decimal("0.00"))


def meal_for(days: Sequence[date], terms: Sequence[SalaryTerms]) -> Decimal:
    """Сумма выплат по питанию за каждый день"""
    return sum([terms_on(terms, day).meal_per_day for day in days], Decimal("0"))


def accrue_month(
    year: int, month: int, terms: Sequence[SalaryTerms], absences: Sequence[Absence]
) -> MonthAccrual:
    """Статистика за месяц"""
    first, last = date(year, month, day=1), month_end(year, month)
    count_work_day = len(business_days(first, last))
    complete_days = worked_days(first, last, absences)
    accrue_job = salary_for(complete_days, terms, count_work_day).quantize(
        Decimal("0.00"), rounding=ROUND_HALF_UP
    )
    accrue_meal = meal_for(complete_days, terms).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)
    return MonthAccrual(year, month, count_work_day, len(complete_days), accrue_job, accrue_meal)
