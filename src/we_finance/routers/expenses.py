"""Расходы: выписки, операции, категории, счета (требования system/expenses.md §3)."""

from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import BaseModel

from we_finance.expenses import service
from we_finance.expenses.repository import (
    ImportResult,
    PostgresExpenseRepository,
    StoredOperation,
)
from we_finance.expenses.service import CategoryChange, RulePreview
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


class CategoryChangeIn(BaseModel):
    """Какую категорию поставить операции и запомнить ли выбор правилом."""

    category_id: str
    remember: bool = False


@router.get("/operations", summary="Операции (Р2)")
def list_operations(
    repo: Repo,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$", examples=["2026-10"])] = None,
    category_id: str | None = None,
    uncategorized: bool = False,
) -> list[StoredOperation]:
    """Операции по дате; фильтры: месяц, категория (с подкатегориями), только «Неопределённые»."""
    return service.list_operations(repo, month, category_id, uncategorized)


@router.get("/operations/{operation_id}/similar", summary="Что ещё заберёт «запомнить» (Р2)")
def preview_rule(repo: Repo, operation_id: str) -> RulePreview:
    """Будущее правило и неразобранные операции, которые лягут в ту же категорию."""
    return service.preview_rule(repo, operation_id)


@router.patch("/operations/{operation_id}", summary="Сменить категорию операции (Р2)")
def change_category(repo: Repo, operation_id: str, change: CategoryChangeIn) -> CategoryChange:
    """Категория от пользователя; remember — правило, такие же неразобранные разложатся сразу."""
    return service.change_category(repo, operation_id, change.category_id, change.remember)
