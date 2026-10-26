"""Тип операции: доход, трата, перевод себе или в кредит (требования system/expenses.md §2.2)."""

from dataclasses import dataclass
from enum import StrEnum

from we_finance.expenses.statement import StatementOperation


class OperationType(StrEnum):
    """Что это за операция — до категории."""

    INCOME = "income"  # зарплата, аванс
    CARD = "card"  # покупка картой или по QR
    PAYMENT = "payment"  # платёж по реквизитам: связь, штраф
    TRANSFER_OWN = "transfer_own"  # себе — нейтрально
    TRANSFER_CREDIT = "transfer_credit"  # на счёт кредита — расход «Кредит»
    TRANSFER_PERSON = "transfer_person"  # человеку
    TRANSFER_IN = "transfer_in"  # пришло от человека


@dataclass(frozen=True)
class Owner:
    """Что система знает о владельце: свои номера и банки, где лежат кредиты."""

    phones: frozenset[str] = frozenset()
    credit_banks: frozenset[str] = frozenset()


_INCOME = ("ЗАРАБОТНАЯ ПЛАТА", "АВАНС ПО ЗАРАБОТНОЙ ПЛАТЕ")


def operation_type(op: StatementOperation, owner: Owner) -> OperationType:
    """Тип операции Альфа-Банка по описанию, сумме и тому, что известно о владельце."""
    if op.amount > 0:
        return _incoming_type(op, owner)
    return _outgoing_type(op, owner)


def _incoming_type(op: StatementOperation, owner: Owner) -> OperationType:
    """Пришли деньги: доход, от себя или от человека."""
    if op.description.startswith(_INCOME):
        return OperationType.INCOME
    if (
        "Внутрибанковский перевод между счетами" in op.description
        or op.counterparty in owner.phones
    ):
        return OperationType.TRANSFER_OWN
    return OperationType.TRANSFER_IN


def _outgoing_type(op: StatementOperation, owner: Owner) -> OperationType:
    """Ушли деньги: покупка, платёж, перевод себе, в кредит или человеку."""
    text = op.description
    if op.mcc or "Исходящий платеж QR" in text:
        return OperationType.CARD
    if "Перевод собственных средств" in text:
        if any(bank in text for bank in owner.credit_banks):
            return OperationType.TRANSFER_CREDIT
        return OperationType.TRANSFER_OWN
    if op.counterparty:
        if op.counterparty in owner.phones:
            return OperationType.TRANSFER_OWN
        return OperationType.TRANSFER_PERSON
    return OperationType.PAYMENT
