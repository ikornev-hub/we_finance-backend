"""Расходы: выписки, операции, категории, счета (требования system/expenses.md §3)."""

from decimal import Decimal
from io import BytesIO
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, File, Form, Path, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from we_finance.credit.repository import LoanRepository
from we_finance.expenses import service
from we_finance.expenses.report import MonthReport
from we_finance.expenses.repository import (
    ImportResult,
    NewAccount,
    PostgresExpenseRepository,
    StoredAccount,
    StoredCategory,
    StoredOperation,
)
from we_finance.expenses.service import CategoryChange, RulePreview
from we_finance.routers.deps import (
    get_expense_repository,
    get_repository,
    get_salary_repository,
)
from we_finance.salary.repository import SalaryRepository

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


# ---------- категории ----------

Share = Annotated[Decimal, Field(ge=0, le=1, examples=["0.15"])]
Amount = Annotated[Decimal, Field(ge=0, decimal_places=2, examples=["15000.00"])]
Name = Annotated[str, Field(min_length=1, max_length=60)]


class CategoryIn(BaseModel):
    """Новая категория; parent_id — подкатегория; граница — доля располагаемого или сумма."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Name
    parent_id: str | None = None
    target_share: Share | None = None
    target_amount: Amount | None = None


class CategoryPatch(BaseModel):
    """Что поменять. Граница: target_share или target_amount; оба null — убрать.

    Не переданное поле не меняется; задать одно — значит убрать другое.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Name | None = None
    target_share: Share | None = None
    target_amount: Amount | None = None


@router.get("/categories", summary="Дерево категорий")
def list_categories(repo: Repo) -> list[StoredCategory]:
    """Категории с подкатегориями; при первом входе — стартовое дерево."""
    return repo.categories()


@router.post("/categories", status_code=status.HTTP_201_CREATED, summary="Добавить категорию")
def create_category(repo: Repo, category: CategoryIn) -> StoredCategory:
    """Категория или подкатегория (уровней два); цель — только у верхнего уровня."""
    return service.create_category(
        repo, category.name, category.parent_id, (category.target_share, category.target_amount)
    )


@router.patch("/categories/{category_id}", summary="Переименовать, задать цель")
def update_category(repo: Repo, category_id: str, patch: CategoryPatch) -> StoredCategory:
    """Меняет только переданные поля; системные можно переименовать."""
    return service.update_category(repo, category_id, patch.model_dump(exclude_unset=True))


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить категорию",
)
def delete_category(repo: Repo, category_id: str) -> Response:
    """Подкатегория → операции родителю; категория → в «Неопределённые»; системная — 422."""
    service.delete_category(repo, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- свои счета ----------


class AccountIn(BaseModel):
    """Свой счёт (последние 4 цифры) или номер телефона; кредитный — с кредитом из «Кредитов»."""

    model_config = ConfigDict(str_strip_whitespace=True)

    bank: Annotated[str, Field(min_length=1, examples=["alfa"])]
    name: Name
    kind: Literal["own", "credit"]
    number_tail: Annotated[str | None, Field(pattern=r"^\d{4}$")] = None
    phone: Annotated[str | None, Field(pattern=r"^\+7\d{10}$", examples=["+79000000000"])] = None
    loan_id: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.number_tail is None and self.phone is None:
            raise ValueError("Нужен номер счёта (4 цифры) или телефон")
        if (self.kind == "credit") != (self.loan_id is not None):
            raise ValueError("loan_id обязателен у счёта кредита и запрещён у своего")
        return self


@router.get("/accounts", summary="Свои счета и номера")
def list_accounts(repo: Repo) -> list[StoredAccount]:
    """Переводы на них — себе (нейтрально) или в кредит (расход «Кредит»)."""
    return repo.accounts()


@router.post("/accounts", status_code=status.HTTP_201_CREATED, summary="Добавить свой счёт")
def create_account(repo: Repo, account: AccountIn) -> StoredAccount:
    """Действует на следующие загрузки; уже загруженные операции не пересчитываются."""
    return service.create_account(repo, NewAccount(**account.model_dump()))


@router.delete(
    "/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить свой счёт"
)
def delete_account(repo: Repo, account_id: str) -> Response:
    """Удаляет счёт; уже загруженные операции не трогает."""
    service.delete_account(repo, account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- месяц ----------


@router.get("/months/{month}", summary="Месяц: факт, прогноз, доли и границы (Р3)")
def month_report(
    repo: Repo,
    salary_repo: Annotated[SalaryRepository, Depends(get_salary_repository)],
    loan_repo: Annotated[LoanRepository, Depends(get_repository)],
    month: Annotated[str, Path(pattern=r"^\d{4}-\d{2}$", examples=["2026-10"])],
) -> MonthReport:
    """Факт по выписке; прогноз — больше из плана («Доходы», «Кредиты», правила жилья) и факта."""
    return service.month_report(repo, salary_repo, loan_repo, month)
