"""Зависимости эндпоинтов. Отдельно — чтобы тесты подменяли их через app.dependency_overrides."""

from datetime import date

from we_finance.credit.repository import LoanRepository, PostgresLoanRepository
from we_finance.salary.repository import JsonSalaryRepository, SalaryRepository
from we_finance.settings import get_database_url, get_salary_data_path


def get_salary_repository() -> SalaryRepository:
    """Хранилище профиля зарплаты: JSON-файл по пути из SALARY_DATA_PATH."""
    return JsonSalaryRepository(get_salary_data_path())


def get_today() -> date:
    """Сегодня."""
    return date.today()


def get_repository() -> LoanRepository:
    """Хранилище кредитов: Postgres. Пользователь пока один — вход появится в шаге 2.3."""
    return PostgresLoanRepository(get_database_url(), "u1")
