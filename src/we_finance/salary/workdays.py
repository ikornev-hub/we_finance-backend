import calendar
from datetime import date, timedelta

from we_finance.credit.calendar_ru import is_business_day


def month_end(year: int, month: int) -> date:
    """Узнать последний день месяца"""
    return date(year, month, calendar.monthrange(year, month)[1])


def business_days(start: date, end: date) -> list[date]:
    """Рабочие дни от start до end включительно, по порядку"""
    working_day = []
    while start <= end:
        if is_business_day(start):
            working_day.append(start)
        start += timedelta(days=1)
    return working_day


def previous_business_day(day: date) -> date:
    """Тот же день, если рабочий; иначе ближайший предыдущий рабочий"""
    result = day
    while not is_business_day(result):
        result -= timedelta(days=1)
    return result
