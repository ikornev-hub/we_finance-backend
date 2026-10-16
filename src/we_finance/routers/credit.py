"""Эндпоинты кредита: калькулятор (ничего не сохраняет)."""

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from we_finance.credit.models import (
    HistoryEntry,
    Loan,
    PaymentDayChange,
    Prepayment,
    RatePeriod,
    ScheduleRow,
)
from we_finance.credit.schedule import build_schedule, calculate
from we_finance.credit.schemas import (
    CalculationIn,
    CalculationOut,
    HistoryEntryOut,
    LoanIn,
    LoanStateOut,
    ScheduleItemOut,
    ScheduleRowOut,
    WarningOut,
)
from we_finance.credit.state import history_from, loan_overview

router = APIRouter(prefix="/credit", tags=["credit"])


def get_today() -> date:
    """Сегодня. Отдельная зависимость, чтобы тесты могли подставить свою дату."""
    return date.today()


def _to_loan(loan_in: LoanIn) -> Loan:
    """Параметры из запроса → кредит ядра. id и name — заглушки: калькулятор не сохраняет."""
    return Loan(
        id="preview",
        name="preview",
        principal=loan_in.principal,
        rates=tuple(RatePeriod(r.start, r.annual_rate) for r in loan_in.rates),
        payment=loan_in.payment,
        months=loan_in.months,
        issue_date=loan_in.issue_date,
        first_payment_date=loan_in.first_payment_date,
        day_count=loan_in.day_count,
        weekend_shift=loan_in.weekend_shift,
        monthly_fee=loan_in.monthly_fee,
        payment_day_changes=tuple(
            PaymentDayChange(c.start, c.day) for c in loan_in.payment_day_changes
        ),
    )


def _unused_prepayment(
    prepayments: list[Prepayment], applied: list[HistoryEntry], rows: list[ScheduleRow]
) -> Decimal:
    """Сколько из внесённых ЧДП не понадобилось: сверх долга, процентов и комиссии на дату."""
    used = sum((entry.amount for entry in applied), Decimal("0"))
    closed_by_prepayment = applied and applied[-1].balance == 0
    if closed_by_prepayment and rows[-1].date == applied[-1].date:
        used += rows[-1].interest + rows[-1].fee  # погашение в тот же день покрыло проценты
    return sum((p.amount for p in prepayments), Decimal("0")) - used


@router.post(
    "/schedule",
    summary="Calculate payment schedule",
    description="Строит график платежей по параметрам кредита без ЧДП. Ничего не сохраняет.",
)
def calculate_schedule(loan: LoanIn) -> list[ScheduleRowOut]:
    """График платежей по параметрам кредита."""
    rows = build_schedule(_to_loan(loan))
    return [ScheduleRowOut.model_validate(row) for row in rows]


@router.post(
    "/calculate",
    summary="Calculate loan with prepayments",
    description=(
        "Стартовые и актуальные данные, итоги ЧДП, график с признаком «прошёл» и история "
        "платежей с типами (обычный / ЧДП). as_of — дата, на которую показать состояние "
        "(по умолчанию сегодня). Ничего не сохраняет."
    ),
)
def calculate_loan(
    request: CalculationIn, today: Annotated[date, Depends(get_today)]
) -> CalculationOut:
    """Полный расчёт кредита с ЧДП (сценарии С3–С6)."""
    loan = _to_loan(request.loan)
    prepayments = [Prepayment(p.date, p.amount, p.mode) for p in request.prepayments]
    as_of = request.as_of or today

    rows, applied = calculate(loan, prepayments)
    late = [p for p in prepayments if p.date > rows[-1].date]
    if late:
        raise HTTPException(
            status_code=422,
            detail=f"ЧДП {late[0].date} позже закрытия кредита {rows[-1].date}",
        )

    overview = loan_overview(loan, prepayments, as_of)
    excess = _unused_prepayment(prepayments, applied, rows)
    warnings = []
    if excess > 0:
        warnings.append(
            WarningOut(
                code="amount_exceeds_balance",
                message=f"ЧДП больше остатка долга: {excess} не учтено, кредит закрыт",
            )
        )

    return CalculationOut(
        start=LoanStateOut.model_validate(overview.start),
        actual=LoanStateOut.model_validate(overview.actual),
        prepaid_total=overview.prepaid_total,
        interest_saved=overview.interest_saved,
        months_saved=overview.months_saved,
        schedule=[ScheduleItemOut(**asdict(row), past=row.date <= as_of) for row in rows],
        history=[HistoryEntryOut.model_validate(e) for e in history_from(rows, applied, as_of)],
        warnings=warnings,
    )
