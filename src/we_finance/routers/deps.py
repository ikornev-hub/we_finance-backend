"""Зависимости эндпоинтов. Отдельно — чтобы тесты подменяли их через app.dependency_overrides."""

from datetime import date

from we_finance.credit.repository import JsonLoanRepository, LoanRepository
from we_finance.salary.repository import JsonSalaryRepository, SalaryRepository
from we_finance.settings import get_credit_data_path, get_salary_data_path


def get_salary_repository() -> SalaryRepository:
    """Хранилище профиля зарплаты: JSON-файл по пути из SALARY_DATA_PATH."""
    return JsonSalaryRepository(get_salary_data_path())


def get_today() -> date:
    """Сегодня."""
    return date.today()


def get_repository() -> LoanRepository:
    """Хранилище кредитов: JSON-файл по пути из CREDIT_DATA_PATH."""
    return JsonLoanRepository(get_credit_data_path())
