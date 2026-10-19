"""Зарплата: расчёт выплат за год по присланному профилю (требования, З3–З5)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends

from we_finance.routers.deps import get_today
from we_finance.salary import service
from we_finance.salary.schemas import SalaryCalculationIn, YearReportOut

router = APIRouter(prefix="/salary", tags=["salary"])

Today = Annotated[date, Depends(get_today)]


@router.post(
    "/calculate",
    summary="Salary payments for a year",
    description=(
        "Выплаты за год по присланному профилю: аванс, остаток, отпускные, больничный, "
        "НДФЛ, итоги по месяцам и за год. received — выплата пришла к дате as_of "
        "(по умолчанию сегодня). Ничего не сохраняет."
    ),
)
def calculate(
    request: SalaryCalculationIn, today: Today, as_of: date | None = None
) -> YearReportOut:
    """Расчёт зарплаты за год."""
    return service.calculate(request, as_of or today)
