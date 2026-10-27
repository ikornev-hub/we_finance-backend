"""Сверка выплат «Доходов» с поступлениями по выписке (system/expenses.md §2.5)."""

import datetime as dt
from decimal import Decimal

from we_finance.expenses.income_check import CheckStatus, ExpectedPayment, Receipt, check_income

TODAY = dt.date(2026, 10, 27)
PERIODS = [(dt.date(2026, 9, 1), dt.date(2026, 9, 30))]


def _by_kind(checks):
    return {check.kind: check for check in checks}


def _only(payments, receipts):
    """Сверка ровно одной выплаты."""
    checks = check_income(payments, receipts, PERIODS, TODAY)
    assert len(checks) == 1
    return checks[0]


def test_vacation_takes_vacation_receipt_not_closer_transfer():
    """#51: отпускные берут «ОТПУСКНЫЕ» на день раньше, а не перевод по СБП в тот же день."""
    payments = [ExpectedPayment(dt.date(2026, 9, 11), "vacation", Decimal("108086.40"))]
    receipts = [
        Receipt(
            dt.date(2026, 9, 10), Decimal("115458.60"), "ОТПУСКНЫЕ. Основание 77131404691009268M10"
        ),
        Receipt(
            dt.date(2026, 9, 11),
            Decimal("32000.00"),
            "Категория: Перевод по СБП.Перевод C171109262864128",
        ),
    ]
    check = _only(payments, receipts)
    assert check.operation_amount == Decimal("115458.60")
    assert check.difference == Decimal("7372.20")


def test_remainder_does_not_take_advance_receipt():
    """«АВАНС ПО ЗАРАБОТНОЙ ПЛАТЕ» — аванс: остаток его не берёт, даже если сумма ближе."""
    payments = [
        ExpectedPayment(dt.date(2026, 9, 10), "remainder", Decimal("105000.00")),
        ExpectedPayment(dt.date(2026, 9, 10), "advance", Decimal("150000.00")),
    ]
    receipts = [
        Receipt(
            dt.date(2026, 9, 10),
            Decimal("105006.86"),
            "АВАНС ПО ЗАРАБОТНОЙ ПЛАТЕ. Основание 7713140469250",
        ),
        Receipt(
            dt.date(2026, 9, 10),
            Decimal("148626.48"),
            "ЗАРАБОТНАЯ ПЛАТА. Основание 77131404691009268M2O",
        ),
    ]
    checks = _by_kind(check_income(payments, receipts, PERIODS, TODAY))
    assert checks["remainder"].operation_amount == Decimal("148626.48")
    assert checks["advance"].operation_amount == Decimal("105006.86")


def test_sick_takes_benefit_receipt():
    """Больничный узнаётся по «ПОСОБИЕ»; зарплата в тот же день ему не достаётся."""
    payments = [ExpectedPayment(dt.date(2026, 9, 12), "sick_fund", Decimal("10445.32"))]
    receipts = [
        Receipt(dt.date(2026, 9, 12), Decimal("10445.00"), "ЗАРАБОТНАЯ ПЛАТА. Основание 1"),
        Receipt(
            dt.date(2026, 9, 13), Decimal("10445.32"), "ПОСОБИЕ ПО ВРЕМЕННОЙ НЕТРУДОСПОСОБНОСТИ"
        ),
    ]
    check = _only(payments, receipts)
    assert check.status == CheckStatus.CONFIRMED
    assert check.operation_date == dt.date(2026, 9, 13)


def test_receipt_without_kind_words_still_matches():
    """Описание без слов о виде выплаты — поступление годится, если другого нет."""
    payments = [ExpectedPayment(dt.date(2026, 9, 10), "remainder", Decimal("1000.00"))]
    receipts = [Receipt(dt.date(2026, 9, 10), Decimal("1000.00"), "Поступление от ООО Ромашка")]
    check = _only(payments, receipts)
    assert check.status == CheckStatus.CONFIRMED


def test_vacation_without_its_receipt_is_missing_not_salary():
    """Нет «ОТПУСКНЫХ» в выписке — отпускные не найдены; зарплату они не забирают."""
    payments = [ExpectedPayment(dt.date(2026, 9, 11), "vacation", Decimal("108086.40"))]
    receipts = [
        Receipt(dt.date(2026, 9, 10), Decimal("148626.48"), "ЗАРАБОТНАЯ ПЛАТА. Основание 1")
    ]
    check = _only(payments, receipts)
    assert check.status == CheckStatus.MISSING
