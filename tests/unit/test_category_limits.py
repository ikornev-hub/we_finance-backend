"""Граница категории (system/expenses.md §2.6): у «Обязательных» и «Служебных» её нет."""

from dataclasses import replace
from decimal import Decimal

import pytest

from we_finance.expenses.errors import ExpenseError
from we_finance.expenses.repository import StoredCategory, StoredGroup
from we_finance.expenses.service import create_category, update_category


class FakeRepo:
    """Столько репозитория, сколько нужно правке категории."""

    def __init__(self):
        self._groups = {
            code: StoredGroup(f"g-{code}", code, code, None, None, [])
            for code in ("mandatory", "managed")
        }
        self.categories = {
            "food": StoredCategory(
                "food", "Еда", None, None, None, Decimal("5000.00"), "g-managed", []
            ),
            "rent": StoredCategory("rent", "Жильё", None, "housing", None, None, "g-mandatory", []),
            "unknown": StoredCategory(
                "unknown", "Неопределённые", None, "uncategorized", None, None, None, []
            ),
        }

    def groups(self):
        return list(self._groups.values())

    def group(self, group_id):
        return next((g for g in self._groups.values() if g.id == group_id), None)

    def category(self, category_id):
        return self.categories.get(category_id)

    def set_category_group(self, category_id, group_id):
        self.categories[category_id] = replace(self.categories[category_id], group_id=group_id)

    def set_limit(self, category_id, share, amount):
        self.categories[category_id] = replace(
            self.categories[category_id], target_share=share, target_amount=amount
        )

    def add_category(self, name, parent_id, share, group_id):
        self.categories[name] = StoredCategory(
            name, name, parent_id, None, share, None, group_id, []
        )
        return name


def test_limit_on_mandatory_is_refused():
    repo = FakeRepo()
    with pytest.raises(ExpenseError, match="Обязательных"):
        update_category(repo, "rent", {"target_amount": Decimal("1000.00")})


def test_limit_on_service_is_refused():
    """Ревью aa6f88d: у «Служебных» (group_id = None) граница проходила."""
    repo = FakeRepo()
    with pytest.raises(ExpenseError, match="Служебных"):
        update_category(repo, "unknown", {"target_amount": Decimal("1000.00")})


def test_limit_checked_against_new_group_in_same_patch():
    """Ревью aa6f88d: перенос в «Обязательные» с границей в одном PATCH — по старой группе."""
    repo = FakeRepo()
    with pytest.raises(ExpenseError, match="Обязательных"):
        update_category(
            repo, "food", {"group_id": "g-mandatory", "target_amount": Decimal("5000.00")}
        )


def test_moving_to_mandatory_drops_the_limit():
    """Ревью aa6f88d: граница переживала перенос в «Обязательные» и «воскресала» при обратном."""
    repo = FakeRepo()
    moved = update_category(repo, "food", {"group_id": "g-mandatory"})
    assert moved.target_amount is None and moved.target_share is None
    back = update_category(repo, "food", {"group_id": "g-managed"})
    assert back.target_amount is None


def test_moving_between_spending_groups_keeps_the_limit():
    repo = FakeRepo()
    repo._groups["unmanaged"] = StoredGroup("g-unmanaged", "unmanaged", "unmanaged", None, None, [])  # pylint: disable=protected-access
    moved = update_category(repo, "food", {"group_id": "g-unmanaged"})
    assert moved.target_amount == Decimal("5000.00")


def test_new_mandatory_category_with_limit_is_refused():
    repo = FakeRepo()
    with pytest.raises(ExpenseError, match="Обязательных"):
        create_category(repo, "Ипотека", None, (None, Decimal("1000.00")), "g-mandatory")
