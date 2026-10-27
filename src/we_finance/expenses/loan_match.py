"""Перевод без банка → кредит, если совпал с фактом из «Кредитов» (решение 2026-10-27).

В PDF-выписке Альфы «Перевод собственных средств» идёт без названия банка: кредит это или
перевод себе — не видно. Но «Кредиты» знают факты: ЧДП, которые записал пользователь, и платежи
по графику. Совпало по сумме и по дате — это платёж по кредиту:

- ЧДП из истории — та же сумма, ±3 дня;
- платёж по графику — та же сумма, переведён за 20 дней до списания или до 3 дней после
  (деньги на счёт кредита кладут заранее — в день зарплаты);
- платёж + ЧДП одним переводом — сумма обоих.

Каждый факт закрывает одну операцию выписки.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from we_finance.credit.models import LoanStatus, StoredLoan
from we_finance.credit.schedule import calculate
from we_finance.expenses.statement import StatementOperation

AROUND = 3  # дней: банк проводит перевод не в тот же день
AHEAD = 20  # дней: платёж по графику переводят заранее


@dataclass
class _Fact:
    loan: StoredLoan
    day: date
    amount: Decimal
    what: str  # «ЧДП» или «платёж по графику»
    used: bool = False


def _near(fact: _Fact, day: date) -> bool:
    delta = (day - fact.day).days
    if fact.what == "ЧДП":
        return abs(delta) <= AROUND
    return -AHEAD <= delta <= AROUND


@dataclass
class LoanMatcher:
    """Сверка переводов одной выписки с фактами всех кредитов пользователя."""

    loans: Sequence[StoredLoan]
    _facts: list[_Fact] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        for stored in self.loans:
            if stored.status == LoanStatus.DELETED:
                continue
            self._facts += [_Fact(stored, p.date, p.amount, "ЧДП") for p in stored.prepayments]
            rows, _ = calculate(stored.loan, stored.prepayments)
            self._facts += [_Fact(stored, r.date, r.payment, "платёж по графику") for r in rows]

    def match(self, op: StatementOperation) -> tuple[StoredLoan, str] | None:
        """Кредит и почему; найденные факты помечаются использованными."""
        if op.amount >= 0:
            return None
        amount = -op.amount
        free = [fact for fact in self._facts if not fact.used and _near(fact, op.day)]
        single = next((fact for fact in free if fact.amount == amount), None)
        if single:
            single.used = True
            return single.loan, f"совпало: {single.what} {single.day:%d.%m.%Y} в «Кредитах»"
        for payment in (fact for fact in free if fact.what != "ЧДП"):
            extra = next(
                (
                    fact
                    for fact in free
                    if fact.what == "ЧДП"
                    and fact.loan is payment.loan
                    and fact.amount + payment.amount == amount
                ),
                None,
            )
            if extra:
                payment.used = extra.used = True
                return payment.loan, (
                    f"совпало: платёж {payment.day:%d.%m.%Y} + ЧДП {extra.day:%d.%m.%Y}"
                    " в «Кредитах»"
                )
        return None
