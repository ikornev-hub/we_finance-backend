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
    """Итог смены категории: операция, правило и что ещё разложилось по нему."""

    operation: StoredOperation
    rule: StoredRule | None
    applied: list[StoredOperation]


@dataclass(frozen=True)
class RulePreview:
    """Будущее правило и неразобранные операции, которые оно заберёт; None — нечего помнить."""

    match_kind: str | None
    pattern: str | None
    operations: list[StoredOperation]


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
    operation = _get(repo, operation_id)
    if not repo.has_category(category_id):
        raise ExpenseError(f"Категории {category_id} нет")
    rule = _rule_for(operation) if remember else None
    stored_rule, applied_ids = repo.set_category(operation_id, category_id, rule)
    applied = [_get(repo, applied_id) for applied_id in applied_ids]
    return CategoryChange(_get(repo, operation_id), stored_rule, applied)


def preview_rule(repo: PostgresExpenseRepository, operation_id: str) -> RulePreview:
    """Что будет, если «запомнить» эту операцию: правило и операции, которые лягут туда же."""
    rule = _rule_for(_get(repo, operation_id))
    if rule is None:
        return RulePreview(None, None, [])
    return RulePreview(*rule, repo.similar(operation_id, rule))


def _get(repo: PostgresExpenseRepository, operation_id: str) -> StoredOperation:
    """Операция пользователя; нет — 404."""
    operation = repo.operation(operation_id)
    if operation is None:
        raise ExpenseNotFoundError(f"Операция {operation_id} не найдена")
    return operation


def _rule_for(operation: StoredOperation) -> tuple[str, str] | None:
    """Правило запоминает получателя, если он есть, иначе мерчанта; QR без них — нечего помнить."""
    if operation.counterparty:
        return "counterparty", operation.counterparty
    if operation.merchant:
        return "merchant", operation.merchant
    return None
