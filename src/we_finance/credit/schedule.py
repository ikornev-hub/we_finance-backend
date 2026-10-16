import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from we_finance.credit.calendar_ru import is_business_day
from we_finance.credit.models import (
    DayCount,
    Loan,
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


def payment_dates(first_payment_date: date, months: int, weekend_shift: bool) -> list[date]:
    """Даты всех платежей: k-я — от первой даты (не от предыдущей); перенос на рабочий день."""
    if weekend_shift:
        dates = [
            next_business_day(add_months(first_payment_date, offset)) for offset in range(months)
        ]
    else:
        dates = [add_months(first_payment_date, offset) for offset in range(months)]
    return dates


@dataclass
class _Plan:
    """Изменяемое состояние графика между платежами: что меняют ЧДП."""

    balance: Decimal  # остаток основного долга
    payment: Decimal  # текущий стандартный платёж (меняется при «уменьшить платёж»)
    last_number: int | None  # номер последнего платежа; None — закроется сам («сократить срок»)


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

    plan.balance -= min(prepayment.amount, plan.balance)
    if plan.balance == 0:
        return

    if prepayment.mode == PrepaymentMode.REDUCE_PAYMENT:
        remaining = plan.last_number - number
        rate = rate_on(loan.rates, prepayment.date)
        plan.payment = annuity_payment(plan.balance, rate, remaining) + loan.monthly_fee
    else:
        plan.last_number = None


def build_schedule(loan: Loan, prepayments: Sequence[Prepayment] = ()) -> list[ScheduleRow]:
    """График платежей от выдачи до закрытия с учётом ЧДП (требования 2.4, 2.6).

    Платёж банка включает комиссию: платёж = в долг + проценты + комиссия.
    Последний платёж (по сроку или раньше, если долг уже помещается в платёж) закрывает остаток.
    ЧДП в дату платежа применяется после обычного платежа.
    """
    dates = payment_dates(loan.first_payment_date, loan.months, loan.weekend_shift)
    rows: list[ScheduleRow] = []
    plan = _Plan(balance=loan.principal, payment=loan.payment, last_number=loan.months)
    previous_date = loan.issue_date
    accrued_total = Decimal("0")
    interest_paid = Decimal("0")

    for number, pay_date in enumerate(dates, start=1):
        accrued_total += interest_for_period(
            plan.balance, loan.rates, previous_date, pay_date, loan.day_count
        )
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
        for prepayment in prepayments:
            if prepayment.date == pay_date:
                _apply_prepayment(loan, plan, prepayment, number, dates[number:])
        if plan.balance == 0:
            break
        previous_date = pay_date

    return rows
