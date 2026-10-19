"""Сервис зарплаты: сценарии поверх ядра и хранилища. Про HTTP не знает."""

from dataclasses import replace

from we_finance.salary.models import Absence, Payment, SalaryProfile
from we_finance.salary.repository import SalaryRepository
from we_finance.salary.year import year_report


class SalaryError(ValueError):
    """Ввод корректен по форме, но противоречит профилю зарплаты → 422."""


class ProfileNotFoundError(LookupError):
    """Профиль зарплаты ещё не заведён → 404."""


def get_profile(repo: SalaryRepository) -> SalaryProfile:
    """Профиль из хранилища или ProfileNotFoundError."""
    profile = repo.get()
    if profile is None:
        raise ProfileNotFoundError("Профиль зарплаты не заведён")
    return profile


def save_profile(repo: SalaryRepository, profile: SalaryProfile) -> None:
    """Сохранить профиль целиком."""
    repo.save(profile)


def year(repo: SalaryRepository, target_year: int) -> list[Payment]:
    """Все выплаты за год по сохранённому профилю."""
    profile = get_profile(repo)
    try:
        return year_report(
            target_year,
            profile.terms,
            profile.absences,
            profile.history,
            profile.stage_start,
        )
    except ValueError as error:
        raise SalaryError(str(error)) from error


def add_absence(repo: SalaryRepository, absence: Absence) -> SalaryProfile:
    """Добавить отсутствие, если оно не пересекается с уже записанными."""
    profile = get_profile(repo)
    for existing in profile.absences:
        if absence.start <= existing.end and existing.start <= absence.end:
            raise SalaryError(
                f"Отсутствие {absence.start}–{absence.end} "
                f"пересекается с {existing.start}–{existing.end}"
            )
    updated = replace(profile, absences=(*profile.absences, absence))
    repo.save(updated)
    return updated
