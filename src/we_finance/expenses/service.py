"""Сценарии «Расходов» поверх ядра и хранилища. Про HTTP не знает."""

from typing import BinaryIO

from we_finance.expenses.categories import category_for
from we_finance.expenses.classify import operation_type
from we_finance.expenses.repository import (
    ClassifiedOperation,
    ImportResult,
    PostgresExpenseRepository,
)
from we_finance.expenses.statement import StatementFormatError, parse_alfa

PARSERS = {"alfa": parse_alfa}


def import_statement(
    repo: PostgresExpenseRepository, bank: str, file_name: str, source: BinaryIO
) -> ImportResult:
    """Разобрать выписку, определить тип и категорию каждой операции, сохранить без дублей."""
    parser = PARSERS.get(bank)
    if parser is None:
        raise StatementFormatError(f"Банк {bank} пока не поддерживается")
    owner = repo.owner()
    rules = repo.rules()
    items = []
    for op in parser(source):
        kind = operation_type(op, owner)
        items.append(ClassifiedOperation(op, kind, category_for(op, kind, rules)))
    return repo.save_import(bank, file_name, items)
