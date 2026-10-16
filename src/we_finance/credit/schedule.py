import calendar
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from we_finance.credit.calendar_ru import is_business_day
from we_finance.credit.models import (
    DayCount,
    EntryKind,
    HistoryEntry,
    Loan,
    PaymentDayChange,
    Prepayment,
    PrepaymentMode,
    RatePeriod,
    ScheduleRow,
)

CENT = Decimal("0.01")


def rate_on(rates: Sequence[RatePeriod], day: date) -> Decimal:
    """Годовая ставка, действующая в этот день."""
    if not rates:
        raise ValueError("Нет ни одного периода ставки")

    found = None
    for period in rates:
        if period.start <= day:
            found = period.annual_rate

    if found is None:
        raise ValueError(f"Нет ставки на {day}: первый период начинается {rates[0].start}")
    return found


def days_in_year(day: date, day_count: DayCount) -> int:
    """365 или 366 - по способу подсчета дней."""

    return 366 if (calendar.isleap(year=day.year) and day_count == DayCount.ACTUAL) else 365


def interest_for_period(
    balance: Decimal, rates: Sequence[RatePeriod], start: date, end: date, day_count: DayCount
) -> Decimal:
    """Проценты за дни после start по end включительно."""
    total = Decimal("0")
    day = start + timedelta(days=1)

    while day <= end:
        total += balance * rate_on(rates, day) / 100 / days_in_year(day, day_count)
        day += timedelta(days=1)

    return total


def annuity_payment(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """Платёж по формуле (З10, 1.1): для учебного примера и ЧДП «уменьшение платежа»."""
    total = Decimal("0")
    if annual_rate == 0:
        total = principal / months
    else:
        monthly_rate = annual_rate / 100 / 12
        total = (principal * monthly_rate) / (1 - (1 + monthly_rate) ** -months)
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(start: date, months: int) -> date:
    """Дата через months месяцев; если такого числа нет - последний день месяца."""
    total = start.year * 12 + (start.month - 1) + months
    year, month_zero = divmod(total, 12)
    month = month_zero + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def next_business_day(day: date) -> date:
    """Тот же день, если рабочий; иначе ближайший следующий рабочий (календарь calendar_ru)."""
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def with_payment_day(nominal: date, changes: Sequence[PaymentDayChange]) -> date:
    """Номинальная дата с днём платежа из последней действующей смены (если день есть в месяце)."""
    day = None
    for change in changes:
        if change.start <= nominal:
            day = change.day
    if day is None:
        return nominal
    last_day = calendar.monthrange(nominal.year, nominal.month)[1]
    return nominal.replace(day=min(day, last_day))


def payment_dates(
    first_payment_date: date,
    months: int,
    weekend_shift: bool,
    day_changes: Sequence[PaymentDayChange] = (),
) -> list[date]:
    """Даты всех платежей (требования 2.1).

    k-я дата — от первой даты (не от предыдущей), затем день из смены дня платежа,
    затем перенос на рабочий день, если weekend_shift.
    """
    dates = []
    for offset in range(months):
        nominal = with_payment_day(add_months(first_payment_date, offset), day_changes)
        dates.append(next_business_day(nominal) if weekend_shift else nominal)
    return dates


@dataclass
class _Plan:
    """Изменяемое состояние графика между платежами: что меняют ЧДП."""

    balance: Decimal  # остаток основного долга
    payment: Decimal  # текущий стандартный платёж (меняется при «уменьшить платёж»)
    last_number: int | None  # номер последнего платежа; None — закроется сам («сократить срок»)
    applied: list[HistoryEntry] = field(default_factory=list)  # применённые ЧДП


def remaining_payments(
    loan: Loan, balance: Decimal, payment: Decimal, start: date, future_dates: Sequence[date]
) -> int:
    """Сколько платежей нужно, чтобы погасить balance платежом payment, начиная после start."""
    count = 0
    previous_date = start
    for pay_date in future_dates:
        count += 1
        interest = interest_for_period(balance, loan.rates, previous_date, pay_date, loan.day_count)
        if balance + interest + loan.monthly_fee <= payment:
            break
        balance -= payment - interest - loan.monthly_fee
        previous_date = pay_date
    return count


def _apply_prepayment(
    loan: Loan, plan: _Plan, prepayment: Prepayment, number: int, future_dates: Sequence[date]
) -> None:
    """ЧДП после платежа номер number: уменьшает остаток и пересчитывает план (требования 2.6)."""
    if prepayment.mode == PrepaymentMode.REDUCE_PAYMENT and plan.last_number is None:
        # после «сократить срок» план неизвестен: считаем его ДО вычета этого ЧДП
        plan.last_number = number + remaining_payments(
            loan, plan.balance, plan.payment, prepayment.date, future_dates
        )

    amount = min(prepayment.amount, plan.balance)
    plan.balance -= amount
    plan.applied.append(
        HistoryEntry(
            date=prepayment.date,
            kind=EntryKind.PREPAYMENT,
            amount=amount,
            principal=amount,
            interest=Decimal("0.00"),
            fee=Decimal("0.00"),
            balance=plan.balance,
        )
    )
    if plan.balance == 0:
        return

    if prepayment.mode == PrepaymentMode.REDUCE_PAYMENT:
        remaining = plan.last_number - number
        rate = rate_on(loan.rates, prepayment.date)
        plan.payment = annuity_payment(plan.balance, rate, remaining) + loan.monthly_fee
    else:
        plan.last_number = None


def _accrue_period(
    loan: Loan,
    plan: _Plan,
    prepayments: Sequence[Prepayment],
    dates: Sequence[date],
    number: int,
) -> Decimal:
    """Неокруглённые проценты за период перед платежом number (требования 2.3, 2.6).

    ЧДП, попавшие внутрь периода, применяются по ходу: до даты ЧДП проценты идут
    на старый остаток, после — на новый. prepayments должны быть отсортированы по дате.
    """
    start = loan.issue_date if number == 1 else dates[number - 2]
    end = dates[number - 1]
    total = Decimal("0")
    for prepayment in prepayments:
        if start < prepayment.date < end:
            total += interest_for_period(
                plan.balance, loan.rates, start, prepayment.date, loan.day_count
            )
            # ЧДП между платежами number-1 и number: ближайший платёж — уже по новому плану
            _apply_prepayment(loan, plan, prepayment, number - 1, dates[number - 1 :])
            start = prepayment.date
    return total + interest_for_period(plan.balance, loan.rates, start, end, loan.day_count)


def build_schedule(loan: Loan, prepayments: Sequence[Prepayment] = ()) -> list[ScheduleRow]:
    """График платежей от выдачи до закрытия с учётом ЧДП (требования 2.4, 2.6)."""
    rows, _ = calculate(loan, prepayments)
    return rows


def calculate(
    loan: Loan, prepayments: Sequence[Prepayment] = ()
) -> tuple[list[ScheduleRow], list[HistoryEntry]]:
    """График и применённые ЧДП (требования 2.4, 2.6).

    Платёж банка включает комиссию: платёж = в долг + проценты + комиссия.
    Последний платёж (по сроку или раньше, если долг уже помещается в платёж) закрывает остаток.
    ЧДП в дату платежа применяется после обычного платежа, ЧДП между датами — внутри периода.
    """
    dates = payment_dates(
        loan.first_payment_date, loan.months, loan.weekend_shift, loan.payment_day_changes
    )
    rows: list[ScheduleRow] = []
    plan = _Plan(balance=loan.principal, payment=loan.payment, last_number=loan.months)
    ordered = sorted(prepayments, key=lambda prepayment: prepayment.date)
    accrued_total = Decimal("0")
    interest_paid = Decimal("0")

    for number, pay_date in enumerate(dates, start=1):
        accrued_total += _accrue_period(loan, plan, ordered, dates, number)
        interest = accrued_total.quantize(CENT, rounding=ROUND_HALF_UP) - interest_paid
        interest_paid += interest
        closing = plan.balance + interest + loan.monthly_fee

        if number == plan.last_number or closing <= plan.payment:
            payment = closing
        else:
            payment = plan.payment

        principal_part = payment - interest - loan.monthly_fee
        plan.balance -= principal_part
        rows.append(
            ScheduleRow(
                number=number,
                date=pay_date,
                payment=payment,
                principal=principal_part,
                interest=interest,
                balance=plan.balance,
                fee=loan.monthly_fee,
            )
        )
        for prepayment in ordered:
            if prepayment.date == pay_date:
                _apply_prepayment(loan, plan, prepayment, number, dates[number:])
        if plan.balance == 0:
            break

    return rows, plan.applied
