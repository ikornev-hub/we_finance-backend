"""Тип операции: доход, трата, перевод себе или в кредит (требования system/expenses.md §2.2)."""

from dataclasses import dataclass
from enum import StrEnum

from we_finance.expenses.goals import savings_tail
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
    TRANSFER_SAVINGS = "transfer_savings"  # на накопительный счёт или с него — взнос в цель


@dataclass(frozen=True)
class Owner:
    """Что система знает о владельце: свои номера и банки, где лежат кредиты."""

    phones: frozenset[str] = frozenset()
    credit_banks: frozenset[str] = frozenset()
    savings_tails: frozenset[str] = frozenset()  # 4 последние цифры накопительных счетов


# Начисления: работодатель, СФР, банк (решение 2026-10-27: премии, пособия, кэшбэк — доход).
_INCOME = (
    "ЗАРАБОТНАЯ ПЛАТА",
    "АВАНС ПО ЗАРАБОТНОЙ ПЛАТЕ",
    "ОТПУСКНЫЕ",
    "ПЕРЕЧИСЛЕНИЕ ПРЕМИИ",
    "ПОСОБИЕ ПО ВРЕМ",  # «ПО ВРЕМ. НЕТРУДОСПОСОБНОСТИ» и полностью
    "ФЗ 255-ФЗ",  # пособия СФР: больничный, по уходу за ребёнком
    "Выплата за операции покупок",  # кэшбэк банка
    "Выплата в рамках",  # выплата по акции банка
)
# Вклады и экспресс-счёт Альфы — накопления, не траты и не доход (решение 2026-10-27).
_SAVINGS = ("Перевод на экспресс-счет", "Открытие депозита", "Досрочное расторжение депозита")
# Между своими счетами в Альфе — в обе стороны одинаково.
_OWN = "Внутрибанковский перевод между счетами"


def operation_type(op: StatementOperation, owner: Owner) -> OperationType:
    """Тип операции Альфа-Банка по описанию, сумме и тому, что известно о владельце."""
    if op.description.startswith(_SAVINGS):
        return OperationType.TRANSFER_SAVINGS
    if op.amount > 0:
        return _incoming_type(op, owner)
    return _outgoing_type(op, owner)


def _incoming_type(op: StatementOperation, owner: Owner) -> OperationType:
    """Пришли деньги: доход, от себя или от человека."""
    if op.description.startswith(_INCOME):
        return OperationType.INCOME
    if _OWN in op.description:
        return _own_type(op, owner, outgoing=False)
    if op.counterparty in owner.phones:
        return OperationType.TRANSFER_OWN
    return OperationType.TRANSFER_IN


def _outgoing_type(op: StatementOperation, owner: Owner) -> OperationType:
    """Ушли деньги: покупка, платёж, перевод себе, в кредит или человеку."""
    text = op.description
    if op.mcc or "Исходящий платеж QR" in text:
        return OperationType.CARD
    if _OWN in text:
        return _own_type(op, owner, outgoing=True)
    if "Перевод собственных средств" in text:
        return _other_bank_type(op, owner)
    if op.counterparty:
        if op.counterparty in owner.phones:
            return OperationType.TRANSFER_OWN
        return OperationType.TRANSFER_PERSON
    return OperationType.PAYMENT


def _other_bank_type(op: StatementOperation, owner: Owner) -> OperationType:
    """«Перевод собственных средств в банк …»: в банк кредита — в кредит, иначе — себе."""
    if " в банк " not in op.description:  # PDF не пишет банк: в кредит или себе — решает человек
        return OperationType.PAYMENT
    if any(bank in op.description for bank in owner.credit_banks):
        return OperationType.TRANSFER_CREDIT
    return OperationType.TRANSFER_OWN


def _own_type(op: StatementOperation, owner: Owner, outgoing: bool) -> OperationType:
    """Между своими счетами в Альфе: накопительный счёт цели — взнос, иначе — себе."""
    if savings_tail(op.description, outgoing) in owner.savings_tails:
        return OperationType.TRANSFER_SAVINGS
    return OperationType.TRANSFER_OWN
