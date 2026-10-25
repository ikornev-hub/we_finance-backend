"""Год зарплаты: выплаты по датам с НДФЛ и итоги по месяцам."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal

from we_finance.salary.models import (
    Absence,
    AbsenceKind,
    HistoryMonth,
    MonthTotal,
    Payment,
    PaymentKind,
    SalaryTerms,
)
from we_finance.salary.payroll import advance_date, remainder_date, split_salary
from we_finance.salary.sick import sick_pay
from we_finance.salary.tax import withhold
from we_finance.salary.vacation import month_history, vacation_pay, vacation_pay_date
from we_finance.salary.workdays import add_business_days


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
    year: int,
    terms: Sequence[SalaryTerms],
    absences: Sequence[Absence],
    history: Sequence[HistoryMonth],
    stage_start: date,
) -> list[Payment]:
    """Все выплаты года по датам, у каждой — НДФЛ и сумма на руки."""
    payments = salary_payments(year, terms, absences)
    computed = [month_history(year, m, terms, absences) for m in range(1, 13)]
    full_history = [*history, *computed]

    salary_dates = [p.date for p in payments]

    for absence in absences:
        if absence.start.year != year:
            continue
        if absence.kind == AbsenceKind.VACATION:
            payments.append(
                Payment(
                    vacation_pay_date(absence),
                    PaymentKind.VACATION,
                    absence.start.month,
                    vacation_pay(full_history, absence),
                )
            )
        if absence.kind == AbsenceKind.SICK:
            pay = sick_pay(full_history, absence, stage_start)
            employer_date = min(d for d in salary_dates if d > absence.end)
            fund_date = add_business_days(absence.end, 10)
            payments.append(
                Payment(employer_date, PaymentKind.SICK_EMPLOYER, absence.start.month, pay.employer)
            )
            payments.append(
                Payment(fund_date, PaymentKind.SICK_FUND, absence.start.month, pay.fund)
            )
    return with_tax(payments)
