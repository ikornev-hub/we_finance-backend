from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from we_finance.auth.sessions import SessionStore
from we_finance.credit.repository import LoanRepository, PostgresLoanRepository
from we_finance.salary.repository import PostgresSalaryRepository, SalaryRepository
from we_finance.settings import get_database_url

_bearer = HTTPBearer(auto_error=False)


def get_today() -> date:
    """Сегодня."""
    return date.today()


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Кто пришёл: id пользователя по токену из заголовка Authorization; иначе 401."""
    user_id = (
        SessionStore(get_database_url()).user_id(credentials.credentials) if credentials else None
    )
    if user_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Нужно войти",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


CurrentUser = Annotated[str, Depends(get_current_user)]


def get_repository(user_id: CurrentUser) -> LoanRepository:
    """Кредиты того, кто вошёл."""
    return PostgresLoanRepository(get_database_url(), user_id)


def get_salary_repository(user_id: CurrentUser) -> SalaryRepository:
    """Профиль зарплаты того, кто вошёл."""
    return PostgresSalaryRepository(get_database_url(), user_id)
