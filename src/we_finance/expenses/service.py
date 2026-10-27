"""Сценарии «Расходов» поверх ядра и хранилища. Про HTTP не знает."""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import BinaryIO

from we_finance.credit.models import LoanStatus
from we_finance.credit.repository import LoanRepository
from we_finance.credit.schedule import calculate
from we_finance.expenses import analysis as analysis_rules
from we_finance.expenses import goals as goal_rules
from we_finance.expenses.categories import CREDIT, Rule, category_reason
from we_finance.expenses.classify import OperationType, Owner, operation_type
from we_finance.expenses.errors import ExpenseError, ExpenseNotFoundError
from we_finance.expenses.goals import Goal
from we_finance.expenses.income_check import ExpectedPayment, IncomeCheck, check_income
from we_finance.expenses.loan_goals import LoanGoals
from we_finance.expenses.loan_match import LoanMatcher
from we_finance.expenses.report import MonthPlan, MonthReport, build_month
from we_finance.expenses.repository import (
    ClassifiedOperation,
    ImportResult,
    NewAccount,
    PostgresExpenseRepository,
    StoredAccount,
    StoredCategory,
    StoredGroup,
    StoredOperation,
    StoredRule,
)
from we_finance.expenses.statement import Statement, StatementFormatError, StatementOperation
from we_finance.expenses.statement_pdf import read_alfa_any
from we_finance.salary import service as salary_service
from we_finance.salary.repository import SalaryRepository

PARSERS = {"alfa": read_alfa_any}  # XLSX или PDF — по содержимому


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
        end = date(year + number // 12, number % 12 + 1, 1)  # 9999-12 → 10000 год (#48)
    except ValueError as exc:
        raise ExpenseError(f"Месяц {month} не похож на ГГГГ-ММ или вне диапазона") from exc
    return start, end


@dataclass(frozen=True)
class PreviewOperation:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Новая операция выписки до сохранения: куда система её кладёт и почему."""

    bank_operation_id: str
    day: date
    amount: Decimal
    description: str
    merchant: str | None
    counterparty: str | None
    type: str
    category_id: str | None
    category: str | None
    reason: str
    can_remember: bool  # есть получатель или магазин — правило можно запомнить


@dataclass(frozen=True)
class ImportPreview:
    """Проверка выписки перед сохранением (решение заказчика 2026-10-27)."""

    period_from: date | None
    period_to: date | None
    total: int
    new: int
    duplicates: int
    operations: list[PreviewOperation]


@dataclass(frozen=True)
class ImportOverride:
    """Правка при проверке: другая категория; remember — правило на получателя или магазин."""

    bank_operation_id: str
    category_id: str
    remember: bool = False


@dataclass(frozen=True)
class _Known:
    """Что известно о пользователе для разбора выписки."""

    owner: Owner
    rules: list[Rule]
    loan_paths: dict[str, str]  # счёт кредита из «Моих счетов» → «Кредит/<кредит>»
    loans: LoanMatcher  # сверка переводов без банка с фактами «Кредитов»
    credit: str  # как у пользователя называется «Кредит»


def _classify(
    repo: PostgresExpenseRepository,
    bank: str,
    source: BinaryIO,
    loan_repo: LoanRepository | None = None,
) -> tuple[Statement, list[tuple[ClassifiedOperation, str]]]:
    """Разобрать выписку: тип, категория и причина каждой операции. Базу не меняет."""
    parser = PARSERS.get(bank)
    if parser is None:
        raise StatementFormatError(f"Банк {bank} пока не поддерживается")
    paths = repo.ensure_loan_categories()
    known = _Known(
        repo.owner(),
        repo.rules(),
        paths,
        LoanMatcher(loan_repo.list_loans() if loan_repo else []),
        next(iter(paths.values()), CREDIT + "/").split("/")[0],
    )
    statement = parser(source)
    return statement, [_classify_one(op, known) for op in statement.operations]


def _classify_one(op: StatementOperation, known: _Known) -> tuple[ClassifiedOperation, str]:
    """Тип, категория, причина; перевод без банка (PDF) сверяется с фактами «Кредитов»."""
    kind = operation_type(op, known.owner)
    category, reason = category_reason(op, kind, known.rules)
    if kind == OperationType.TRANSFER_CREDIT:  # в банк кредита — в подкатегорию кредита
        category = next((p for b, p in known.loan_paths.items() if b in op.description), category)
    elif op.description == "Перевод собственных средств":
        found = known.loans.match(op)
        if found:
            kind = OperationType.TRANSFER_CREDIT
            category, reason = f"{known.credit}/{found[0].loan.name}", found[1]
    return ClassifiedOperation(op, kind, category), reason


def preview_import(
    repo: PostgresExpenseRepository,
    bank: str,
    source: BinaryIO,
    loan_repo: LoanRepository | None = None,
) -> ImportPreview:
    """Что ляжет в базу: только новые операции, с категорией и причиной; дубли — числом."""
    statement, items = _classify(repo, bank, source, loan_repo)
    known = repo.existing_ids(bank, [item.operation.bank_operation_id for item, _ in items])
    ids = repo.category_ids()
    fresh = [
        (item, reason) for item, reason in items if item.operation.bank_operation_id not in known
    ]
    return ImportPreview(
        statement.period_from,
        statement.period_to,
        len(items),
        len(fresh),
        len(items) - len(fresh),
        [
            PreviewOperation(
                item.operation.bank_operation_id,
                item.operation.day,
                item.operation.amount,
                item.operation.description,
                item.operation.merchant,
                item.operation.counterparty,
                str(item.kind),
                ids.get(item.category) if item.category else None,
                item.category,
                reason,
                bool(item.operation.counterparty or item.operation.merchant),
            )
            for item, reason in fresh
        ],
    )


def import_statement(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    repo: PostgresExpenseRepository,
    bank: str,
    file_name: str,
    source: BinaryIO,
    overrides: list[ImportOverride] = (),  # type: ignore[assignment]
    loan_repo: LoanRepository | None = None,
) -> ImportResult:
    """Сохранить проверенную выписку: категории — как выбрал пользователь, без дублей."""
    statement, items = _classify(repo, bank, source, loan_repo)
    saved = _apply_overrides(repo, [item for item, _ in items], overrides)
    period = (statement.period_from, statement.period_to)
    return repo.save_import(bank, file_name, saved, period, statement.closing_balance)


def _apply_overrides(
    repo: PostgresExpenseRepository,
    items: list[ClassifiedOperation],
    overrides: list[ImportOverride],
) -> list[ClassifiedOperation]:
    """Правки проверки: категория пользователя; remember — правило, как «Запомнить» в разборе."""
    paths = {category_id: path for path, category_id in repo.category_ids().items()}
    in_file = {item.operation.bank_operation_id for item in items}
    chosen = {}
    for override in overrides:
        if override.bank_operation_id not in in_file:
            raise ExpenseError(f"Операции {override.bank_operation_id} нет в этой выписке")
        if override.category_id not in paths:
            raise ExpenseError(f"Категории {override.category_id} нет")
        chosen[override.bank_operation_id] = override
    result = []
    for item in items:
        override = chosen.get(item.operation.bank_operation_id)
        if override is None:
            result.append(item)
            continue
        result.append(replace(item, category=paths[override.category_id], source="user"))
        rule = _rule_for(item.operation) if override.remember else None
        if rule is not None:
            repo.add_rule(*rule, paths[override.category_id])
    return result


def list_operations(
    repo: PostgresExpenseRepository,
    month: str | None,
    category_id: str | None,
    uncategorized: bool,
) -> list[StoredOperation]:
    """Операции месяца, категории (вместе с подкатегориями) или ждущие разбора."""
    start, end = month_range(month) if month else (None, None)
    return repo.operations(start, end, category_id, uncategorized)


def change_categories(
    repo: PostgresExpenseRepository, operation_ids: list[str], category_id: str
) -> int:
    """Выбор списком: одна категория нескольким операциям сразу, без правил."""
    if not repo.has_category(category_id):
        raise ExpenseError(f"Категории {category_id} нет")
    return repo.set_categories(list(dict.fromkeys(operation_ids)), category_id)


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


def _rule_for(operation: StoredOperation | StatementOperation) -> tuple[str, str] | None:
    """Правило запоминает получателя, если он есть, иначе мерчанта; QR без них — нечего помнить."""
    if operation.counterparty:
        return "counterparty", operation.counterparty
    if operation.merchant:
        return "merchant", operation.merchant
    return None


# ---------- категории ----------


def _category(repo: PostgresExpenseRepository, category_id: str) -> StoredCategory:
    """Категория пользователя; нет — 404."""
    category = repo.category(category_id)
    if category is None:
        raise ExpenseNotFoundError(f"Категория {category_id} не найдена")
    return category


def _check_limit(share: Decimal | None, amount: Decimal | None) -> None:
    if share is not None and amount is not None:
        raise ExpenseError("Граница — либо в процентах, либо суммой, не обе сразу")


def create_category(
    repo: PostgresExpenseRepository,
    name: str,
    parent_id: str | None,
    limit: tuple[Decimal | None, Decimal | None] = (None, None),
    group: str | None = None,
) -> StoredCategory:
    """Категория верхнего уровня или подкатегория; уровней два, граница — только у верхнего.

    limit = (доля располагаемого, сумма) — одно из двух.
    """
    target_share, target_amount = limit
    _check_limit(target_share, target_amount)
    if parent_id is not None:
        parent = repo.category(parent_id)
        if parent is None:
            raise ExpenseError(f"Родительской категории {parent_id} нет")
        if parent.parent_id is not None:
            raise ExpenseError("Уровней два: у подкатегории не бывает своих подкатегорий")
        if target_share is not None or target_amount is not None:
            raise ExpenseError("Граница задаётся только категории верхнего уровня")
    group_id = None
    if parent_id is None:  # новая верхнего уровня — в «Управляемые», если не сказано иначе
        group_id = group or next(g.id for g in repo.groups() if g.code == "managed")
        _group(repo, group_id)
    category_id = repo.add_category(name, parent_id, target_share, group_id)
    if target_amount is not None:
        repo.set_limit(category_id, None, target_amount)
    return _category(repo, category_id)


def update_category(
    repo: PostgresExpenseRepository, category_id: str, changes: dict[str, object]
) -> StoredCategory:
    """Переименовать и/или задать цель; системные переименовывать можно."""
    category = _category(repo, category_id)
    if "name" in changes:
        if changes["name"] is None:
            raise ExpenseError("Имя категории не может быть пустым")
        repo.rename_category(category_id, str(changes["name"]))
    if "parent_id" in changes:
        _move(repo, category, changes["parent_id"])  # type: ignore[arg-type]
        category = _category(repo, category_id)
    if "group_id" in changes:
        if category.parent_id is not None:
            raise ExpenseError("Группа задаётся только категории верхнего уровня")
        if changes["group_id"] is not None:
            _group(repo, str(changes["group_id"]))
        repo.set_category_group(category_id, changes["group_id"])  # type: ignore[arg-type]
    if "target_share" in changes or "target_amount" in changes:
        share = changes.get("target_share")
        amount = changes.get("target_amount")
        _check_limit(share, amount)  # type: ignore[arg-type]
        if category.parent_id is not None and (share is not None or amount is not None):
            raise ExpenseError("Граница задаётся только категории верхнего уровня")
        repo.set_limit(category_id, share, amount)  # type: ignore[arg-type]
    return _category(repo, category_id)


# Системные, на которые опирается автоматика: их не удалить и не перенести внутрь другой.
_FIXED = {"credit", "housing", "income", "own_transfer", "savings", "uncategorized", "cash"}


def _move(repo: PostgresExpenseRepository, category: StoredCategory, parent_id: str | None) -> None:
    """Перенести категорию внутрь другой или наверх; уровней два."""
    if category.system_code in _FIXED:
        raise ExpenseError(f"«{category.name}» — системная: перенести нельзя")
    if parent_id is None:
        if category.parent_id is not None:
            managed = next(g.id for g in repo.groups() if g.code == "managed")
            repo.reparent_category(category.id, None)
            repo.set_category_group(category.id, managed)
        return
    parent = _category(repo, parent_id)
    if parent.id == category.id or parent.parent_id is not None:
        raise ExpenseError("Переносить можно только внутрь категории верхнего уровня")
    if category.children:
        raise ExpenseError(f"У «{category.name}» есть подкатегории — сначала влей их в неё")
    repo.reparent_category(category.id, parent.id)


def delete_category(
    repo: PostgresExpenseRepository, category_id: str, move_to: str | None = None
) -> None:
    """Удалить; операции и правила — в move_to.

    По умолчанию подкатегория отдаёт всё родителю, категория верхнего уровня — в
    «Неопределённые» (вместе с подкатегориями). Правила не теряются.
    """
    category = _category(repo, category_id)
    if category.system_code is not None:
        raise ExpenseError(f"«{category.name}» — системная: удалить нельзя, только переименовать")
    if move_to is None:
        move_to = category.parent_id or repo.system_category_id("uncategorized")
    target = _category(repo, move_to)
    if category.id in (target.id, target.parent_id):
        raise ExpenseError("Переносить операции в удаляемую категорию нельзя")
    repo.delete_category(category_id, move_to)


# ---------- свои счета ----------


def create_account(repo: PostgresExpenseRepository, account: NewAccount) -> StoredAccount:
    """Свой счёт или номер; счёт кредита — только к своему кредиту."""
    if account.loan_id is not None and not repo.has_loan(account.loan_id):
        raise ExpenseError(f"Кредита {account.loan_id} нет")
    return repo.account(repo.add_account(account))


def delete_account(repo: PostgresExpenseRepository, account_id: str) -> None:
    """Удалить свой счёт; уже загруженные операции не пересчитываются."""
    if not repo.delete_account(account_id):
        raise ExpenseNotFoundError(f"Счёт {account_id} не найден")


# ---------- месяц ----------


def month_plan(
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month: str,
) -> MonthPlan:
    """План месяца: выплаты по «Доходам», платежи по графикам «Кредитов», жильё по правилам."""
    start, end = month_range(month)
    try:
        payments = salary_service.year(salary_repo, start.year)
    except salary_service.ProfileNotFoundError, salary_service.SalaryError:
        payments = []  # профиля нет — дохода по плану нет, остаётся факт
    income = sum((p.net for p in payments if start <= p.date < end), Decimal("0"))
    credit = Decimal("0")
    for stored in loan_repo.list_loans():
        if stored.status == LoanStatus.DELETED:
            continue
        rows, _ = calculate(stored.loan, stored.prepayments)
        credit += sum((row.payment for row in rows if start <= row.date < end), Decimal("0"))
    return MonthPlan(income, credit, repo.mandatory_plan(start, end))


def month_report(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month: str,
    today: date,
    states: list[GoalState] | None = None,
) -> MonthReport:
    """Месяц: факт по выписке, прогноз «план + факт», доли и границы категорий.

    Месяц закончился (сегодня уже после него) — прогноз равен факту, план не нужен.
    """
    start, end = month_range(month)
    closed = end <= today
    plan = MonthPlan() if closed else month_plan(repo, salary_repo, loan_repo, month)
    if states is None:
        states = projected_states(repo, salary_repo, loan_repo, start, today)
    plan = MonthPlan(plan.income, plan.credit, plan.mandatory, sum((s.plan for s in states), ZERO))
    manual = sum((c.amount for c in repo.manual_contributions() if start <= c.day < end), ZERO)
    flows = repo.month_flows(start, end)
    return build_month(
        month, repo.limited_groups(), repo.limited_tree(), flows, plan, closed, manual
    )


# ---------- сверка доходов ----------


def income_check(
    repo: PostgresExpenseRepository, salary_repo: SalaryRepository, year: int, today: date
) -> list[IncomeCheck]:
    """Каждая выплата года из «Доходов» — пришла ли по выписке. Профиля нет — пусто."""
    try:
        payments = salary_service.year(salary_repo, year)
    except salary_service.ProfileNotFoundError, salary_service.SalaryError:
        return []
    expected = [ExpectedPayment(p.date, str(p.kind), p.net) for p in payments]
    window = timedelta(days=10)
    receipts = repo.income_receipts(date(year, 1, 1) - window, date(year + 1, 1, 1) + window)
    return check_income(expected, receipts, repo.statement_periods(), today)


# ---------- группы ----------


def _group(repo: PostgresExpenseRepository, group_id: str) -> StoredGroup:
    """Группа пользователя; нет — 422 (это ввод, а не адрес ресурса)."""
    group = repo.group(group_id)
    if group is None:
        raise ExpenseError(f"Группы {group_id} нет")
    return group


def update_group(
    repo: PostgresExpenseRepository, group_id: str, changes: dict[str, object]
) -> StoredGroup:
    """Переименовать группу и/или задать границу; у «Обязательных» границы нет."""
    group = repo.group(group_id)
    if group is None:
        raise ExpenseNotFoundError(f"Группа {group_id} не найдена")
    if "name" in changes:
        if changes["name"] is None:
            raise ExpenseError("Имя группы не может быть пустым")
        repo.rename_group(group_id, str(changes["name"]))
    if "target_share" in changes or "target_amount" in changes:
        share = changes.get("target_share")
        amount = changes.get("target_amount")
        _check_limit(share, amount)  # type: ignore[arg-type]
        if group.code == "mandatory" and (share is not None or amount is not None):
            raise ExpenseError("У «Обязательных» границы нет: они вычитаются из дохода")
        repo.set_group_limit(group_id, share, amount)  # type: ignore[arg-type]
    return repo.group(group_id)


# ---------- цели накоплений ----------

ZERO = Decimal("0")


@dataclass(frozen=True)
class GoalState:
    """Цель на месяц: сколько отложено всего и к началу месяца, план месяца."""

    goal: Goal
    saved: Decimal
    saved_before: Decimal
    plan: Decimal


@dataclass(frozen=True)
class Payday:
    """Сколько положить в цель в день выплаты зарплаты."""

    date: date
    kind: str  # advance — аванс, remainder — остаток
    amount: Decimal


@dataclass(frozen=True)
class GoalView:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Цель для экрана: прогресс, план, реальный взнос (с пропорцией), месяц достижения."""

    id: str
    name: str
    target_amount: Decimal
    deadline: date | None
    monthly_amount: Decimal | None
    initial_amount: Decimal
    saved: Decimal
    saved_before_month: Decimal
    plan: Decimal
    contribution: Decimal
    eta: str | None
    account_tails: list[str]
    start_date: date | None = None
    paydays: list[Payday] = field(default_factory=list)
    projected: bool = False  # будущий месяц: «отложено» — ожидаемое к его началу
    loan_id: str | None = None
    closes_on: date | None = None  # цель «закрыть кредит»: когда закроется при таких ЧДП
    interest_saved: Decimal | None = None  # сколько процентов не уйдёт банку
    note: str | None = None


def goal_states(
    repo: PostgresExpenseRepository,
    month_start: date,
    loans: LoanGoals,
    expected: dict[str, Decimal] | None = None,
) -> list[GoalState]:
    """Все цели: отложено (взносы из выписки и вручную) и план на месяц month_start.

    Цель «закрыть кредит»: отложено — на сколько уменьшился долг, план — ЧДП месяца.
    expected — будущий месяц: сколько будет отложено к его началу по прогнозу.
    """
    contributions = repo.manual_contributions() + goal_rules.from_statement(
        repo.savings_operations(), repo.savings_accounts()
    )
    result = []
    for goal in repo.goals():
        if goal.loan_id:
            loan = loans.state(goal, month_start)
            result.append(GoalState(goal, loan.saved, loan.saved_before, loan.plan))
            continue
        if expected is not None and goal.id in expected:
            before = saved = expected[goal.id]
        else:
            before = goal_rules.saved(goal, contributions, month_start)
            saved = goal_rules.saved(goal, contributions)
        result.append(GoalState(goal, saved, before, goal_rules.plan(goal, before, month_start)))
    return result


def _goal_room(
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month: str,
    today: date,
) -> Decimal:
    """Сколько месяц может отдать целям: доход − обязательные − границы трат."""
    start, end = month_range(month)
    closed = end <= today
    plan = MonthPlan() if closed else month_plan(repo, salary_repo, loan_repo, month)
    report = build_month(
        month,
        repo.limited_groups(),
        repo.limited_tree(),
        repo.month_flows(start, end),
        plan,
        closed,
    )
    return report.forecast.unallocated  # план целей = 0 → свободное до целей


def projected_states(
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month_start: date,
    today: date,
) -> list[GoalState]:
    """Цели на месяц; будущий — с прогнозом накоплений (Решение 2026-10-27).

    От текущего месяца до нужного: в каждом цели получают столько, сколько влезает в бюджет
    (не хватает — пропорционально), отложенное переносится в следующий месяц.
    """
    loans = LoanGoals(loan_repo, salary_repo, today)
    current = today.replace(day=1)
    if month_start <= current:
        return goal_states(repo, month_start, loans)
    states = goal_states(repo, current, loans)
    now = {s.goal.id: s.saved for s in states}
    expected = {s.goal.id: s.saved_before for s in states if not s.goal.loan_id}
    cursor = current
    while cursor < month_start:
        if cursor != current:
            states = goal_states(repo, cursor, loans, expected)
        room = _goal_room(repo, salary_repo, loan_repo, f"{cursor:%Y-%m}", today)
        real = goal_rules.allocate({s.goal.id: s.plan for s in states}, room)
        for goal_id in expected:
            expected[goal_id] += real[goal_id]
            if cursor == current:  # в этом месяце уже отложили больше — берём факт
                expected[goal_id] = max(expected[goal_id], now[goal_id])
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    return goal_states(repo, month_start, loans, expected)


def goals_view(
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month: str,
    today: date,
) -> list[GoalView]:
    """Цели на месяц: не хватает на все планы — каждой пропорционально (решение заказчика)."""
    start, _ = month_range(month)
    loans = LoanGoals(loan_repo, salary_repo, today)
    states = projected_states(repo, salary_repo, loan_repo, start, today)
    report = month_report(repo, salary_repo, loan_repo, month, today, states)
    total = sum((s.plan for s in states), ZERO)
    shortage = max(-report.forecast.unallocated, ZERO)  # границы трат не влезают в остаток
    real = goal_rules.allocate({s.goal.id: s.plan for s in states}, total - shortage)
    tails: dict[str, list[str]] = {}
    for tail, goal_id in repo.savings_accounts().items():
        tails.setdefault(goal_id, []).append(tail)
    return [
        _goal_view(s, real[s.goal.id], start, _salary_paydays(salary_repo, start), tails, loans)
        for s in states
    ]


def _goal_view(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    s: GoalState,
    real: Decimal,
    start: date,
    paydays: list[tuple[date, str, Decimal]],
    tails: dict[str, list[str]],
    loans: LoanGoals,
) -> GoalView:
    """Карточка цели; у цели «закрыть кредит» — ЧДП по дням, дата закрытия, экономия."""
    view = GoalView(
        id=s.goal.id,
        name=s.goal.name,
        target_amount=s.goal.target_amount,
        deadline=s.goal.deadline,
        monthly_amount=s.goal.monthly_amount,
        initial_amount=s.goal.initial_amount,
        saved=s.saved,
        saved_before_month=s.saved_before,
        plan=s.plan,
        contribution=real,
        eta=goal_rules.eta(s.goal, s.saved_before, real, start),
        account_tails=sorted(tails.get(s.goal.id, [])),
        start_date=s.goal.start_date,
        paydays=[
            Payday(day, kind, amount) for day, kind, amount in goal_rules.by_paydays(real, paydays)
        ],
    )
    view = replace(view, projected=start > loans.today)
    if not s.goal.loan_id:
        return view
    loan = loans.outcome(s.goal, start, real)
    return replace(
        view,
        eta=f"{loan.closes_on:%Y-%m}" if loan.closes_on else None,
        paydays=[Payday(day, kind, amount) for day, kind, amount in loan.paydays],
        loan_id=s.goal.loan_id,
        closes_on=loan.closes_on,
        interest_saved=loan.interest_saved,
        note=loan.note,
    )


def _salary_paydays(
    salary_repo: SalaryRepository, month_start: date
) -> list[tuple[date, str, Decimal]]:
    """Аванс и остаток зарплаты в этом месяце: (дата, вид, на руки). Профиля нет — пусто."""
    end = date(month_start.year + month_start.month // 12, month_start.month % 12 + 1, 1)
    try:
        payments = salary_service.year(salary_repo, month_start.year)
    except salary_service.ProfileNotFoundError, salary_service.SalaryError:
        return []
    return sorted(
        (p.date, str(p.kind), p.net)
        for p in payments
        if month_start <= p.date < end and str(p.kind) in {"advance", "remainder"}
    )


@dataclass(frozen=True)
class LoanGoalPreview:
    """Цель «закрыть кредит» до сохранения: ЧДП месяца по дням, дата закрытия, экономия."""

    debt: Decimal  # остаток долга сегодня
    plan: Decimal
    paydays: list[Payday]
    closes_on: date | None
    interest_saved: Decimal
    note: str | None


def preview_loan_goal(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    goal: Goal,
    month: str,
    today: date,
) -> LoanGoalPreview:
    """Расчёт цели по кредиту на месяц, как если бы весь план влез в бюджет."""
    start, _ = month_range(month)
    loans = LoanGoals(loan_repo, salary_repo, today)
    state = loans.state(goal, start)
    outcome = loans.outcome(goal, start, state.plan)
    return LoanGoalPreview(
        goal.target_amount - state.saved,
        state.plan,
        [Payday(day, kind, amount) for day, kind, amount in outcome.paydays],
        outcome.closes_on,
        outcome.interest_saved,
        outcome.note,
    )


def save_goal(
    repo: PostgresExpenseRepository, goal: Goal, loan_repo: LoanRepository | None = None
) -> Goal:
    """Новая цель или правка: нужен срок или взнос в месяц; кредит — только свой."""
    if goal.deadline is None and goal.monthly_amount is None:
        raise ExpenseError("У цели нужен срок или взнос в месяц")
    if goal.loan_id is not None:
        mine = {s.loan.id for s in loan_repo.list_loans()} if loan_repo else set()
        if goal.loan_id not in mine:
            raise ExpenseNotFoundError(f"Кредит {goal.loan_id} не найден")
    repo.save_goal(goal)
    return repo.goal(goal.id)


def get_goal(repo: PostgresExpenseRepository, goal_id: str) -> Goal:
    """Цель пользователя; нет — 404."""
    goal = repo.goal(goal_id)
    if goal is None:
        raise ExpenseNotFoundError(f"Цель {goal_id} не найдена")
    return goal


# ---------- анализ ----------


def _months(first: str, last: str) -> list[str]:
    """«2026-05», «2026-10» → все месяцы между ними включительно (не больше 24)."""
    start, _ = month_range(first)
    end, _ = month_range(last)
    if end < start:
        raise ExpenseError("Конец периода раньше начала")
    result = []
    index = start.year * 12 + start.month - 1
    while index <= end.year * 12 + end.month - 1:
        result.append(f"{index // 12}-{index % 12 + 1:02}")
        index += 1
    if len(result) > 24:
        raise ExpenseError("Период не больше 24 месяцев")
    return result


def _fact_reports(
    repo: PostgresExpenseRepository, months: list[str], today: date
) -> list[tuple[MonthReport, bool]]:
    """Отчёты месяцев только по факту (без плана) и признак «месяц закончился»."""
    groups, tree = repo.limited_groups(), repo.limited_tree()
    manual = repo.manual_contributions()
    facts = []
    for month in months:
        start, end = month_range(month)
        month_manual = sum((c.amount for c in manual if start <= c.day < end), ZERO)
        report = build_month(
            month, groups, tree, repo.month_flows(start, end), MonthPlan(), True, month_manual
        )
        facts.append((report, end <= today))
    return facts


def analysis(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    first: str,
    last: str,
    today: date,
) -> analysis_rules.Analysis:
    """Динамика по фактам месяцев; статистика — по полным месяцам с выпиской; темп — текущий."""
    facts = _fact_reports(repo, _months(first, last), today)
    periods = repo.statement_periods()

    def covered(month: str) -> bool:  # месяц целиком внутри выписки: 27.04–… апрель не полный
        start, end = month_range(month)
        last = end - timedelta(days=1)
        return any(first <= start and last <= until for first, until in periods)

    full = [report for report, closed in facts if closed and covered(report.month)]
    current = f"{today.year}-{today.month:02}"
    pace = None
    if current in {report.month for report, _ in facts}:
        live = month_report(repo, salary_repo, loan_repo, current, today)
        pace = analysis_rules.pace(live, today)
    return analysis_rules.Analysis(
        months=[analysis_rules.to_month(report) for report, _ in facts],
        stats=analysis_rules.stats(full),
        pace=pace,
        full_months=[report.month for report in full],
    )
