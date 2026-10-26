"""Сервис зарплаты: сценарии поверх ядра и хранилища. Про HTTP не знает."""

from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal

from we_finance.payment_status import payment_status
from we_finance.salary.models import Absence, HistoryMonth, Payment, SalaryProfile, SalaryTerms
from we_finance.salary.repository import SalaryRepository
from we_finance.salary.schemas import (
    AbsenceIn,
    MonthChangeOut,
    MonthTotalOut,
    PaymentOut,
    SalaryCalculationIn,
    SalaryProfileIn,
    SalaryTermsIn,
    WhatIfOut,
    YearReportOut,
)
from we_finance.salary.year import month_totals, year_report


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


def to_profile(profile_in: SalaryProfileIn) -> SalaryProfile:
    """Схема API → профиль ядра: списки в кортежи, схемы в dataclass-ы."""
    return SalaryProfile(
        terms=tuple(
            SalaryTerms(start=t.start, salary=t.salary, meal_per_day=t.meal_per_day)
            for t in profile_in.terms
        ),
        stage_start=profile_in.stage_start,
        absences=tuple(Absence(kind=a.kind, start=a.start, end=a.end) for a in profile_in.absences),
        history=tuple(
            HistoryMonth(
                year=h.year,
                month=h.month,
                salary=h.salary,
                vacation_pay=h.vacation_pay,
                excluded_days=h.excluded_days,
            )
            for h in profile_in.history
        ),
    )


def _report(profile: SalaryProfile, target_year: int, as_of: date) -> YearReportOut:
    """Отчёт за год по профилю ядра; статус выплат — на дату as_of (сегодняшние — «сегодня»)."""
    try:
        payments = year_report(
            year=target_year,
            terms=profile.terms,
            absences=profile.absences,
            history=profile.history,
            stage_start=profile.stage_start,
        )
    except ValueError as error:
        raise SalaryError(str(error)) from error
    return YearReportOut(
        year=target_year,
        payments=[
            PaymentOut(
                **asdict(p),
                net=p.net,
                received=p.date < as_of,
                status=payment_status(p.date, as_of),
            )
            for p in payments
        ],
        months=[MonthTotalOut.model_validate(m) for m in month_totals(payments)],
        gross=sum((p.gross for p in payments), Decimal("0")),
        tax=sum((p.tax for p in payments), Decimal("0")),
        net=sum((p.net for p in payments), Decimal("0")),
    )


def calculate(request: SalaryCalculationIn, as_of: date) -> YearReportOut:
    """Выплаты за год по присланному профилю, без сохранения."""
    return _report(to_profile(request.profile), request.year, as_of)


def year_out(repo: SalaryRepository, target_year: int, as_of: date) -> YearReportOut:
    """Отчёт за год по сохранённому профилю."""
    return _report(get_profile(repo), target_year, as_of)


def to_terms(terms_in: SalaryTermsIn) -> SalaryTerms:
    """Схема условий → условия ядра."""
    return SalaryTerms(
        start=terms_in.start, salary=terms_in.salary, meal_per_day=terms_in.meal_per_day
    )


def what_if(repo: SalaryRepository, target_year: int, terms_in: SalaryTermsIn) -> WhatIfOut:
    """Год по сохранённому профилю и по варианту с новыми условиями. Ничего не сохраняет."""
    profile = get_profile(repo)
    last = profile.terms[-1].start
    if terms_in.start <= last:
        raise SalaryError(
            f"Новые условия должны начинаться позже {last}, а начинаются {terms_in.start}"
        )
    scenario = replace(profile, terms=(*profile.terms, to_terms(terms_in)))
    before = _report(profile, target_year, terms_in.start)
    after = _report(scenario, target_year, terms_in.start)
    return WhatIfOut(
        year=target_year,
        net_before=before.net,
        net_after=after.net,
        net_change=after.net - before.net,
        months=[
            MonthChangeOut(
                month=b.month, net_before=b.net, net_after=a.net, net_change=a.net - b.net
            )
            for b, a in zip(before.months, after.months, strict=True)
        ],
    )


def to_absence(absence_in: AbsenceIn) -> Absence:
    """Схема отсутствия → отсутствие ядра."""
    return Absence(kind=absence_in.kind, start=absence_in.start, end=absence_in.end)


def to_profile_in(profile: SalaryProfile) -> SalaryProfileIn:
    """Профиль ядра → схема для ответа API (обратно к to_profile)."""
    return SalaryProfileIn.model_validate(asdict(profile))
