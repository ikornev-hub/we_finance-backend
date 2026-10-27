"""Категория операции (business/expenses.md, «Тип операции»): переводы себе и СБП на свой номер."""

from datetime import date
from decimal import Decimal

from we_finance.expenses.categories import OWN_TRANSFER, UNCATEGORIZED, Rule, category_reason
from we_finance.expenses.classify import OperationType, Owner, operation_type
from we_finance.expenses.statement import StatementOperation

OWNER = Owner(phones=frozenset({"+79000000001"}))


def _op(amount, description, counterparty=None):
    return StatementOperation(
        "alfa", "1", date(2026, 10, 5), Decimal(amount), description, counterparty=counterparty
    )


def _category(op, rules=()):
    return category_reason(op, operation_type(op, OWNER), list(rules))


def test_sbp_to_own_phone_waits_for_user():
    """Решение 2026-10-27: СБП на свой номер — «Неопределённые», куда — решает человек."""
    op = _op("-7000.00", "Перевод по СБП", counterparty="+79000000001")
    assert operation_type(op, OWNER) == OperationType.TRANSFER_OWN
    category, reason = _category(op)
    assert category == UNCATEGORIZED
    assert "свой номер" in reason


def test_sbp_to_own_phone_follows_remembered_rule():
    """«Запомнить» по такому переводу работает на следующих выписках."""
    op = _op("-7000.00", "Перевод по СБП", counterparty="+79000000001")
    rule = Rule("counterparty", "+79000000001", "Связь")
    assert _category(op, [rule])[0] == "Связь"


def test_transfer_between_own_accounts_stays_neutral():
    """Между своими счетами Альфы — «Переводы себе», как раньше."""
    op = _op("-5000.00", "Внутрибанковский перевод между счетами, Иванов Иван Иванович")
    assert _category(op)[0] == OWN_TRANSFER


def test_own_funds_to_other_bank_stays_neutral():
    """«Перевод собственных средств в банк …» не в банк кредита — «Переводы себе»."""
    op = _op("-3000.00", "Перевод собственных средств в банк Озон")
    assert _category(op)[0] == OWN_TRANSFER


def test_incoming_from_own_phone_stays_neutral():
    """Пришло от себя — нейтрально: решение касается только исходящих на свой номер."""
    op = _op("3000.00", "Перевод по СБП", counterparty="+79000000001")
    assert _category(op)[0] == OWN_TRANSFER
