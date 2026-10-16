"""Эндпоинты кредита."""

from fastapi import APIRouter

from we_finance.credit.models import Loan, RatePeriod
from we_finance.credit.schedule import build_schedule
from we_finance.credit.schemas import LoanIn, ScheduleRowOut

router = APIRouter(prefix="/credit", tags=["credit"])


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
    )


@router.post(
    "/schedule",
    summary="Calculate payment schedule",
    description="Строит график платежей по параметрам кредита. Ничего не сохраняет.",
)
def calculate_schedule(loan: LoanIn) -> list[ScheduleRowOut]:
    """График платежей по параметрам кредита."""
    rows = build_schedule(_to_loan(loan))
    return [ScheduleRowOut.model_validate(row) for row in rows]
