"""Анализ трат: динамика по месяцам, медиана и выбросы, темп текущего месяца (system §2.8).

Чистые функции поверх готовых отчётов месяца (report.MonthReport).
"""

import calendar
import datetime as dt
import statistics
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from we_finance.expenses.report import MonthReport

CENT = Decimal("0.01")


@dataclass(frozen=True)
class AnalysisMonth:
    """Месяц в динамике: доход, обязательные, отложено, факт по группам и категориям."""

    month: str
    income: Decimal
    mandatory: Decimal
    saved: Decimal
    groups: dict[str, Decimal]  # код группы → факт
    categories: dict[str, Decimal]  # id категории → факт


@dataclass(frozen=True)
class Stat:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Группа или категория за полные месяцы: медиана, среднее, максимум."""

    kind: str  # "group" | "category"
    id: str
    name: str
    group_code: str
    median: Decimal
    mean: Decimal
    max: Decimal
    max_month: str | None


@dataclass(frozen=True)
class PaceItem:
    """Темп: факт к сегодняшнему дню и прогноз к концу месяца против границы."""

    id: str
    name: str
    amount: Decimal
    projected: Decimal
    target: Decimal | None


@dataclass(frozen=True)
class Pace:
    """Темп текущего месяца."""

    month: str
    day: int
    days: int
    groups: list[PaceItem]
    categories: list[PaceItem]


@dataclass(frozen=True)
class Analysis:
    """Динамика, статистика и темп."""

    months: list[AnalysisMonth]
    stats: list[Stat]
    pace: Pace | None


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_month(report: MonthReport) -> AnalysisMonth:
    """Отчёт месяца → строка динамики."""
    mandatory = next((g.amount for g in report.groups if g.code == "mandatory"), Decimal("0"))
    return AnalysisMonth(
        month=report.month,
        income=report.income,
        mandatory=mandatory,
        saved=report.saved,
        groups={g.code: g.amount for g in report.groups},
        categories={c.id: c.amount for c in report.categories},
    )


def _stat(kind: str, key: str, name: str, group: str, values: list[tuple[str, Decimal]]) -> Stat:
    amounts = [amount for _, amount in values]
    peak = max(values, key=lambda item: item[1]) if values else None
    return Stat(
        kind=kind,
        id=key,
        name=name,
        group_code=group,
        median=_money(Decimal(statistics.median(amounts))) if amounts else Decimal("0.00"),
        mean=_money(sum(amounts, Decimal("0")) / len(amounts)) if amounts else Decimal("0.00"),
        max=peak[1] if peak else Decimal("0.00"),
        max_month=peak[0] if peak and peak[1] > 0 else None,
    )


def stats(full: list[MonthReport]) -> list[Stat]:
    """Медиана, среднее, максимум по группам и категориям за полные месяцы."""
    if not full:
        return []
    last = full[-1]
    zero = Decimal("0")
    result = [
        _stat(
            "group",
            group.code,
            group.name,
            group.code,
            [
                (r.month, next((g.amount for g in r.groups if g.code == group.code), zero))
                for r in full
            ],
        )
        for group in last.groups
    ]
    for category in last.categories:
        values = [
            (r.month, next((c.amount for c in r.categories if c.id == category.id), Decimal("0")))
            for r in full
        ]
        result.append(_stat("category", category.id, category.name, category.group_code, values))
    return result


def pace(report: MonthReport, today: dt.date) -> Pace:
    """Темп месяца: факт / прошедших дней × дней в месяце; только у того, где есть граница."""
    days = calendar.monthrange(today.year, today.month)[1]

    def item(key: str, name: str, amount: Decimal, target: Decimal | None) -> PaceItem:
        return PaceItem(key, name, amount, _money(amount / today.day * days), target)

    return Pace(
        month=report.month,
        day=today.day,
        days=days,
        groups=[
            item(g.code, g.name, g.amount, g.target)
            for g in report.groups
            if g.code not in ("mandatory", "service")
        ],
        categories=[
            item(c.id, c.name, c.amount, c.target)
            for c in report.categories
            if c.target is not None
        ],
    )
