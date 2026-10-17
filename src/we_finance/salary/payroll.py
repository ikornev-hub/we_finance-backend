"""Получение данных на конкретный день"""

from collections.abc import Sequence
from datetime import date

from we_finance.salary.models import Absence, SalaryTerms


def terms_on(terms: Sequence[SalaryTerms], day: date) -> SalaryTerms:
    """Получить актуальные соглашения на конкретный день"""
    sorted_terms = sorted(terms, key=lambda term: term.start)
    current_term = None
    for term in sorted_terms:
        if term.start <= day:
            current_term = term
    if current_term is None:
        raise ValueError(f"Нет условий на {day}")
    return current_term


def absence_on(absences: Sequence[Absence], day: date) -> Absence | None:
    """Отсутствие, в которое попадает день, или None"""
    for absence in absences:
        if absence.start <= day <= absence.end:
            return absence
    return None
