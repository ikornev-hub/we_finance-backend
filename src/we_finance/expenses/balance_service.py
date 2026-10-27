"""Остаток на счёте по дням на месяц: факт по выписке и ожидание по плану (Решение 2026-10-27)."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from we_finance.credit.models import LoanStatus
from we_finance.credit.repository import LoanRepository
from we_finance.credit.schedule import calculate
from we_finance.expenses import balance
from we_finance.expenses.balance import Event, Point
from we_finance.expenses.repository import PostgresExpenseRepository
from we_finance.expenses.service import goals_view, month_range, month_report
from we_finance.salary import service as salary_service
from we_finance.salary.repository import SalaryRepository

DAY = timedelta(days=1)
_PAYMENT = {
    "advance": "Аванс",
    "remainder": "Зарплата",
    "vacation": "Отпускные",
    "sick_employer": "Больничный (работодатель)",
    "sick_fund": "Больничный (СФР)",
}


@dataclass(frozen=True)
class BalanceView:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Остаток на месяц: на начало, факт по дням (до конца выписки), ожидание по дням."""

    month: str
    today: date
    statement_until: date | None  # по какой день есть выписка
    start_balance: Decimal | None  # на конец предыдущего месяца; None — выписки нет
    actual: list[Point]
    expected: list[Point]
    events: list[Event]  # плановые доходы и платежи месяца
    spending: Decimal  # траты по границам за месяц — ровно по дням


def _events(
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month: str,
    today: date,
) -> list[Event]:
    """Доходы и обязательные платежи месяца в свои даты, взносы целей — в дни выплат."""
    start, end = month_range(month)
    events = []
    try:
        payments = salary_service.year(salary_repo, start.year)
    except salary_service.ProfileNotFoundError, salary_service.SalaryError:
        payments = []
    events += [
        Event(p.date, p.net, _PAYMENT.get(str(p.kind), str(p.kind)))
        for p in payments
        if start <= p.date < end
    ]
    for stored in loan_repo.list_loans():
        if stored.status == LoanStatus.DELETED:
            continue
        rows, _ = calculate(stored.loan, stored.prepayments)
        events += [
            Event(r.date, -r.payment, f"Платёж: {stored.loan.name}")
            for r in rows
            if start <= r.date < end
        ]
        events += [  # ЧДП, уже записанные в «Кредитах»
            Event(p.date, -p.amount, f"ЧДП: {stored.loan.name}")
            for p in stored.prepayments
            if start <= p.date < end
        ]
    last = (end - DAY).day
    events += [
        Event(start.replace(day=min(day, last)), -amount, name)
        for name, amount, day in repo.mandatory_rule_days()
    ]
    for goal in goals_view(repo, salary_repo, loan_repo, month, today):
        events += [Event(p.date, -p.amount, f"Цель: {goal.name}") for p in goal.paydays]
    return sorted(events, key=lambda e: e.day)


def balance_view(
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month: str,
    today: date,
) -> BalanceView:
    """Факт — от остатка в шапке последней выписки; ожидание — от остатка на начало месяца."""
    start, end = month_range(month)
    until = repo.statement_until()
    start_balance, points = _facts(repo, start, end, until)
    events = _events(repo, salary_repo, loan_repo, month, today)
    spending = month_report(repo, salary_repo, loan_repo, month, today).forecast.limits_total
    return BalanceView(
        month,
        today,
        until,
        start_balance,
        points,
        balance.expected(start_balance or Decimal("0"), start, end, events, spending),
        events,
        spending,
    )


def _facts(
    repo: PostgresExpenseRepository, start: date, end: date, until: date | None
) -> tuple[Decimal | None, list[Point]]:
    """Остаток на начало месяца и факт по дням — от остатка в шапке последней выписки."""
    anchor = repo.balance_anchor()
    if anchor is None:
        return None, []
    net = repo.daily_net(min(start - DAY, anchor[0]), max(end, anchor[0]))
    points = balance.actual(anchor, net, start, min(end - DAY, until)) if until else []
    return balance.balance_on(anchor, net, start - DAY), points
