"""Прогноз месяца (system/expenses.md §2.6–2.7): располагаемый, доли, можно ещё, цели."""

from decimal import Decimal

from we_finance.expenses.report import Flow, LimitedCategory, LimitedGroup, MonthPlan, build_month

MONTH = "2026-10"
GROUPS = [
    LimitedGroup("g-mandatory", "mandatory", "Обязательные"),
    LimitedGroup("g-managed", "managed", "Управляемые"),
    LimitedGroup("g-unmanaged", "unmanaged", "Неуправляемые"),
]


def _category(cid, group, code=None, target=None):
    return LimitedCategory(cid, cid, code, None, Decimal(target) if target else None, [], group)


def _out(amount):
    return Flow(outflow=Decimal(amount), count=1)


def _report(flows, plan=None, tree=None, groups=None):
    tree = tree or [
        _category("income", None, "income"),
        _category("credit", "mandatory"),
        _category("food", "managed"),
        _category("fines", "unmanaged"),
        _category("unknown", None, "uncategorized"),
        _category("savings", None, "savings"),
    ]
    return build_month(MONTH, groups or GROUPS, tree, flows, plan or MonthPlan(), closed=False)


def test_sample_month_matches_fixture_oracle():
    """Эталон образца (fixtures/README.md): располагаемый 99 500, можно ещё 82 876,24."""
    report = _report(
        {
            "income": Flow(inflow=Decimal("180000.00"), count=2),
            "credit": _out("80500.00"),  # кредит 50 000 + жильё 30 000 + связь 500
            "food": _out("6283.56"),  # еда 2 133,56 + транспорт 4 150
            "fines": _out("562.50"),
            "unknown": Flow(Decimal("10777.70"), Decimal("1000.00"), 3),
        }
    )
    forecast = report.forecast
    groups = {group.code: group for group in report.groups}
    assert forecast.disposable == Decimal("99500.00")
    assert forecast.spent == Decimal("16623.76")
    assert forecast.can_spend == Decimal("82876.24")
    assert groups["mandatory"].share == Decimal("0.4472")  # от дохода
    assert groups["managed"].share == Decimal("0.0632")  # от располагаемого
    assert groups["unmanaged"].share == Decimal("0.0057")


def test_goals_take_only_what_fits_after_limits():
    """#50: свободно до целей 9 500, план целей 30 000 → отложить 9 500, «Свободно» 0."""
    tree = [
        _category("income", None, "income"),
        _category("credit", "mandatory"),
        _category("food", "managed", target="90000.00"),
    ]
    report = _report(
        {"income": Flow(inflow=Decimal("180000.00")), "credit": _out("80500.00")},
        MonthPlan(savings=Decimal("30000.00")),
        tree,
    )
    assert report.forecast.savings == Decimal("9500.00")
    assert report.forecast.unallocated == Decimal("0.00")
    assert report.forecast.can_spend == Decimal("90000.00")


def test_goals_get_full_plan_when_it_fits():
    """Влезает целиком — отложить = план."""
    report = _report(
        {"income": Flow(inflow=Decimal("180000.00")), "credit": _out("80500.00")},
        MonthPlan(savings=Decimal("30000.00")),
    )
    assert report.forecast.savings == Decimal("30000.00")
    assert report.forecast.unallocated == Decimal("69500.00")


def test_goals_get_nothing_when_limits_exceed_disposable():
    """Границы больше располагаемого — в цели не уходит ничего, «Свободно» отрицательное."""
    tree = [
        _category("income", None, "income"),
        _category("credit", "mandatory"),
        _category("food", "managed", target="120000.00"),
    ]
    report = _report(
        {"income": Flow(inflow=Decimal("180000.00")), "credit": _out("80500.00")},
        MonthPlan(savings=Decimal("30000.00")),
        tree,
    )
    assert report.forecast.savings == Decimal("0.00")
    assert report.forecast.unallocated == Decimal("-20500.00")


def test_saved_more_than_fits_counts_fact():
    """Отложил по факту больше, чем влезает по плану, — считаем факт."""
    tree = [
        _category("income", None, "income"),
        _category("credit", "mandatory"),
        _category("food", "managed", target="90000.00"),
        _category("savings", None, "savings"),
    ]
    report = _report(
        {
            "income": Flow(inflow=Decimal("180000.00")),
            "credit": _out("80500.00"),
            "savings": _out("15000.00"),
        },
        MonthPlan(savings=Decimal("30000.00")),
        tree,
    )
    assert report.forecast.savings == Decimal("15000.00")
