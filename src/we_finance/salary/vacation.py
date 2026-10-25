"""Отпускные: средний заработок, дни отпуска, дата выплаты."""

import calendar
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from we_finance.credit.calendar_ru import FIXED_HOLIDAYS
from we_finance.credit.schedule import CENT
from we_finance.salary.models import Absence, HistoryMonth, SalaryTerms
from we_finance.salary.payroll import absence_on, accrue_month
from we_finance.salary.workdays import month_end, previous_business_day


def months_before(year: int, month: int, count: int) -> list[tuple[int, int]]:
    """count месяцев ДО указанного, от старого к новому."""
    result = []
    for _ in range(count):
        month -= 1
        if month == 0:
            year -= 1
            month = 12
        result.append((year, month))
    return result[::-1]


def vacation_days(absence: Absence) -> int:
    """Календарные дни отпуска без праздников."""
    count = 0
    day = absence.start
    while day <= absence.end:
        if (day.month, day.day) not in FIXED_HOLIDAYS:
            count += 1
        day += timedelta(days=1)
    return count


def vacation_pay_date(absence: Absence) -> date:
    """Не позже чем за 3 календарных дня до начала отпуска, на рабочий день раньше."""
    return previous_business_day(absence.start - timedelta(days=3))


def month_history(
    year: int, month: int, terms: Sequence[SalaryTerms], absences: Sequence[Absence]
) -> HistoryMonth:
    """Месяц истории из расчёта: оклад и календарные дни в отсутствиях."""
    first, last = date(year, month, 1), month_end(year, month)
    excluded = 0
    day = first
    while day <= last:
        if absence_on(absences, day) is not None:
            excluded += 1
        day += timedelta(days=1)
    accrual = accrue_month(year, month, terms, absences)
    return HistoryMonth(year=year, month=month, salary=accrual.salary, excluded_days=excluded)


def average_daily(history: Sequence[HistoryMonth], year: int, month: int) -> Decimal:
    """Средний дневной заработок для отпуска, начинающегося в этом месяце."""
    by_month = {(h.year, h.month): h for h in history}
    earned = Decimal("0")
    days = Decimal("0")
    for y, m in months_before(year, month, 12):
        h = by_month.get((y, m))
        if h is None:
            raise ValueError(f"Нет данных за {y}-{m:02}: нужны 12 месяцев до отпуска")
        earned += h.salary
        in_month = calendar.monthrange(y, m)[1]
        if h.excluded_days == 0:
            days += Decimal("29.3")
        else:
            days += Decimal("29.3") * (in_month - h.excluded_days) / in_month
    return (earned / days).quantize(CENT, rounding=ROUND_HALF_UP)


def vacation_pay(history: Sequence[HistoryMonth], absence: Absence) -> Decimal:
    """Отпускные: средний дневной × дни отпуска, до копеек."""
    average = average_daily(history, absence.start.year, absence.start.month)
    return (average * vacation_days(absence)).quantize(CENT, rounding=ROUND_HALF_UP)
