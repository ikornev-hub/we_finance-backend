from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from we_finance.api import app


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
