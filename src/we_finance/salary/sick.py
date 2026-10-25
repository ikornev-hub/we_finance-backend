"""Больничный: средний заработок за 2 года, процент по стажу, выплаты работодателя и Фонда."""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from we_finance.salary.models import Absence, HistoryMonth, SickPay

DAYS_IN_TWO_YEARS = 730
CENT = Decimal("0.01")
INSURANCE_BASE = {
    2024: Decimal("2225000"),
    2025: Decimal("2759000"),
    2026: Decimal("2979000"),
}
MROT = {2026: Decimal("27093")}


def average_daily(history: Sequence[HistoryMonth], year: int) -> Decimal:
    """Средний дневной заработок для больничного, начавшегося в year."""
    total = Decimal("0")
    for y in (year - 2, year - 1):
        earned = sum((h.salary + h.vacation_pay for h in history if h.year == y), Decimal("0"))
        total += min(earned, INSURANCE_BASE[y])
    floor = MROT[year] * 24 / DAYS_IN_TWO_YEARS
    return max(total / DAYS_IN_TWO_YEARS, floor).quantize(CENT, rounding=ROUND_HALF_UP)


def stage_percent(stage_start: date, on: date) -> Decimal:
    """Процент пособия по страховому стажу на дату: до 5 лет — 60 %, до 8 — 80 %, дальше — 100 %."""
    years = on.year - stage_start.year
    if (on.month, on.day) < (stage_start.month, stage_start.day):
        years -= 1
    return Decimal("0.6") if years < 5 else Decimal("0.8") if years < 8 else Decimal("1")


def sick_pay(history: Sequence[HistoryMonth], absence: Absence, stage_start: date) -> SickPay:
    """Пособие по больничному: работодатель платит первые 3 дня, Фонд — остальные."""
    average = average_daily(history, absence.start.year)
    daily = (average * stage_percent(stage_start, absence.start)).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    days = (absence.end - absence.start).days + 1
    employer_days = min(days, 3)
    return SickPay(
        average=average,
        daily=daily,
        days=days,
        employer=daily * employer_days,
        fund=daily * (days - employer_days),
    )
