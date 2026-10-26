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
class Goal:  # pylint: disable=too-many-instance-attributes  # поля цели = хранимое
    """Цель: сумма, срок или фиксированный взнос, сколько было отложено до учёта."""

    id: str
    name: str
    target_amount: Decimal
    deadline: dt.date | None
    monthly_amount: Decimal | None
    initial_amount: Decimal = ZERO
    start_date: dt.date | None = None  # с какого числа копить; до этого месяца план 0
    loan_id: str | None = None  # цель «закрыть кредит»: взносы — ЧДП по нему


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


def _first_month(goal: Goal) -> dt.date | None:
    """Первое число месяца старта цели."""
    return goal.start_date.replace(day=1) if goal.start_date else None


def _next_month(day: dt.date) -> dt.date:
    """Первое число следующего месяца."""
    return (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def plan(goal: Goal, saved_before: Decimal, month_start: dt.date) -> Decimal:
    """Сколько откладывать в этом месяце, чтобы успеть к сроку (или фиксированный взнос).

    До месяца старта — 0; месяцы до срока считаются от месяца старта.
    """
    left = goal.target_amount - saved_before
    first = _first_month(goal)
    if left <= 0 or (first is not None and month_start < first):
        return ZERO
    if goal.deadline is None:
        return min(goal.monthly_amount or ZERO, left)
    if goal.deadline < month_start:
        return left  # срок прошёл — весь остаток
    months = months_between(month_start, goal.deadline)
    return (left / months).quantize(RUBLE, rounding=ROUND_CEILING).quantize(CENT)


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


def eta(goal: Goal, saved_before: Decimal, real: Decimal, month_start: dt.date) -> str | None:
    """Месяц достижения: «2027-08». None — и план нулевой, не достигается.

    Этот месяц — реальный взнос (может быть меньше плана, если не хватает), дальше — по плану
    (решение заказчика 2026-10-27: один плохой месяц не хоронит цель).
    """
    left = goal.target_amount - saved_before - real
    if left <= 0:
        return f"{month_start.year}-{month_start.month:02}"
    nxt = max(_next_month(month_start), _first_month(goal) or month_start)
    monthly = plan(goal, goal.target_amount - left, nxt)
    if monthly <= 0:
        return None
    months = int((left / monthly).to_integral_value(rounding=ROUND_CEILING))
    index = nxt.year * 12 + nxt.month - 1 + months - 1
    return f"{index // 12}-{index % 12 + 1:02}"


def by_paydays(
    amount: Decimal, payments: list[tuple[dt.date, str, Decimal]]
) -> list[tuple[dt.date, str, Decimal]]:
    """Разложить взнос месяца по дням выплат пропорционально их суммам (до рубля).

    payments: (дата, вид, сумма на руки). Остаток округления — в последнюю выплату.
    """
    total = sum((net for _, _, net in payments), ZERO)
    if amount <= 0 or total <= 0:
        return []
    result = []
    rest = amount
    for index, (day, kind, net) in enumerate(payments):
        if index == len(payments) - 1:
            part = rest
        else:
            part = (amount * net / total).quantize(RUBLE, rounding=ROUND_HALF_UP)
            rest -= part
        result.append((day, kind, part.quantize(CENT)))
    return result
