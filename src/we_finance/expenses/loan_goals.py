"""Цели «закрыть кредит»: план месяца, ЧДП по дням выплат, дата закрытия (system/expenses.md §2.7).

Всё — от фактов: остаток долга по истории кредита на сегодня, дни и суммы выплат из «Доходов».
Режим «к сроку» каждый месяц заново подбирает долю выплат от сегодняшнего остатка: не хватило в
этом месяце — следующие ЧДП вырастут (приоритет — закрыть к дате). Режим «взнос в месяц» — сумма
ЧДП в месяц постоянная, дата закрытия следует из неё.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from we_finance.credit.models import LoanStatus, Prepayment, PrepaymentMode, StoredLoan
from we_finance.credit.repository import LoanRepository
from we_finance.expenses import goals as goal_rules
from we_finance.expenses import payoff
from we_finance.expenses.goals import Goal
from we_finance.salary import service as salary_service
from we_finance.salary.repository import SalaryRepository

ZERO = Decimal("0")
CENT = Decimal("0.01")
DAY = timedelta(days=1)

Paid = tuple[date, str, Decimal]  # дата выплаты, вид (advance / remainder), на руки


def next_month(day: date) -> date:
    """Первое число следующего месяца."""
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


class Paydays:  # pylint: disable=too-few-public-methods  # кэш с одним вопросом
    """Аванс и остаток зарплаты по годам; профиля нет — пусто. Считается раз на запрос."""

    def __init__(self, repo: SalaryRepository) -> None:
        self._repo = repo
        self._years: dict[int, list[Paid]] = {}

    def _year(self, year: int) -> list[Paid]:
        if year not in self._years:
            try:
                payments = salary_service.year(self._repo, year)
            except salary_service.ProfileNotFoundError, salary_service.SalaryError:
                payments = []
            self._years[year] = sorted(
                (p.date, str(p.kind), p.net)
                for p in payments
                if str(p.kind) in {"advance", "remainder"}
            )
        return self._years[year]

    def between(self, start: date, end: date) -> list[Paid]:
        """Выплаты с start включительно до end не включая."""
        if end <= start:
            return []
        result = []
        for year in range(start.year, (end - DAY).year + 1):
            result += [paid for paid in self._year(year) if start <= paid[0] < end]
        return result


def _net(paid: list[Paid]) -> list[payoff.Payday]:
    return [(day, net) for day, _, net in paid]


def _prepayments(paid: list[Paid]) -> list[Prepayment]:
    return [
        Prepayment(day, amount, PrepaymentMode.REDUCE_TERM) for day, _, amount in paid if amount > 0
    ]


def _rub(amount: Decimal) -> str:
    return f"{amount:,.0f} ₽".replace(",", " ")


@dataclass(frozen=True)
class LoanGoalState:
    """Цель по кредиту на месяц: насколько уменьшился долг (всего и к началу месяца), план ЧДП."""

    saved: Decimal
    saved_before: Decimal
    plan: Decimal


@dataclass(frozen=True)
class LoanGoalOutcome:
    """ЧДП этого месяца по дням выплат, дата закрытия, экономия процентов, пояснение."""

    paydays: list[Paid]
    closes_on: date | None
    interest_saved: Decimal
    note: str | None


class LoanGoals:
    """Расчёты целей по кредитам на один запрос."""

    def __init__(
        self, loan_repo: LoanRepository, salary_repo: SalaryRepository, today: date
    ) -> None:
        self._loans = {
            stored.loan.id: stored
            for stored in loan_repo.list_loans()
            if stored.status != LoanStatus.DELETED
        }
        self.paydays = Paydays(salary_repo)
        self.today = today
        self._base: dict[str, Decimal | None] = {}  # доля выплат от сегодняшнего остатка

    def _first(self, goal: Goal) -> date:
        """С какого дня вносить ЧДП: с завтра (сегодняшнее уже в истории) или со старта цели."""
        first = self.today + DAY
        return max(first, goal.start_date) if goal.start_date else first

    def state(self, goal: Goal, month_start: date) -> LoanGoalState:
        """Прогресс и план ЧДП на месяц."""
        stored = self._loans.get(goal.loan_id or "")
        if stored is None:
            return LoanGoalState(ZERO, ZERO, ZERO)
        loan, done = stored.loan, stored.prepayments
        if month_start <= self.today:
            now = payoff.balance_on(loan, done, self.today)
            before = payoff.balance_on(loan, done, min(self.today, month_start - DAY))
            saved = max(goal.target_amount - now, ZERO)
        else:
            # будущий месяц: до его начала ЧДП внесены по плану — ожидаемый остаток
            planned = [*done, *self._until(goal, stored, month_start)]
            before = payoff.balance_on(loan, planned, month_start)
            saved = max(goal.target_amount - before, ZERO)
        return LoanGoalState(
            saved,
            max(goal.target_amount - before, ZERO),
            self._plan(goal, stored, month_start),
        )

    def _plan(self, goal: Goal, stored: StoredLoan, month_start: date) -> Decimal:
        month = self.paydays.between(max(month_start, self._first(goal)), next_month(month_start))
        if goal.deadline is not None:
            month = [paid for paid in month if paid[0] <= goal.deadline]
        planned = [*stored.prepayments, *self._until(goal, stored, month_start)]
        if not month or payoff.closing_date(stored.loan, planned) < month_start:
            return ZERO.quantize(CENT)  # выплат нет или кредит к этому месяцу уже закрыт
        if goal.deadline is None:
            return goal.monthly_amount or ZERO
        share = self._base_share(goal, stored)
        if not share:
            return ZERO.quantize(CENT)
        return sum((p.amount for p in payoff.by_share(share, _net(month))), ZERO).quantize(CENT)

    def _base_share(self, goal: Goal, stored: StoredLoan) -> Decimal | None:
        """Доля выплат «к дате» от сегодняшнего остатка — одна на запрос."""
        if goal.id not in self._base:
            deadline = goal.deadline or self.today  # зовётся только для «к дате»
            self._base[goal.id] = self._share(
                deadline, stored, stored.prepayments, self._first(goal)
            )
        return self._base[goal.id]

    def _share(
        self,
        deadline: date,
        stored: StoredLoan,
        done: tuple[Prepayment, ...] | list[Prepayment],
        first: date,
    ) -> Decimal | None:
        """Доля выплат с first до срока, чтобы закрыть к сроку."""
        upcoming = _net(self.paydays.between(first, deadline + DAY))
        return payoff.solve_share(stored.loan, done, upcoming, deadline)

    def outcome(self, goal: Goal, month_start: date, real: Decimal) -> LoanGoalOutcome:
        """Реальный взнос месяца → ЧДП по дням; дальше — по режиму цели; дата и экономия."""
        stored = self._loans.get(goal.loan_id or "")
        if stored is None:
            return LoanGoalOutcome([], None, ZERO, "Кредит не найден или удалён")
        end = next_month(month_start)
        this = goal_rules.by_paydays(
            real, self.paydays.between(max(month_start, self._first(goal)), end)
        )
        planned = [
            *stored.prepayments,
            *self._until(goal, stored, month_start),
            *_prepayments(this),
        ]
        later = max(end, self._first(goal))
        if goal.deadline is not None:
            future, note = self._catch_up(goal.deadline, stored, planned, later)
            if note is None and real < self._plan(goal, stored, month_start):
                grown = sum((p.amount for p in future if p.date < next_month(later)), ZERO)
                note = (
                    f"В этом месяце ЧДП меньше плана — недовнесённое разойдётся по следующим;"
                    f" в следующем месяце ЧДП {_rub(grown)}"
                )
        else:
            future, note = self._steady(goal.monthly_amount or ZERO, stored, planned, later), None
        final = [*planned, *future]
        return LoanGoalOutcome(
            this,
            payoff.closing_date(stored.loan, final),
            payoff.interest_total(stored.loan, stored.prepayments)
            - payoff.interest_total(stored.loan, final),
            note,
        )

    def _until(self, goal: Goal, stored: StoredLoan, month_start: date) -> list[Prepayment]:
        """Смотрим будущий месяц: ЧДП по плану с завтра до его начала (их ещё нет в истории)."""
        first = self._first(goal)
        if month_start <= first:
            return []
        if goal.deadline is not None:
            share = self._base_share(goal, stored)
            return payoff.by_share(share or ZERO, _net(self.paydays.between(first, month_start)))
        steady = self._steady(goal.monthly_amount or ZERO, stored, list(stored.prepayments), first)
        return [p for p in steady if p.date < month_start]

    def _catch_up(
        self, deadline: date, stored: StoredLoan, planned: list[Prepayment], later: date
    ) -> tuple[list[Prepayment], str | None]:
        """«К сроку»: со следующего месяца — доля выплат, чтобы всё равно успеть."""
        share = self._share(deadline, stored, planned, later)
        if share is None:
            return [], f"К {deadline:%d.%m.%Y} не успеть даже всеми выплатами — выбери дату позже"
        return payoff.by_share(share, _net(self.paydays.between(later, deadline + DAY))), None

    def _steady(
        self, monthly: Decimal, stored: StoredLoan, planned: list[Prepayment], later: date
    ) -> list[Prepayment]:
        """«Взнос в месяц»: каждый месяц одна сумма ЧДП, по дням выплат — пропорционально."""
        future: list[Prepayment] = []
        stop = payoff.closing_date(stored.loan, planned)
        cursor = later.replace(day=1)
        while monthly > 0 and cursor <= stop:
            paid = self.paydays.between(max(cursor, later), next_month(cursor))
            future += _prepayments(goal_rules.by_paydays(monthly, paid))
            cursor = next_month(cursor)
        return future
