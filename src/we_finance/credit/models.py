from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class DayCount(StrEnum):
    """Способ подсчёта дней в году — «тариф банка»: фактический (365/366) или всегда 365."""

    ACTUAL = "actual"
    DAYS_365 = "365"


class PrepaymentMode(StrEnum):
    """Режим ЧДП: сократить срок или уменьшить платёж."""

    REDUCE_TERM = "reduce_term"
    REDUCE_PAYMENT = "reduce_payment"


@dataclass(frozen=True)
class RatePeriod:
    """Дата процентного периода"""

    start: date
    annual_rate: Decimal


@dataclass(frozen=True)
class Loan:  # pylint: disable=too-many-instance-attributes  # 11 параметров договора
    """Стартовые данные кредита (хранимое)."""

    id: str
    name: str
    principal: Decimal
    rates: tuple[RatePeriod, ...]
    payment: Decimal
    months: int
    issue_date: date
    first_payment_date: date
    day_count: DayCount = DayCount.ACTUAL
    weekend_shift: bool = True
    monthly_fee: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class ScheduleRow:
    """Строка графика платежей"""

    number: int
    date: date
    payment: Decimal
    principal: Decimal
    interest: Decimal
    balance: Decimal
    fee: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class Prepayment:
    """ЧДП: дата, сумма, режим"""

    date: date
    amount: Decimal
    mode: PrepaymentMode
