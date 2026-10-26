from dataclasses import dataclass
from datetime import date, datetime
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
class PaymentDayChange:
    """Смена дня платежа по заявлению: платежи с номинальной датой не раньше start — в день day."""

    start: date
    day: int


@dataclass(frozen=True)
class Loan:  # pylint: disable=too-many-instance-attributes  # параметры договора и его изменения
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
    payment_day_changes: tuple[PaymentDayChange, ...] = ()


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


class LoanStatus(StrEnum):
    """Состояние кредита (сценарий С8)."""

    ACTIVE = "active"
    COMPLETED = "completed"
    DELETED = "deleted"


@dataclass(frozen=True)
class StatusChange:
    """Переход в состояние: какое и когда."""

    status: LoanStatus
    changed_at: datetime


@dataclass(frozen=True)
class StoredLoan:
    """Что хранится: кредит, его ЧДП и переходы состояния (события). Всё остальное вычисляется."""

    loan: Loan
    prepayments: tuple[Prepayment, ...] = ()
    status_history: tuple[StatusChange, ...] = ()

    @property
    def status(self) -> LoanStatus:
        """Текущее состояние — последний переход; переходов не было — активный."""
        return self.status_history[-1].status if self.status_history else LoanStatus.ACTIVE


class EntryKind(StrEnum):
    """Тип записи в истории платежей."""

    REGULAR = "regular"
    PREPAYMENT = "prepayment"


@dataclass(frozen=True)
class HistoryEntry:
    """Запись истории: обычный платёж или ЧДП (требования 2.8)."""

    date: date
    kind: EntryKind
    amount: Decimal  # сколько списано
    principal: Decimal  # из них в основной долг
    interest: Decimal  # из них проценты (у ЧДП — 0)
    fee: Decimal  # из них комиссия (у ЧДП — 0)
    balance: Decimal  # остаток долга после записи


@dataclass(frozen=True)
class LoanState:
    """Состояние кредита на дату (требования 2.7)."""

    as_of: date
    balance: Decimal
    next_payment: ScheduleRow | None  # None — кредит закрыт
    close_date: date
    last_payment: Decimal
    payments_left: int


@dataclass(frozen=True)
class LoanOverview:
    """Стартовое и актуальное состояние плюс итоги ЧДП (сценарий С3, требования 2.9)."""

    start: LoanState
    actual: LoanState
    prepaid_total: Decimal
    interest_saved: Decimal
    months_saved: int
