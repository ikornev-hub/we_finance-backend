from decimal import Decimal

import pytest

from we_finance.money import to_money


@pytest.mark.parametrize(
    "input_value, expected",
    [
        ("10", Decimal("10.00")),
        ("10.5", Decimal("10.50")),
        ("10.567", Decimal("10.57")),
        ("10.555", Decimal("10.56")),
        ("-10.65", Decimal("-10.65")),
        (Decimal("10.1234"), Decimal("10.12")),
        (Decimal("10.999"), Decimal("11.00")),
        (2.675, Decimal("2.68")),
        (10.0, Decimal("10.00")),
    ],
)
def test_to_money(input_value, expected):
    """Перевод значения в число"""
    assert to_money(input_value) == expected
