"""Цели накоплений: отложено, сколько откладывать, когда достигнем (system/expenses.md §2.7).

Чистые функции: цели, взносы и месяц на входе — числа на выходе. Без базы и HTTP.
"""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
RUBLE = Decimal("1")
CENT = Decimal("0.01")

# Альфа: «Внутрибанковский перевод между счетами… Со счёта <20 цифр> на счёт <20 цифр>».
_FROM = re.compile(r"Со сч[её]та (\d+)")
_TO = re.compile(r"на сч[её]т (\d+)")


@dataclass(frozen=True)
class Goal:
    """Цель: сумма, срок или фиксированный взнос, сколько было отложено до учёта."""

    id: str
    name: str
    target_amount: Decimal
    deadline: dt.date | None
    monthly_amount: Decimal | None
    initial_amount: Decimal = ZERO


@dataclass(frozen=True)
class Contribution:
    """Взнос в цель: плюс — отложил, минус — снял."""

    goal_id: str
    day: dt.date
    amount: Decimal


@dataclass(frozen=True)
class SavingsOperation:
    """Операция категории «Накопления» из выписки."""

    day: dt.date
    amount: Decimal  # минус — ушло на накопительный счёт
    description: str


def from_statement(
    operations: list[SavingsOperation], accounts: dict[str, str]
) -> list[Contribution]:
    """Переводы на накопительный счёт → взносы его цели; с него обратно — снятия.

    accounts: последние 4 цифры накопительного счёта → id цели.
    """
    result = []
    for op in operations:
        pattern = _TO if op.amount < 0 else _FROM
        found = pattern.search(op.description)
        goal_id = accounts.get(found.group(1)[-4:]) if found else None
        if goal_id:
            result.append(Contribution(goal_id, op.day, -op.amount))
    return result


def savings_tail(description: str, outgoing: bool) -> str | None:
    """Хвост счёта, на который ушло (outgoing) или с которого пришло — для распознавания."""
    found = (_TO if outgoing else _FROM).search(description)
    return found.group(1)[-4:] if found else None


def saved(goal: Goal, contributions: list[Contribution], before: dt.date | None = None) -> Decimal:
    """Отложено по цели (до даты before, не включая)."""
    mine = [c for c in contributions if c.goal_id == goal.id]
    return goal.initial_amount + sum(
        (c.amount for c in mine if before is None or c.day < before), ZERO
    )


def months_between(start: dt.date, end: dt.date) -> int:
    """Месяцев от месяца start до месяца end включительно (≥ 1)."""
    return max((end.year - start.year) * 12 + end.month - start.month + 1, 1)


def plan(goal: Goal, saved_before: Decimal, month_start: dt.date) -> Decimal:
    """Сколько откладывать в этом месяце, чтобы успеть к сроку (или фиксированный взнос)."""
    left = goal.target_amount - saved_before
    if left <= 0:
        return ZERO
    if goal.deadline is None:
        return min(goal.monthly_amount or ZERO, left)
    if goal.deadline < month_start:
        return left  # срок прошёл — весь остаток
    months = months_between(month_start, goal.deadline)
    return (left / months).quantize(RUBLE, rounding=ROUND_CEILING)


def allocate(plans: dict[str, Decimal], available: Decimal) -> dict[str, Decimal]:
    """Не хватает на все планы — каждой цели пропорционально её плану (решение заказчика)."""
    total = sum(plans.values(), ZERO)
    if total <= 0:
        return {goal_id: ZERO for goal_id in plans}
    if available >= total:
        return dict(plans)
    factor = max(available, ZERO) / total
    return {
        goal_id: (amount * factor).quantize(CENT, rounding=ROUND_HALF_UP)
        for goal_id, amount in plans.items()
    }


def eta(goal: Goal, saved_now: Decimal, monthly: Decimal, month_start: dt.date) -> str | None:
    """Месяц достижения при таком взносе: «2027-08»; взнос 0 и не достигнута — None."""
    left = goal.target_amount - saved_now
    if left <= 0:
        return f"{month_start.year}-{month_start.month:02}"
    if monthly <= 0:
        return None
    months = int((left / monthly).to_integral_value(rounding=ROUND_CEILING))
    index = month_start.year * 12 + month_start.month - 1 + months - 1
    return f"{index // 12}-{index % 12 + 1:02}"
