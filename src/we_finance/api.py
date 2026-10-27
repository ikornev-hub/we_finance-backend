from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from we_finance import __version__
from we_finance.credit.service import CreditError, LoanNotFoundError
from we_finance.db import check_db
from we_finance.expenses.errors import ExpenseError, ExpenseNotFoundError
from we_finance.expenses.statement import StatementFormatError
from we_finance.routers import auth, calculator, expenses, loans, salary
from we_finance.salary.service import ProfileNotFoundError, SalaryError
from we_finance.schemas import HealthResponse, VersionResponse
from we_finance.settings import get_app_env

app = FastAPI(title="We Finance", version=__version__)
app.include_router(calculator.router, prefix="/api/v1")
app.include_router(loans.router, prefix="/api/v1")
app.include_router(salary.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(expenses.router, prefix="/api/v1")


@app.exception_handler(StatementFormatError)
def statement_format_handler(_request: Request, exc: StatementFormatError) -> JSONResponse:
    """Файл не похож на выписку этого банка → 422 с понятным текстом."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ExpenseError)
def expense_error_handler(_request: Request, exc: ExpenseError) -> JSONResponse:
    """Ввод противоречит расходам пользователя → 422."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ExpenseNotFoundError)
def expense_not_found_handler(_request: Request, exc: ExpenseNotFoundError) -> JSONResponse:
    """Нет такой операции, категории или счёта → 404."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(CreditError)
def credit_error_handler(_request: Request, exc: CreditError) -> JSONResponse:
    """Ввод противоречит кредиту → 422 с понятным текстом, а не 500."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ProfileNotFoundError)
def profile_not_found_handler(_request: Request, exc: ProfileNotFoundError) -> JSONResponse:
    """Профиль зарплаты не заведён → 404."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(LoanNotFoundError)
def loan_not_found_handler(_request: Request, exc: LoanNotFoundError) -> JSONResponse:
    """Нет такого кредита → 404."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SalaryError)
def salary_error_handler(_request: Request, exc: SalaryError) -> JSONResponse:
    """Ввод противоречит профилю зарплаты → 422 с понятным текстом, а не 500."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health", tags=["service"], summary="healthchecker", description="Get health app status")
def health(response: Response) -> HealthResponse:
    """Healthcheck"""
    if check_db():
        return HealthResponse(status="ok", db="ok")
    response.status_code = 503
    return HealthResponse(status="degraded", db="unavailable")


@app.get("/version", tags=["service"], summary="Get version", description="Get app version")
def get_version() -> VersionResponse:
    """Get app version"""
    return VersionResponse(version=__version__, env=get_app_env())
