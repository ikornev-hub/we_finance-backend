"""Зарплата: расчёт выплат за год по присланному профилю (требования, З3–З5)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, status

from we_finance.routers.deps import get_salary_repository, get_today
from we_finance.salary import service
from we_finance.salary.repository import SalaryRepository
from we_finance.salary.schemas import (
    AbsenceIn,
    SalaryCalculationIn,
    SalaryProfileIn,
    SalaryTermsIn,
    WhatIfOut,
    YearReportOut,
)

router = APIRouter(prefix="/salary", tags=["salary"])

Repo = Annotated[SalaryRepository, Depends(get_salary_repository)]
Today = Annotated[date, Depends(get_today)]


@router.post(
    "/calculate",
    summary="Salary payments for a year",
    description=(
        "Выплаты за год по присланному профилю: аванс, остаток, отпускные, больничный, "
        "НДФЛ, итоги по месяцам и за год. received — выплата пришла к дате as_of "
        "(по умолчанию сегодня). Ничего не сохраняет."
    ),
)
def calculate(
    request: SalaryCalculationIn, today: Today, as_of: date | None = None
) -> YearReportOut:
    """Расчёт зарплаты за год."""
    return service.calculate(request, as_of or today)


@router.get("/profile", summary="Salary profile")
def get_profile(repo: Repo) -> SalaryProfileIn:
    """Сохранённый профиль: условия, отсутствия, история, начало стажа."""
    return service.to_profile_in(service.get_profile(repo))


@router.put("/profile", summary="Replace salary profile")
def put_profile(profile: SalaryProfileIn, repo: Repo) -> SalaryProfileIn:
    """Заменить профиль целиком. Повтор того же запроса даёт тот же результат."""
    service.save_profile(repo, service.to_profile(profile))
    return profile


@router.post("/absences", status_code=status.HTTP_201_CREATED, summary="Add absence")
def add_absence(absence: AbsenceIn, repo: Repo) -> SalaryProfileIn:
    """Добавить отсутствие, если оно не пересекается с уже записанными."""
    return service.to_profile_in(service.add_absence(repo, service.to_absence(absence)))


@router.get("/{year}", summary="Salary report for a year")
def get_year(year: int, repo: Repo, today: Today, as_of: date | None = None) -> YearReportOut:
    """Отчёт за год по сохранённому профилю; received — на дату as_of."""
    return service.year_out(repo, year, as_of or today)


@router.post("/{year}/what-if", summary="What if terms change")
def what_if(year: int, terms: SalaryTermsIn, repo: Repo) -> WhatIfOut:
    """Год по сохранённому профилю и по варианту с новыми условиями. Ничего не сохраняет."""
    return service.what_if(repo, year, terms)
