"""Год зарплаты: выплаты по датам с НДФЛ и итоги по месяцам."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from we_finance.salary.models import Absence, MonthTotal, Payment, PaymentKind, SalaryTerms
from we_finance.salary.payroll import advance_date, remainder_date, split_salary
from we_finance.salary.tax import withhold


def salary_payments(
    year: int, terms: Sequence[SalaryTerms], absences: Sequence[Absence]
) -> list[Payment]:
    """Аванс и остаток за каждый месяц года"""
    payments = []
    for month in range(1, 13):
        advance, remainder = split_salary(year, month, terms, absences)
        payments.append(Payment(advance_date(year, month), PaymentKind.ADVANCE, month, advance))
        payments.append(
            Payment(remainder_date(year, month), PaymentKind.REMAINDER, month, remainder)
        )
    return payments


def with_tax(payments: Sequence[Payment]) -> list[Payment]:
    """Выплаты по датам, у каждой - НДФЛ нарастающим итогом"""
    ordered = sorted(payments, key=lambda p: (p.date, p.kind))
    taxes = withhold([p.gross for p in ordered])
    return [replace(p, tax=t) for p, t in zip(ordered, taxes, strict=True)]


def month_totals(payments: Sequence[Payment]) -> list[MonthTotal]:
    """Начислено, удержано и на руки за каждый месяц года"""
    totals = []
    for month in range(1, 13):
        of_month = [p for p in payments if p.for_month == month]
        gross = sum((p.gross for p in of_month), Decimal("0"))
        tax = sum((p.tax for p in of_month), Decimal("0"))
        totals.append(MonthTotal(month, gross, tax))
    return totals


def year_report(
    year: int, terms: Sequence[SalaryTerms], absences: Sequence[Absence]
) -> list[Payment]:
    """Все выплаты года по датам, у каждой — НДФЛ и сумма на руки."""
    accrual_without_tax = salary_payments(year, terms, absences)
    accrual_with_tax = with_tax(accrual_without_tax)
    return accrual_with_tax
