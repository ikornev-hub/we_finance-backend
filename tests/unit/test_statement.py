from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from we_finance.expenses.statement import StatementFormatError, parse_alfa


def test_total_matches_statement_header(operations):

    assert len(operations) == 16
    assert sum(op.amount for op in operations) == Decimal("100376.24")


def test_card_operation_fields(by_id):
    card = by_id["CRD_A00001"]

    assert card.day == date(2026, 10, 1)
    assert card.amount == Decimal("-1234.56")
    assert card.mcc == "5411"
    assert card.merchant == "MAGNIT MM TEST"
    assert card.counterparty is None
    assert card.bank == "alfa"


@pytest.mark.parametrize(
    ("operation_id", "amount", "counterparty"),
    [
        ("C0000000000010", Decimal("-30000"), "+79000000001"),
        ("C0000000000014", Decimal("+1000"), "+79000000005"),
        ("C0000000000012", Decimal("-50000"), None),
    ],
    ids=["transfer_to_phone", "income_transfer", "without_number"],
)
def test_transfer_counterparty(operation_id, amount, counterparty, by_id):
    operation = by_id[operation_id]

    assert operation.amount == amount
    assert operation.counterparty == counterparty


def test_not_alfa_statement_is_rejected(tmp_path):
    path = tmp_path / "other.xlsx"
    book = openpyxl.Workbook()
    book.active["A1"] = "какая-то таблица"
    book.save(path)

    with pytest.raises(StatementFormatError):
        parse_alfa(path)
