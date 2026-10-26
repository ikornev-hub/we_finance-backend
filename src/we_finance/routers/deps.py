"""Зависимости эндпоинтов. Отдельно — чтобы тесты подменяли их через app.dependency_overrides."""

from datetime import date

from we_finance.credit.repository import LoanRepository, PostgresLoanRepository
from we_finance.salary.repository import PostgresSalaryRepository, SalaryRepository
from we_finance.settings import get_database_url


def get_today() -> date:
    """Сегодня."""
    return date.today()


def get_repository() -> LoanRepository:
    """Хранилище кредитов: Postgres. Пользователь пока один — вход появится в шаге 2.3."""
    return PostgresLoanRepository(get_database_url(), "u1")


def get_salary_repository() -> SalaryRepository:
    """Хранилище профиля зарплаты: Postgres. Пользователь пока один — вход появится в шаге 2.3."""
    return PostgresSalaryRepository(get_database_url(), "u1")
