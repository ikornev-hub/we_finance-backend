"""Сценарии «Расходов» поверх ядра и хранилища. Про HTTP не знает."""

from dataclasses import dataclass
from datetime import date
from typing import BinaryIO

from we_finance.expenses.categories import category_for
from we_finance.expenses.classify import operation_type
from we_finance.expenses.repository import (
    ClassifiedOperation,
    ImportResult,
    PostgresExpenseRepository,
    StoredOperation,
    StoredRule,
)
from we_finance.expenses.statement import StatementFormatError, parse_alfa

PARSERS = {"alfa": parse_alfa}


class ExpenseError(ValueError):
    """Ввод противоречит данным пользователя → 422."""


class ExpenseNotFoundError(LookupError):
    """Нет такой операции, категории или счёта (или они чужие) → 404."""


@dataclass(frozen=True)
class CategoryChange:
    """Итог смены категории: операция и правило, если попросили запомнить."""

    operation: StoredOperation
    rule: StoredRule | None


def month_range(month: str) -> tuple[date, date]:
    """«2026-10» → [1 октября, 1 ноября)."""
    try:
        year, number = (int(part) for part in month.split("-"))
        start = date(year, number, 1)
    except ValueError as exc:
        raise ExpenseError(f"Месяц {month} не похож на ГГГГ-ММ") from exc
    end = date(year + number // 12, number % 12 + 1, 1)
    return start, end


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


def list_operations(
    repo: PostgresExpenseRepository,
    month: str | None,
    category_id: str | None,
    uncategorized: bool,
) -> list[StoredOperation]:
    """Операции месяца, категории (вместе с подкатегориями) или ждущие разбора."""
    start, end = month_range(month) if month else (None, None)
    return repo.operations(start, end, category_id, uncategorized)


def change_category(
    repo: PostgresExpenseRepository, operation_id: str, category_id: str, remember: bool
) -> CategoryChange:
    """Пользователь выбрал категорию; remember — правило на получателя, иначе на мерчанта."""
    if repo.operation(operation_id) is None:
        raise ExpenseNotFoundError(f"Операция {operation_id} не найдена")
    if not repo.has_category(category_id):
        raise ExpenseError(f"Категории {category_id} нет")
    operation = repo.operation(operation_id)
    rule = None
    if remember and operation.counterparty:
        rule = ("counterparty", operation.counterparty)
    elif remember and operation.merchant:
        rule = ("merchant", operation.merchant)
    stored_rule = repo.set_category(operation_id, category_id, rule)
    return CategoryChange(repo.operation(operation_id), stored_rule)
