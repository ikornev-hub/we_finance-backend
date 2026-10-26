"""Сценарии «Расходов» поверх ядра и хранилища. Про HTTP не знает."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import BinaryIO

from we_finance.credit.models import LoanStatus
from we_finance.credit.repository import LoanRepository
from we_finance.credit.schedule import calculate
from we_finance.expenses import analysis as analysis_rules
from we_finance.expenses import goals as goal_rules
from we_finance.expenses.categories import category_for
from we_finance.expenses.classify import operation_type
from we_finance.expenses.errors import ExpenseError, ExpenseNotFoundError
from we_finance.expenses.goals import Goal
from we_finance.expenses.income_check import ExpectedPayment, IncomeCheck, check_income
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
from we_finance.expenses.statement import StatementFormatError, read_alfa
from we_finance.salary import service as salary_service
from we_finance.salary.repository import SalaryRepository

PARSERS = {"alfa": read_alfa}


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


def import_statement(
    repo: PostgresExpenseRepository, bank: str, file_name: str, source: BinaryIO
) -> ImportResult:
    """Разобрать выписку, определить тип и категорию каждой операции, сохранить без дублей."""
    parser = PARSERS.get(bank)
    if parser is None:
        raise StatementFormatError(f"Банк {bank} пока не поддерживается")
    owner = repo.owner()
    rules = repo.rules()
    statement = parser(source)
    items = []
    for op in statement.operations:
        kind = operation_type(op, owner)
        items.append(ClassifiedOperation(op, kind, category_for(op, kind, rules)))
    period = (statement.period_from, statement.period_to)
    return repo.save_import(bank, file_name, items, period)


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


def _rule_for(operation: StoredOperation) -> tuple[str, str] | None:
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


def delete_category(repo: PostgresExpenseRepository, category_id: str) -> None:
    """Подкатегория отдаёт операции родителю; категория — в «Неопределённые» с подкатегориями."""
    category = _category(repo, category_id)
    if category.system_code is not None:
        raise ExpenseError(f"«{category.name}» — системная: удалить нельзя, только переименовать")
    move_to = category.parent_id or repo.system_category_id("uncategorized")
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


def month_report(
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month: str,
    today: date,
) -> MonthReport:
    """Месяц: факт по выписке, прогноз «план + факт», доли и границы категорий.

    Месяц закончился (сегодня уже после него) — прогноз равен факту, план не нужен.
    """
    start, end = month_range(month)
    closed = end <= today
    plan = MonthPlan() if closed else month_plan(repo, salary_repo, loan_repo, month)
    states = goal_states(repo, start)
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


def goal_states(repo: PostgresExpenseRepository, month_start: date) -> list[GoalState]:
    """Все цели: отложено (взносы из выписки и вручную) и план на месяц month_start."""
    contributions = repo.manual_contributions() + goal_rules.from_statement(
        repo.savings_operations(), repo.savings_accounts()
    )
    result = []
    for goal in repo.goals():
        before = goal_rules.saved(goal, contributions, month_start)
        result.append(
            GoalState(
                goal,
                goal_rules.saved(goal, contributions),
                before,
                goal_rules.plan(goal, before, month_start),
            )
        )
    return result


def goals_view(
    repo: PostgresExpenseRepository,
    salary_repo: SalaryRepository,
    loan_repo: LoanRepository,
    month: str,
    today: date,
) -> list[GoalView]:
    """Цели на месяц: не хватает на все планы — каждой пропорционально (решение заказчика)."""
    start, _ = month_range(month)
    states = goal_states(repo, start)
    report = month_report(repo, salary_repo, loan_repo, month, today)
    total = sum((s.plan for s in states), ZERO)
    shortage = max(-report.forecast.unallocated, ZERO)  # границы трат не влезают в остаток
    real = goal_rules.allocate({s.goal.id: s.plan for s in states}, total - shortage)
    tails: dict[str, list[str]] = {}
    for tail, goal_id in repo.savings_accounts().items():
        tails.setdefault(goal_id, []).append(tail)
    return [
        GoalView(
            id=s.goal.id,
            name=s.goal.name,
            target_amount=s.goal.target_amount,
            deadline=s.goal.deadline,
            monthly_amount=s.goal.monthly_amount,
            initial_amount=s.goal.initial_amount,
            saved=s.saved,
            saved_before_month=s.saved_before,
            plan=s.plan,
            contribution=real[s.goal.id],
            eta=goal_rules.eta(s.goal, s.saved_before, real[s.goal.id], start),
            account_tails=sorted(tails.get(s.goal.id, [])),
        )
        for s in states
    ]


def save_goal(repo: PostgresExpenseRepository, goal: Goal) -> Goal:
    """Новая цель или правка: нужен срок или взнос в месяц."""
    if goal.deadline is None and goal.monthly_amount is None:
        raise ExpenseError("У цели нужен срок или взнос в месяц")
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
    full = [report for report, closed in facts if closed and report.has_statement]
    current = f"{today.year}-{today.month:02}"
    pace = None
    if current in {report.month for report, _ in facts}:
        live = month_report(repo, salary_repo, loan_repo, current, today)
        pace = analysis_rules.pace(live, today)
    return analysis_rules.Analysis(
        months=[analysis_rules.to_month(report) for report, _ in facts],
        stats=analysis_rules.stats(full),
        pace=pace,
    )
