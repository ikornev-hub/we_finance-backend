"""Схемы API кредита: что принимает и что отдаёт HTTP (pydantic).

Типы полей — настоящие (date, Decimal, int); в JSON pydantic сам пишет даты и деньги строками.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from we_finance.credit.models import DayCount


class RatePeriodIn(BaseModel):
    """Период ставки: с этой даты (включительно) действует эта годовая ставка, %."""

    start: date
    annual_rate: Decimal = Field(ge=0)


class LoanIn(BaseModel):
    """Параметры кредита для расчёта графика."""

    principal: Decimal = Field(gt=0)
    rates: list[RatePeriodIn] = Field(min_length=1)
    payment: Decimal = Field(gt=0)
    months: int = Field(ge=1)
    issue_date: date
    first_payment_date: date
    day_count: DayCount = DayCount.ACTUAL
    weekend_shift: bool = True
    monthly_fee: Decimal = Field(default=Decimal("0.00"), ge=0)


class ScheduleRowOut(BaseModel):
    """Строка графика платежей."""

    model_config = ConfigDict(from_attributes=True)

    number: int
    date: date
    payment: Decimal
    principal: Decimal
    interest: Decimal
    balance: Decimal
    fee: Decimal
