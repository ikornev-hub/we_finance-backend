"""Состояние кредита на дату и история платежей (требования 2.7–2.9)."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal

from we_finance.credit.models import (
    EntryKind,
    HistoryEntry,
    Loan,
    LoanOverview,
    LoanState,
    Prepayment,
    ScheduleRow,
)
from we_finance.credit.schedule import calculate


def _regular_entry(row: ScheduleRow) -> HistoryEntry:
    """Строка графика как запись истории."""
    return HistoryEntry(
        date=row.date,
        kind=EntryKind.REGULAR,
        amount=row.payment,
        principal=row.principal,
        interest=row.interest,
        fee=row.fee,
        balance=row.balance,
    )


def history_from(
    rows: Sequence[ScheduleRow], applied: Sequence[HistoryEntry], as_of: date
) -> list[HistoryEntry]:
    """Записи с датой не позже as_of (сегодняшние — со статусом «сегодня»).

    В один день — сначала обычный платёж, потом ЧДП.
    """
    entries = [_regular_entry(row) for row in rows if row.date <= as_of]
    entries += [entry for entry in applied if entry.date <= as_of]
    kind_order = {EntryKind.REGULAR: 0, EntryKind.PREPAYMENT: 1}
    return sorted(entries, key=lambda entry: (entry.date, kind_order[entry.kind]))


def _done(
    rows: Sequence[ScheduleRow], applied: Sequence[HistoryEntry], as_of: date
) -> list[HistoryEntry]:
    """Проведённые: дата строго раньше as_of. Сегодняшние ещё не учтены (решение 2026-10-26)."""
    return [entry for entry in history_from(rows, applied, as_of) if entry.date < as_of]


def state_from(
    loan: Loan, rows: Sequence[ScheduleRow], applied: Sequence[HistoryEntry], as_of: date
) -> LoanState:
    """Состояние на as_of по уже рассчитанному графику."""
    past = _done(rows, applied, as_of)
    future = [row for row in rows if row.date >= as_of]
    return LoanState(
        as_of=as_of,
        balance=past[-1].balance if past else loan.principal,
        next_payment=future[0] if future else None,
        close_date=rows[-1].date,
        last_payment=rows[-1].payment,
        payments_left=len(future),
    )


def payment_history(
    loan: Loan, prepayments: Sequence[Prepayment], as_of: date
) -> list[HistoryEntry]:
    """История платежей на дату (сценарий С5)."""
    rows, applied = calculate(loan, prepayments)
    return history_from(rows, applied, as_of)


def loan_overview(loan: Loan, prepayments: Sequence[Prepayment], as_of: date) -> LoanOverview:
    """Стартовое и актуальное состояние, итоги ЧДП (сценарий С3).

    Стартовое — договор как при выдаче (без смен дня платежа и ЧДП).
    Экономия — против графика с теми же условиями, но без ЧДП: эффект ЧДП, а не смены дня.
    """
    contract_rows, _ = calculate(replace(loan, payment_day_changes=()))
    no_prepayment_rows, _ = calculate(loan)
    rows, applied = calculate(loan, prepayments)
    return LoanOverview(
        start=state_from(loan, contract_rows, [], loan.issue_date),
        actual=state_from(loan, rows, applied, as_of),
        prepaid_total=sum((entry.amount for entry in applied if entry.date < as_of), Decimal("0")),
        interest_saved=sum(row.interest for row in no_prepayment_rows)
        - sum(row.interest for row in rows),
        months_saved=len(no_prepayment_rows) - len(rows),
    )
