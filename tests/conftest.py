from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from we_finance.api import app
from we_finance.expenses.statement import StatementOperation, parse_alfa

STATEMENTS = Path(__file__).parent / "fixtures" / "statements"


@pytest.fixture
def requirements_installed() -> dict[str, str]:
    """Локальное окружение"""
    return {"fastapi": "0.142.2", "pydantic": "2.13.5", "pre-commit": "4.6.2"}


@pytest.fixture
def path_to_requirements() -> Path:
    """Путь к файлам зависимостей"""
    return Path(__file__).parent / "fixtures/requirements"


@pytest.fixture
def api_client() -> TestClient:
    """Клиентское api"""
    return TestClient(app)


@pytest.fixture
def api_v1() -> TestClient:
    """Клиентское api/v1"""
    return TestClient(app, base_url="http://127.0.0.1/api/v1")


@pytest.fixture(scope="module", name="operations")
def fixture_operations() -> list[StatementOperation]:
    """Образец месячной выписки Альфа-Банка, разобранный один раз на модуль."""
    return parse_alfa(STATEMENTS / "alfa-sample.xlsx")


@pytest.fixture(scope="module", name="by_id")
def fixture_by_id(operations: list[StatementOperation]) -> dict[str, StatementOperation]:
    """Операции образца по коду банка."""
    return {op.bank_operation_id: op for op in operations}
