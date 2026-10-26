"""Статус денежного события на дату: проведён, сегодня, запланирован (решение 2026-10-26).

Одно правило для платежей по кредиту, ЧДП и выплат зарплаты: событие сегодняшнего дня
ещё не учтено — остаток до него, в «получено» его нет.
"""

from datetime import date
from enum import StrEnum


class PaymentStatus(StrEnum):
    """Где событие относительно as_of."""

    DONE = "done"  # дата раньше as_of: проведён, учтён
    TODAY = "today"  # дата = as_of: ожидается сегодня, ещё не учтён
    PLANNED = "planned"  # дата позже as_of


def payment_status(day: date, as_of: date) -> PaymentStatus:
    """Статус события с датой day на дату as_of."""
    if day < as_of:
        return PaymentStatus.DONE
    if day == as_of:
        return PaymentStatus.TODAY
    return PaymentStatus.PLANNED
