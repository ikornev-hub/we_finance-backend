"""Расходы: выписки, операции, категории, счета (требования system/expenses.md §3)."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Annotated, Literal, Self
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Path, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from we_finance.credit.repository import LoanRepository
from we_finance.expenses import service
from we_finance.expenses.goals import Goal
from we_finance.expenses.income_check import IncomeCheck
from we_finance.expenses.report import MonthReport
from we_finance.expenses.repository import (
    ImportResult,
    NewAccount,
    PostgresExpenseRepository,
    StoredAccount,
    StoredCategory,
    StoredGroup,
    StoredOperation,
)
from we_finance.expenses.service import CategoryChange, RulePreview
from we_finance.routers.deps import (
    get_expense_repository,
    get_repository,
    get_salary_repository,
    get_today,
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


class CategoriesChangeIn(BaseModel):
    """Выбор списком: какие операции и в какую категорию."""

    operation_ids: Annotated[list[str], Field(min_length=1, max_length=500)]
    category_id: str


@router.post("/operations/category", summary="Одна категория нескольким операциям (Р2)")
def change_categories(repo: Repo, change: CategoriesChangeIn) -> dict[str, int]:
    """Чужие и несуществующие операции пропускаются; в ответе — сколько обновлено."""
    return {"updated": service.change_categories(repo, change.operation_ids, change.category_id)}


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
    group_id: str | None = None  # верхний уровень; не задана — «Управляемые»
    target_share: Share | None = None
    target_amount: Amount | None = None


class CategoryPatch(BaseModel):
    """Что поменять. Граница: target_share или target_amount; оба null — убрать.

    Не переданное поле не меняется; задать одно — значит убрать другое.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Name | None = None
    parent_id: str | None = None  # перенести внутрь категории; null — наверх
    group_id: str | None = None  # null — «Служебные»
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
        repo,
        category.name,
        category.parent_id,
        (category.target_share, category.target_amount),
        category.group_id,
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
def delete_category(repo: Repo, category_id: str, move_to: str | None = None) -> Response:
    """Операции и правила — в move_to; по умолчанию к родителю (верхний уровень — в разбор)."""
    service.delete_category(repo, category_id, move_to)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- свои счета ----------


class AccountIn(BaseModel):
    """Свой счёт (последние 4 цифры) или номер телефона; кредитный — с кредитом из «Кредитов»."""

    model_config = ConfigDict(str_strip_whitespace=True)

    bank: Annotated[str, Field(min_length=1, examples=["alfa"])]
    name: Name
    kind: Literal["own", "credit", "savings"]
    number_tail: Annotated[str | None, Field(pattern=r"^\d{4}$")] = None
    phone: Annotated[str | None, Field(pattern=r"^\+7\d{10}$", examples=["+79000000000"])] = None
    loan_id: str | None = None
    goal_id: str | None = None  # у накопительного счёта — его цель

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.number_tail is None and self.phone is None:
            raise ValueError("Нужен номер счёта (4 цифры) или телефон")
        if (self.kind == "credit") != (self.loan_id is not None):
            raise ValueError("loan_id обязателен у счёта кредита и запрещён у своего")
        if (self.kind == "savings") != (self.goal_id is not None):
            raise ValueError("goal_id обязателен у накопительного счёта и запрещён у других")
        if self.kind == "savings" and self.number_tail is None:
            raise ValueError("У накопительного счёта нужны 4 последние цифры номера")
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
    today: Annotated[date, Depends(get_today)],
) -> MonthReport:
    """Факт по выписке; прогноз — больше из плана и факта, у прошедшего месяца — факт."""
    return service.month_report(repo, salary_repo, loan_repo, month, today)


# ---------- сверка доходов ----------


@router.get("/income-check/{year}", summary="Пришли ли выплаты по выписке (Р4)")
def income_check(
    repo: Repo,
    salary_repo: Annotated[SalaryRepository, Depends(get_salary_repository)],
    today: Annotated[date, Depends(get_today)],
    year: Annotated[int, Path(ge=2000, le=2100)],
) -> list[IncomeCheck]:
    """Выплаты года по «Доходам» против поступлений в «Доход»: окно ±5 дней, аванс — по слову."""
    return service.income_check(repo, salary_repo, year, today)


# ---------- группы ----------


class GroupPatch(BaseModel):
    """Имя и/или граница группы. Не переданное поле не меняется."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Name | None = None
    target_share: Share | None = None
    target_amount: Amount | None = None


@router.get("/groups", summary="Группы трат")
def list_groups(repo: Repo) -> list[StoredGroup]:
    """Обязательные, управляемые, неуправляемые, покупки — с категориями и границами."""
    return repo.groups()


@router.patch("/groups/{group_id}", summary="Переименовать группу, задать границу")
def update_group(repo: Repo, group_id: str, patch: GroupPatch) -> StoredGroup:
    """Граница — доля располагаемого или сумма; у «Обязательных» границы нет."""
    return service.update_group(repo, group_id, patch.model_dump(exclude_unset=True))


# ---------- цели накоплений ----------


class GoalIn(BaseModel):
    """Цель: сумма и срок или взнос в месяц; сколько уже отложено до учёта."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Name
    target_amount: Annotated[Decimal, Field(gt=0, decimal_places=2, examples=["1000000.00"])]
    deadline: date | None = None
    monthly_amount: Annotated[Decimal | None, Field(gt=0, decimal_places=2)] = None
    initial_amount: Annotated[Decimal, Field(ge=0, decimal_places=2)] = Decimal("0")
    start_date: date | None = None  # с какого числа начать копить; нет — сразу


class ContributionIn(BaseModel):
    """Ручной взнос: плюс — отложил, минус — снял."""

    day: date
    amount: Annotated[Decimal, Field(decimal_places=2)]
    comment: Annotated[str | None, Field(max_length=200)] = None


@router.get("/goals", summary="Цели накоплений на месяц (Р5)")
def list_goals(
    repo: Repo,
    salary_repo: Annotated[SalaryRepository, Depends(get_salary_repository)],
    loan_repo: Annotated[LoanRepository, Depends(get_repository)],
    today: Annotated[date, Depends(get_today)],
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> list[service.GoalView]:
    """Отложено, план месяца, реальный взнос (не хватает — пропорционально), месяц достижения."""
    month = month or f"{today.year}-{today.month:02}"
    return service.goals_view(repo, salary_repo, loan_repo, month, today)


@router.post("/goals", status_code=status.HTTP_201_CREATED, summary="Новая цель (Р5)")
def create_goal(repo: Repo, goal: GoalIn) -> Goal:
    """Нужен срок или взнос в месяц."""
    return service.save_goal(repo, Goal(uuid4().hex, **goal.model_dump()))


@router.put("/goals/{goal_id}", summary="Изменить цель (Р5)")
def update_goal(repo: Repo, goal_id: str, goal: GoalIn) -> Goal:
    """Все поля цели целиком."""
    service.get_goal(repo, goal_id)
    return service.save_goal(repo, Goal(goal_id, **goal.model_dump()))


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить цель")
def delete_goal(repo: Repo, goal_id: str) -> Response:
    """С ручными взносами и привязанными накопительными счетами."""
    service.get_goal(repo, goal_id)
    repo.delete_goal(goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/goals/{goal_id}/contributions", status_code=status.HTTP_201_CREATED, summary="Ручной взнос"
)
def add_contribution(repo: Repo, goal_id: str, contribution: ContributionIn) -> dict[str, str]:
    """Наличные, другой банк: «отложил N». Минус — снял."""
    service.get_goal(repo, goal_id)
    if contribution.amount == 0:
        raise service.ExpenseError("Взнос не может быть нулевым")
    return {
        "id": repo.add_contribution(
            goal_id, contribution.day, contribution.amount, contribution.comment
        )
    }


# ---------- анализ ----------


@router.get("/analysis", summary="Анализ трат: динамика, медиана, темп (Р6)")
def spending_analysis(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # зависимости FastAPI
    repo: Repo,
    salary_repo: Annotated[SalaryRepository, Depends(get_salary_repository)],
    loan_repo: Annotated[LoanRepository, Depends(get_repository)],
    today: Annotated[date, Depends(get_today)],
    first: Annotated[str, Query(alias="from", pattern=r"^\d{4}-\d{2}$")],
    last: Annotated[str, Query(alias="to", pattern=r"^\d{4}-\d{2}$")],
) -> service.analysis_rules.Analysis:
    """Месяцы периода по факту; медиана и максимум — по полным месяцам; темп — текущего месяца."""
    return service.analysis(repo, salary_repo, loan_repo, first, last, today)
