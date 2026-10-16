"""Схемы API кредита: что принимает и что отдаёт HTTP (pydantic).

Типы полей — настоящие (date, Decimal, int); в JSON pydantic сам пишет даты и деньги строками.
Проверки одного поля — через Field; проверки, связывающие несколько полей, — model_validator.
"""

from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from we_finance.credit.models import DayCount, EntryKind, PrepaymentMode

# ---------- запрос ----------


class RatePeriodIn(BaseModel):
    """Период ставки: с этой даты (включительно) действует эта годовая ставка, %."""

    start: date
    annual_rate: Decimal = Field(ge=0)


class PaymentDayChangeIn(BaseModel):
    """Смена дня платежа: платежи с номинальной датой не раньше start — в день day."""

    start: date
    day: int = Field(ge=1, le=31)


class PrepaymentIn(BaseModel):
    """ЧДП: дата, сумма, режим."""

    date: date
    amount: Decimal = Field(gt=0, decimal_places=2)
    mode: PrepaymentMode


class LoanIn(BaseModel):
    """Параметры кредита для расчёта графика (требования 2.10)."""

    principal: Decimal = Field(gt=0, decimal_places=2)
    rates: list[RatePeriodIn] = Field(min_length=1)
    payment: Decimal = Field(gt=0, decimal_places=2)
    months: int = Field(ge=1)
    issue_date: date
    first_payment_date: date
    day_count: DayCount = DayCount.ACTUAL
    weekend_shift: bool = True
    monthly_fee: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    payment_day_changes: list[PaymentDayChangeIn] = []

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        """Проверки, в которых участвуют несколько полей сразу."""
        if self.rates[0].start != self.issue_date:
            raise ValueError(
                f"Первый период ставки должен начинаться в дату выдачи {self.issue_date}, "
                f"а начинается {self.rates[0].start}"
            )
        _check_increasing([rate.start for rate in self.rates], "периоды ставки")
        _check_increasing([change.start for change in self.payment_day_changes], "смены дня")
        if self.first_payment_date <= self.issue_date:
            raise ValueError("Дата первого платежа должна быть позже даты выдачи")
        return self


class CalculationIn(BaseModel):
    """Кредит, ЧДП и дата, на которую показать состояние (по умолчанию — сегодня)."""

    loan: LoanIn
    prepayments: list[PrepaymentIn] = []
    as_of: date | None = None

    @model_validator(mode="after")
    def check_prepayments(self) -> Self:
        """ЧДП не раньше дня после выдачи."""
        for prepayment in self.prepayments:
            if prepayment.date <= self.loan.issue_date:
                raise ValueError(
                    f"ЧДП {prepayment.date} должен быть позже даты выдачи {self.loan.issue_date}"
                )
        return self


def _check_increasing(dates: list[date], what: str) -> None:
    """Даты строго по возрастанию — иначе непонятно, какое правило действует."""
    for earlier, later in pairwise(dates):
        if later <= earlier:
            raise ValueError(f"{what}: даты должны строго возрастать ({earlier} → {later})")


# ---------- ответ ----------


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


class ScheduleItemOut(ScheduleRowOut):
    """Строка графика с признаком «уже прошёл» относительно as_of (сценарий С4)."""

    past: bool


class HistoryEntryOut(BaseModel):
    """Запись истории: обычный платёж или ЧДП (сценарий С5)."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    kind: EntryKind
    amount: Decimal
    principal: Decimal
    interest: Decimal
    fee: Decimal
    balance: Decimal


class LoanStateOut(BaseModel):
    """Состояние кредита на дату."""

    model_config = ConfigDict(from_attributes=True)

    as_of: date
    balance: Decimal
    next_payment: ScheduleRowOut | None
    close_date: date
    last_payment: Decimal
    payments_left: int


class WarningOut(BaseModel):
    """Предупреждение: ввод принят, но на что-то стоит обратить внимание."""

    code: str
    message: str


class CalculationOut(BaseModel):
    """Всё о кредите: стартовое и актуальное, итоги ЧДП, график, история (сценарии С3–С6)."""

    start: LoanStateOut
    actual: LoanStateOut
    prepaid_total: Decimal
    interest_saved: Decimal
    months_saved: int
    schedule: list[ScheduleItemOut]
    history: list[HistoryEntryOut]
    warnings: list[WarningOut]


# ---------- ресурсы /loans ----------


class LoanCreateIn(LoanIn):
    """Новый кредит: параметры договора и название (сценарий С1)."""

    name: str = Field(min_length=1, max_length=100)


class LoanSummaryOut(BaseModel):
    """Кредит в списке (сценарий С2)."""

    id: str
    name: str
    principal: Decimal
    balance: Decimal
    close_date: date


class LoanDetailOut(CalculationOut):
    """Кредит целиком: id, название и всё, что считает калькулятор (сценарии С3–С5, С7)."""

    id: str
    name: str


class PreviewOut(BaseModel):
    """Прогноз ЧДП: было и стало (сценарий С6). Ничего не сохраняется."""

    before: LoanStateOut
    after: LoanStateOut
    interest_saved: Decimal  # экономия именно этого ЧДП
    months_saved: int
    warnings: list[WarningOut]
