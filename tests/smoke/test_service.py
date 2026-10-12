import os

import pytest
import requests

from we_finance import __version__

BASE_URL = os.environ.get("BASE_URL")

pytestmark = pytest.mark.skipif(BASE_URL is None, reason="BASE_URL не задан - сервис не запущен")


def test_health_is_ok():
    response = requests.get(f"{BASE_URL}/health", timeout=5)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_version():
    response = requests.get(f"{BASE_URL}/version", timeout=5)
    assert response.status_code == 200
    assert response.json()["version"] == __version__
    assert response.json()["env"] == os.environ.get("EXPECTED_ENV", "dev")
