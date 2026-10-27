"""Отчёт месяца: факт, прогноз «план + факт», группы, доли и границы (system/expenses.md §2.6).

Чистые функции: на входе группы, дерево категорий, суммы операций и план, на выходе отчёт.
Ни базы, ни HTTP — удобно проверять unit-тестами на эталоне.
"""

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
SHARE = Decimal("0.0001")
ZERO = Decimal("0")

MANDATORY = "mandatory"  # вычитаются из дохода; долей от располагаемого и границ нет
SERVICE = "service"  # «Служебные»: категории без группы (Переводы себе, Неопределённые)
GROUP_ORDER = (MANDATORY, "managed", "unmanaged", "purchases", SERVICE)


@dataclass(frozen=True)
class Flow:
    """Движение по одной категории за месяц: ушло, пришло (оба ≥ 0), сколько операций."""

    outflow: Decimal = ZERO
    inflow: Decimal = ZERO
    count: int = 0


@dataclass(frozen=True)
class LimitedGroup:
    """Группа, как её знает отчёт: код, имя, граница."""

    id: str
    code: str
    name: str
    target_share: Decimal | None = None
    target_amount: Decimal | None = None


@dataclass(frozen=True)
class LimitedCategory:  # pylint: disable=too-many-instance-attributes  # поля = то, что знает отчёт
    """Категория верхнего уровня, как её знает отчёт: группа, граница и подкатегории."""

    id: str
    name: str
    system_code: str | None
    target_share: Decimal | None
    target_amount: Decimal | None
    children: list[tuple[str, str]] = field(default_factory=list)  # (id, name)
    group_code: str | None = None  # None — «Служебные»


@dataclass(frozen=True)
class MonthPlan:
    """Что ожидается: доход по «Доходам», платежи по «Кредитам», обязательные по правилам."""

    income: Decimal = ZERO
    credit: Decimal = ZERO
    mandatory: dict[str, Decimal] = field(default_factory=dict)  # категория → по правилам
    savings: Decimal = ZERO  # отложить на цели по плану (Σ планов целей)


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
    group_code: str
    amount: Decimal
    share: Decimal | None
    limit_mode: str | None  # "share" | "amount" | None — как задана граница
    target_share: Decimal | None
    target: Decimal | None
    deviation: Decimal | None  # факт − граница; > 0 — перерасход
    remaining: Decimal | None  # граница − факт; сколько ещё можно потратить
    children: list[MonthChild]


@dataclass(frozen=True)
class MonthGroup:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Группа месяца: сумма её категорий, доля, граница и сами категории."""

    id: str | None  # у «Служебных» — None
    code: str
    name: str
    amount: Decimal
    share: Decimal | None  # у «Обязательных» — от дохода, у остальных — от располагаемого
    limit_mode: str | None
    target_share: Decimal | None
    target: Decimal | None
    deviation: Decimal | None
    remaining: Decimal | None
    categories: list[MonthCategory]


@dataclass(frozen=True)
class MonthForecast:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Прогноз месяца «план + факт»: от него считаются доли и границы."""

    income: Decimal
    mandatory: Decimal  # Σ обязательных: кредит, жильё, связь, близкие…
    savings: Decimal  # отложить на цели: «сначала себе»
    disposable: Decimal  # доход − обязательные − отложить
    spent: Decimal  # потрачено из располагаемого (всё, кроме обязательных)
    can_spend: Decimal  # располагаемый − потрачено
    limits_total: Decimal
    unallocated: Decimal  # располагаемый − сумма границ
    # обязательные по категориям: кредит — платёж по графику, жильё — по правилу (или факт)
    mandatory_by_category: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class MonthReport:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Месяц целиком."""

    month: str
    income: Decimal
    expenses: Decimal
    balance: Decimal  # доходы − расходы − отложено − переложено себе (≈ как изменился счёт)
    disposable: Decimal  # по факту выписки
    saved: Decimal  # отложено по факту: на накопительные счета и вручную
    uncategorized_count: int
    has_statement: bool
    closed: bool  # месяц закончился: прогноз = факт, план не подмешивается
    warnings: list[str]
    forecast: MonthForecast
    groups: list[MonthGroup]
    categories: list[MonthCategory]
    # переводы себе — нейтральные (Решение 2026-10-27): не траты и не доход, отдельной строкой
    transfers_out: Decimal = ZERO  # ушло на свои счета
    transfers_in: Decimal = ZERO  # пришло со своих счетов
    other_in: Decimal = ZERO  # прочие поступления: отдали долг, возврат — сверх трат категории


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _share(amount: Decimal, base: Decimal) -> Decimal | None:
    """Доля от базы; база ≤ 0 — доли не считаются."""
    return (amount / base).quantize(SHARE, rounding=ROUND_HALF_UP) if base > 0 else None


def _net_out(flow: Flow) -> Decimal:
    """Трата: ушло − вернулось (возврат, отдали долг), не меньше нуля (Решение 2026-10-27)."""
    return max(flow.outflow - flow.inflow, ZERO)


def _spent(flows: dict[str, Flow], category: LimitedCategory) -> Decimal:
    """Трата категории с подкатегориями: ушло − вернулось, не меньше нуля."""
    return max(_total(flows, category, "outflow") - _total(flows, category, "inflow"), ZERO)


def _returned(flows: dict[str, Flow], spending: list[LimitedCategory]) -> Decimal:
    """Прочие поступления: в категории трат вернулось больше, чем ушло (отдали долг)."""
    return sum(
        (max(_total(flows, c, "inflow") - _total(flows, c, "outflow"), ZERO) for c in spending),
        ZERO,
    )


def _total(flows: dict[str, Flow], category: LimitedCategory, attr: str) -> Decimal:
    """Сумма по категории вместе с подкатегориями."""
    ids = [category.id, *(child_id for child_id, _ in category.children)]
    return sum((getattr(flows.get(i, Flow()), attr) for i in ids), ZERO)


def _limit(item: LimitedCategory | LimitedGroup, base: Decimal):
    """(как задана, доля, сумма) границы на этот месяц."""
    if item.target_amount is not None:
        return "amount", _share(item.target_amount, base), _money(item.target_amount)
    if item.target_share is not None:
        target = _money(item.target_share * base) if base > 0 else None
        return "share", item.target_share, target
    return None, None, None


def _group_code(category: LimitedCategory) -> str:
    return category.group_code or SERVICE


def _category(category: LimitedCategory, flows: dict[str, Flow], base: Decimal) -> MonthCategory:
    amount = _money(_spent(flows, category))
    code = _group_code(category)
    mandatory = code == MANDATORY
    limited = code not in (MANDATORY, SERVICE)
    mode, target_share, target = _limit(category, base) if limited else (None, None, None)
    return MonthCategory(
        id=category.id,
        name=category.name,
        system_code=category.system_code,
        group_code=code,
        amount=amount,
        share=None if mandatory else _share(amount, base),
        limit_mode=mode,
        target_share=target_share,
        target=target,
        deviation=None if target is None else amount - target,
        remaining=None if target is None else target - amount,
        children=[
            MonthChild(
                child_id,
                name,
                child_amount := _money(_net_out(flows.get(child_id, Flow()))),
                None if mandatory else _share(child_amount, base),
            )
            for child_id, name in category.children
        ],
    )


def _group(
    group: LimitedGroup, categories: list[MonthCategory], base: Decimal, income: Decimal
) -> MonthGroup:
    amount = sum((c.amount for c in categories), ZERO)
    limited = group.code not in (MANDATORY, SERVICE)
    mode, target_share, target = _limit(group, base) if limited else (None, None, None)
    return MonthGroup(
        id=group.id or None,
        code=group.code,
        name=group.name,
        amount=_money(amount),
        share=_share(amount, income if group.code == MANDATORY else base),
        limit_mode=mode,
        target_share=target_share,
        target=target,
        deviation=None if target is None else amount - target,
        remaining=None if target is None else target - amount,
        categories=sorted(categories, key=lambda c: (-c.amount, c.name)),
    )


def _group_limit(group: MonthGroup) -> Decimal:
    """Сколько группа забирает из располагаемого: своя граница или сумма границ категорий."""
    if group.target is not None:
        return group.target
    return sum((c.target for c in group.categories if c.target is not None), ZERO)


def _warnings(
    month: str, has_statement: bool, base: Decimal, groups: list[MonthGroup]
) -> list[str]:
    warnings = []
    if not has_statement:
        warnings.append(f"За {month} выписки нет: факт пустой, прогноз — по «Доходам» и «Кредитам»")
    limits_total = sum((_group_limit(g) for g in groups), ZERO)
    if base <= 0:
        warnings.append("Располагаемый ≤ 0: доли и границы в % не считаются")
    elif limits_total > base:
        warnings.append(f"Границы больше располагаемого на {_money(limits_total - base)}")
    for group in groups:
        inner = sum((c.target for c in group.categories if c.target is not None), ZERO)
        if group.target is not None and inner > group.target:
            warnings.append(
                f"«{group.name}»: границы категорий больше границы группы на "
                f"{_money(inner - group.target)}"
            )
    return warnings


def _mandatory_by_category(
    mandatory: list[LimitedCategory], flows: dict[str, Flow], plan: MonthPlan
) -> dict[str, Decimal]:
    """Обязательные прогноза по категориям: больше из плана и факта."""
    result = {}
    for category in mandatory:
        planned = (
            plan.credit
            if category.system_code == "credit"
            else plan.mandatory.get(category.id, ZERO)
        )
        result[category.id] = _money(max(planned, _spent(flows, category)))
    return result


def _forecast_mandatory(
    mandatory: list[LimitedCategory], flows: dict[str, Flow], plan: MonthPlan
) -> Decimal:
    """Обязательные прогноза: по каждой категории больше из плана и факта."""
    return sum(_mandatory_by_category(mandatory, flows, plan).values(), ZERO)


def _income(tree: list[LimitedCategory], flows: dict[str, Flow]) -> Decimal:
    """Доход по факту: чистый приток категории «Доход» с подкатегориями."""
    category = next((c for c in tree if c.system_code == "income"), None)
    if category is None:
        return ZERO
    return _total(flows, category, "inflow") - _total(flows, category, "outflow")


def _month_groups(
    groups: list[LimitedGroup], categories: list[MonthCategory], base: Decimal, income: Decimal
) -> list[MonthGroup]:
    """Группы в порядке отчёта; «Служебные» — если в них есть категории."""
    known = {g.code: g for g in groups}
    return [
        _group(
            known.get(code) or LimitedGroup("", code, "Служебные"),
            [c for c in categories if c.group_code == code],
            base,
            income,
        )
        for code in GROUP_ORDER
        if any(c.group_code == code for c in categories)  # пустую группу не показываем
    ]


def _month_forecast(
    planned: tuple[Decimal, Decimal, Decimal],
    categories: list[MonthCategory],
    groups: list[MonthGroup],
) -> MonthForecast:
    """Блок прогноза: (доход, обязательные, отложить) → располагаемый, потрачено, распределено.

    Располагаемый = доход − обязательные: от него доли и границы (решение 2026-10-27).
    Цели в приоритете, но в базу не входят — их план меняется (старт, урезание, сдвиг срока),
    а проценты границ должны значить одни и те же рубли. Цели вычитаются из «можно ещё».
    """
    income, mandatory, savings = planned
    base = _money(income - mandatory)
    spent = sum((c.amount for c in categories if c.group_code != MANDATORY), ZERO)
    limits_total = sum((_group_limit(g) for g in groups), ZERO)
    return MonthForecast(
        income=_money(income),
        mandatory=_money(mandatory),
        savings=_money(savings),
        disposable=base,
        spent=_money(spent),
        can_spend=_money(base - savings - spent),
        limits_total=_money(limits_total),
        unallocated=_money(base - savings - limits_total),
    )


def _moved(tree: list[LimitedCategory], flows: dict[str, Flow]) -> tuple[Decimal, Decimal]:
    """Переводы себе: (ушло на свои счета, пришло со своих) — нейтральные, не траты."""
    own = next((c for c in tree if c.system_code == "own_transfer"), None)
    if own is None:
        return ZERO, ZERO
    return _total(flows, own, "outflow"), _total(flows, own, "inflow")


def _net_moved(tree: list[LimitedCategory], flows: dict[str, Flow]) -> Decimal:
    """Переложено себе за месяц: ушло − пришло."""
    out, back = _moved(tree, flows)
    return out - back


def _saved(tree: list[LimitedCategory], flows: dict[str, Flow], manual: Decimal) -> Decimal:
    """Отложено по факту: ушло на накопительные счета минус снятое с них, плюс вручную."""
    category = next((c for c in tree if c.system_code == "savings"), None)
    if category is None:
        return manual
    return _total(flows, category, "outflow") - _total(flows, category, "inflow") + manual


def _planned(
    spending: list[LimitedCategory],
    flows: dict[str, Flow],
    plan: MonthPlan,
    income: Decimal,
    saved: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """(доход, обязательные, отложить) прогноза: по каждому — больше из плана и факта.

    «Сначала себе»: отложить — план целей; отложил больше плана — считаем факт.
    """
    mandatory = [c for c in spending if _group_code(c) == MANDATORY]
    return (
        max(plan.income, income),
        _forecast_mandatory(mandatory, flows, plan),
        max(plan.savings, saved),
    )


def _has_statement(flows: dict[str, Flow]) -> bool:
    """За месяц есть хоть одна операция."""
    return any(flow.count for flow in flows.values())


def build_month(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    month: str,
    groups: list[LimitedGroup],
    tree: list[LimitedCategory],
    flows: dict[str, Flow],
    plan: MonthPlan,
    closed: bool = False,
    manual_saved: Decimal = ZERO,
) -> MonthReport:
    """Отчёт месяца по группам, дереву, движению по категориям и плану.

    Закрытый месяц план не учитывает: иначе платёж, лёгший не в ту категорию
    (аренда в «Неопределённых»), считается дважды — планом и тратой.
    """
    plan = MonthPlan() if closed else plan
    income = _income(tree, flows)
    spending = [c for c in tree if c.system_code not in ("income", "savings", "own_transfer")]
    saved = _saved(tree, flows, manual_saved)
    planned = _planned(spending, flows, plan, income, saved)
    base = _money(planned[0] - planned[1])
    categories = [_category(c, flows, base) for c in spending]
    month_groups = _month_groups(groups, categories, base, planned[0])
    expenses = sum((c.amount for c in categories), ZERO)
    return MonthReport(
        month=month,
        income=_money(income),
        expenses=_money(expenses),
        balance=_money(
            income + _returned(flows, spending) - expenses - saved - _net_moved(tree, flows)
        ),
        disposable=_money(
            income - sum((c.amount for c in categories if c.group_code == MANDATORY), ZERO)
        ),
        uncategorized_count=sum(
            flows.get(c.id, Flow()).count for c in tree if c.system_code == "uncategorized"
        ),
        saved=_money(saved),
        has_statement=_has_statement(flows),
        closed=closed,
        warnings=_warnings(month, _has_statement(flows), base, month_groups),
        forecast=replace(
            _month_forecast(planned, categories, month_groups),
            mandatory_by_category=_mandatory_by_category(
                [c for c in spending if _group_code(c) == MANDATORY], flows, plan
            ),
        ),
        groups=month_groups,
        categories=sorted(categories, key=lambda c: (-c.amount, c.name)),
        transfers_out=_money(_moved(tree, flows)[0]),
        transfers_in=_money(_moved(tree, flows)[1]),
        other_in=_money(_returned(flows, spending)),
    )
