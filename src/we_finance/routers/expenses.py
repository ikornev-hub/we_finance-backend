"""Расходы: загрузка выписок (требования system/expenses.md §3)."""

from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from we_finance.expenses import service
from we_finance.expenses.repository import ImportResult, PostgresExpenseRepository
from we_finance.routers.deps import get_expense_repository

router = APIRouter(prefix="/expenses", tags=["expenses"])

Repo = Annotated[PostgresExpenseRepository, Depends(get_expense_repository)]


@router.post("/imports", status_code=status.HTTP_201_CREATED, summary="Загрузить выписку (Р1)")
def import_statement(
    repo: Repo,
    bank: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> ImportResult:
    """Файл выписки → операции с типом и категорией; уже загруженные пропускаются."""
    return service.import_statement(repo, bank, file.filename or "", BytesIO(file.file.read()))
