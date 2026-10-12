import pytest


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("422", "422.00"),
        ("422.26", "422.26"),
        ("422.254", "422.25"),
        ("422.248", "422.25"),
        ("422.244", "422.24"),
        ("-2.675", "-2.68"),
    ],
    ids=["integer", "equal", "round-down-third-digit", "up", "down", "negative"],
)
def test_money_round(api_v1, amount, expected):
    response = api_v1.get(f"/money/round?amount={amount}")
    assert response.status_code == 200
    assert response.json() == {"amount": expected}


@pytest.mark.parametrize("amount", ["abc", "", "NaN", "Infinity", "1e2"])
def test_enter_character_money_round(api_v1, amount):
    response = api_v1.get(f"/money/round?amount={amount}")
    assert response.status_code == 422
    details = response.json()["detail"]
    assert details[0]["type"] == "string_pattern_mismatch"


def test_money_round_too_big_amount(api_v1):
    response = api_v1.get("/money/round", params={"amount": "999999999999999999999999999.995"})
    assert response.status_code == 422
    details = response.json()["detail"]
    assert details[0]["type"] == "string_too_long"
