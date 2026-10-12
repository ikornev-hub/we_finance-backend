"""Эндпоинты работы с деньгами."""

from typing import Annotated

from fastapi import APIRouter, Query

from we_finance.money import to_money
from we_finance.schemas import MoneyRoundResponse

router = APIRouter(prefix="/money", tags=["money"])


@router.get("/round", summary="Round amount", description="Round amount")
def money_round(
    amount: Annotated[str, Query(max_length=25, pattern=r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")],
) -> MoneyRoundResponse:
    """Round money"""
    result = to_money(amount)
    return MoneyRoundResponse(amount=str(result))
