"""Ресурс «кредиты»: сохранённые кредиты и их ЧДП (требования, раздел 3)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, status

from we_finance.credit import service
from we_finance.credit.repository import LoanRepository
from we_finance.credit.schemas import (
    HistoryEntryOut,
    LoanCreateIn,
    LoanDetailOut,
    LoanSummaryOut,
    PrepaymentIn,
    PreviewOut,
    ScheduleItemOut,
)
from we_finance.routers.deps import get_repository, get_today

router = APIRouter(prefix="/loans", tags=["loans"])

Repo = Annotated[LoanRepository, Depends(get_repository)]
Today = Annotated[date, Depends(get_today)]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Add loan (С1)")
def create_loan(loan: LoanCreateIn, repo: Repo, today: Today) -> LoanDetailOut:
    """Добавить кредит: id выдаёт система."""
    return service.create_loan(repo, loan, today)


@router.get("", summary="List loans (С2)")
def list_loans(repo: Repo, today: Today, as_of: date | None = None) -> list[LoanSummaryOut]:
    """Все кредиты с остатком и датой закрытия на дату."""
    return service.list_loans(repo, as_of or today)


@router.get("/{loan_id}", summary="Loan: start and actual data, totals (С3)")
def get_loan(loan_id: str, repo: Repo, today: Today, as_of: date | None = None) -> LoanDetailOut:
    """Кредит целиком: стартовое и актуальное состояние, итоги ЧДП, график, история."""
    return service.loan_detail(repo, loan_id, as_of or today)


@router.get("/{loan_id}/schedule", summary="Actual payment schedule (С4)")
def get_schedule(
    loan_id: str, repo: Repo, today: Today, as_of: date | None = None
) -> list[ScheduleItemOut]:
    """Актуальный график с признаком «уже прошёл»."""
    return service.loan_detail(repo, loan_id, as_of or today).schedule


@router.get("/{loan_id}/history", summary="Payment history (С5)")
def get_history(
    loan_id: str, repo: Repo, today: Today, as_of: date | None = None
) -> list[HistoryEntryOut]:
    """История: обычные платежи и ЧДП с типом записи."""
    return service.loan_detail(repo, loan_id, as_of or today).history


@router.post("/{loan_id}/prepayments/preview", summary="Prepayment what-if (С6)")
def preview_prepayment(
    loan_id: str, prepayment: PrepaymentIn, repo: Repo, today: Today
) -> PreviewOut:
    """Что будет, если внести ЧДП. Ничего не сохраняет."""
    return service.preview_prepayment(repo, loan_id, prepayment, today)


@router.post(
    "/{loan_id}/prepayments", status_code=status.HTTP_201_CREATED, summary="Add prepayment (С7)"
)
def add_prepayment(
    loan_id: str, prepayment: PrepaymentIn, repo: Repo, today: Today
) -> LoanDetailOut:
    """Внести ЧДП: удалить или изменить его потом нельзя."""
    return service.add_prepayment(repo, loan_id, prepayment, today)
