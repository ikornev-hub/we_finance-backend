"""Калькулятор кредита: считает по присланным параметрам, ничего не сохраняет."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends

from we_finance.credit import service
from we_finance.credit.schemas import CalculationIn, CalculationOut, LoanIn, ScheduleRowOut
from we_finance.routers.deps import get_today

router = APIRouter(prefix="/calculator", tags=["calculator"])


@router.post(
    "/schedule",
    summary="Calculate payment schedule",
    description="Строит график платежей по параметрам кредита без ЧДП. Ничего не сохраняет.",
)
def calculate_schedule(loan: LoanIn) -> list[ScheduleRowOut]:
    """График платежей по параметрам кредита."""
    rows = service.schedule_rows(service.to_loan(loan))
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
    loan = service.to_loan(request.loan)
    prepayments = [service.to_prepayment(p) for p in request.prepayments]
    return service.build_calculation(loan, prepayments, request.as_of or today)
