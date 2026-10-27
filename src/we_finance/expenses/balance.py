"""Остаток на счёте по дням: факт по выписке и ожидание по плану (решение заказчика 2026-10-27).

Ожидание: остаток на начало месяца + доходы и обязательные платежи в свои даты − взносы целей
в дни выплат − траты по границам ровно по дням. Сравнение «на счёте сейчас» с «должно быть» —
сколько потрачено относительно ожидаемого, даже без свежей выписки (остаток видно в банке).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")
DAY = timedelta(days=1)


@dataclass(frozen=True)
class Event:
    """Плановое движение денег: + доход, − платёж."""

    day: date
    amount: Decimal
    label: str


@dataclass(frozen=True)
class Point:
    """Остаток на конец дня."""

    day: date
    balance: Decimal


def balance_on(anchor: tuple[date, Decimal], net: dict[date, Decimal], day: date) -> Decimal:
    """Остаток на конец дня day по якорю (день, остаток) и сальдо операций по дням."""
    anchor_day, anchor_balance = anchor
    if day >= anchor_day:
        moved = sum((v for d, v in net.items() if anchor_day < d <= day), ZERO)
        return anchor_balance + moved
    moved = sum((v for d, v in net.items() if day < d <= anchor_day), ZERO)
    return anchor_balance - moved


def actual(
    anchor: tuple[date, Decimal], net: dict[date, Decimal], start: date, until: date
) -> list[Point]:
    """Факт по дням от start до until включительно."""
    points, day = [], start
    while day <= until:
        points.append(Point(day, balance_on(anchor, net, day)))
        day += DAY
    return points


def expected(
    start_balance: Decimal, start: date, end: date, events: list[Event], spending: Decimal
) -> list[Point]:
    """Ожидание по дням [start, end): события в свои даты, траты — ровно по дням."""
    days = (end - start).days
    per_day = spending / days if days else ZERO
    points, balance, day = [], start_balance, start
    while day < end:
        balance += sum((e.amount for e in events if e.day == day), ZERO) - per_day
        points.append(Point(day, balance.quantize(CENT, rounding=ROUND_HALF_UP)))
        day += DAY
    return points
