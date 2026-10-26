"""Отчёт месяца: факт по выписке, прогноз «план + факт», доли и границы (system/expenses.md §2.6).

Чистые функции: на входе дерево категорий, суммы операций и план, на выходе отчёт.
Ни базы, ни HTTP — удобно проверять unit-тестами на эталоне.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
SHARE = Decimal("0.0001")
ZERO = Decimal("0")

# Обязательные траты: вычитаются из дохода, долей и границ у них нет.
REQUIRED = ("credit", "housing")


@dataclass(frozen=True)
class Flow:
    """Движение по одной категории за месяц: ушло, пришло (оба ≥ 0), сколько операций."""

    outflow: Decimal = ZERO
    inflow: Decimal = ZERO
    count: int = 0


@dataclass(frozen=True)
class LimitedCategory:
    """Категория верхнего уровня, как её знает отчёт: граница и подкатегории."""

    id: str
    name: str
    system_code: str | None
    target_share: Decimal | None
    target_amount: Decimal | None
    children: list[tuple[str, str]] = field(default_factory=list)  # (id, name)


@dataclass(frozen=True)
class MonthPlan:
    """Что ожидается в месяце: доход по «Доходам», платежи по «Кредитам», жильё по правилам."""

    income: Decimal = ZERO
    credit: Decimal = ZERO
    housing: Decimal = ZERO


@dataclass(frozen=True)
class MonthChild:
    """Подкатегория в отчёте."""

    id: str
    name: str
    amount: Decimal
    share: Decimal | None


@dataclass(frozen=True)
class MonthCategory:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Категория месяца: факт, доля, граница (в % и ₽), отклонение, сколько ещё можно."""

    id: str
    name: str
    system_code: str | None
    amount: Decimal
    share: Decimal | None
    limit_mode: str | None  # "share" | "amount" | None — как задана граница
    target_share: Decimal | None
    target: Decimal | None
    deviation: Decimal | None  # факт − граница; > 0 — перерасход
    remaining: Decimal | None  # граница − факт; сколько ещё можно потратить
    children: list[MonthChild]


@dataclass(frozen=True)
class MonthForecast:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Прогноз месяца «план + факт»: от него считаются доли и границы."""

    income: Decimal
    credit: Decimal
    housing: Decimal
    disposable: Decimal  # доход − кредит − жильё
    spent: Decimal  # потрачено из располагаемого (всё, кроме кредита и жилья)
    can_spend: Decimal  # располагаемый − потрачено
    limits_total: Decimal
    unallocated: Decimal  # располагаемый − сумма границ


@dataclass(frozen=True)
class MonthReport:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Месяц целиком."""

    month: str
    income: Decimal
    expenses: Decimal
    balance: Decimal
    disposable: Decimal  # по факту выписки
    uncategorized_count: int
    has_statement: bool
    warnings: list[str]
    forecast: MonthForecast
    categories: list[MonthCategory]


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _share(amount: Decimal, base: Decimal) -> Decimal | None:
    """Доля от располагаемого; располагаемый ≤ 0 — доли не считаются."""
    return (amount / base).quantize(SHARE, rounding=ROUND_HALF_UP) if base > 0 else None


def _total(flows: dict[str, Flow], category: LimitedCategory, attr: str) -> Decimal:
    """Сумма по категории вместе с подкатегориями."""
    ids = [category.id, *(child_id for child_id, _ in category.children)]
    return sum((getattr(flows.get(i, Flow()), attr) for i in ids), ZERO)


def _limit(category: LimitedCategory, base: Decimal):
    """(как задана, доля, сумма) границы на этот месяц."""
    if category.target_amount is not None:
        return "amount", _share(category.target_amount, base), _money(category.target_amount)
    if category.target_share is not None:
        target = _money(category.target_share * base) if base > 0 else None
        return "share", category.target_share, target
    return None, None, None


def _category(category: LimitedCategory, flows: dict[str, Flow], base: Decimal) -> MonthCategory:
    amount = _money(_total(flows, category, "outflow"))
    required = category.system_code in REQUIRED
    mode, target_share, target = (None, None, None) if required else _limit(category, base)
    return MonthCategory(
        id=category.id,
        name=category.name,
        system_code=category.system_code,
        amount=amount,
        share=None if required else _share(amount, base),
        limit_mode=mode,
        target_share=target_share,
        target=target,
        deviation=None if target is None else amount - target,
        remaining=None if target is None else target - amount,
        children=[
            MonthChild(
                child_id,
                name,
                child_amount := _money(flows.get(child_id, Flow()).outflow),
                None if required else _share(child_amount, base),
            )
            for child_id, name in category.children
        ],
    )


def _fact(tree: list[LimitedCategory], flows: dict[str, Flow], code: str) -> Decimal:
    """Факт системной категории: доход — чистый приток, остальные — отток."""
    category = next((c for c in tree if c.system_code == code), None)
    if category is None:
        return ZERO
    outflow = _total(flows, category, "outflow")
    return _total(flows, category, "inflow") - outflow if code == "income" else outflow


def _forecast(
    tree: list[LimitedCategory], flows: dict[str, Flow], plan: MonthPlan
) -> tuple[Decimal, Decimal, Decimal]:
    """(доход, кредит, жильё) прогноза: больше из плана и факта."""
    return (
        max(plan.income, _fact(tree, flows, "income")),
        max(plan.credit, _fact(tree, flows, "credit")),
        max(plan.housing, _fact(tree, flows, "housing")),
    )


def _warnings(month: str, has_statement: bool, base: Decimal, limits_total: Decimal) -> list[str]:
    warnings = []
    if not has_statement:
        warnings.append(f"За {month} выписки нет: факт пустой, прогноз — по «Доходам» и «Кредитам»")
    if base <= 0:
        warnings.append("Располагаемый ≤ 0: доли и границы в % не считаются")
    elif limits_total > base:
        warnings.append(f"Границы больше располагаемого на {_money(limits_total - base)}")
    return warnings


def build_month(
    month: str, tree: list[LimitedCategory], flows: dict[str, Flow], plan: MonthPlan
) -> MonthReport:
    """Отчёт месяца по дереву, движению по категориям и плану."""
    income = _fact(tree, flows, "income")
    spending = [category for category in tree if category.system_code != "income"]
    expenses = sum((_total(flows, c, "outflow") for c in spending), ZERO)
    forecast_income, forecast_credit, forecast_housing = _forecast(tree, flows, plan)
    base = _money(forecast_income - forecast_credit - forecast_housing)

    categories = sorted(
        (_category(c, flows, base) for c in spending), key=lambda c: (-c.amount, c.name)
    )
    spent = sum((c.amount for c in categories if c.system_code not in REQUIRED), ZERO)
    limits_total = sum((c.target for c in categories if c.target is not None), ZERO)
    has_statement = any(flow.count for flow in flows.values())
    return MonthReport(
        month=month,
        income=_money(income),
        expenses=_money(expenses),
        balance=_money(income - expenses),
        disposable=_money(income - _fact(tree, flows, "credit") - _fact(tree, flows, "housing")),
        uncategorized_count=sum(
            flows.get(c.id, Flow()).count for c in tree if c.system_code == "uncategorized"
        ),
        has_statement=has_statement,
        warnings=_warnings(month, has_statement, base, limits_total),
        forecast=MonthForecast(
            income=_money(forecast_income),
            credit=_money(forecast_credit),
            housing=_money(forecast_housing),
            disposable=base,
            spent=_money(spent),
            can_spend=_money(base - spent),
            limits_total=_money(limits_total),
            unallocated=_money(base - limits_total),
        ),
        categories=categories,
    )
