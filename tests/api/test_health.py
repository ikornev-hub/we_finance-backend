import pytest

from we_finance import __version__


def test_health_ok(api_client, monkeypatch):
    monkeypatch.setattr("we_finance.api.check_db", lambda: True)
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_degraded(api_client, monkeypatch):
    monkeypatch.setattr("we_finance.api.check_db", lambda: False)
    response = api_client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "unavailable"}


def test_get_version(api_client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "stage")
    response = api_client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": __version__, "env": "stage"}


@pytest.mark.parametrize("page", ["/get", "/404", "/not found"])
def test_not_found(api_client, page):
    response = api_client.get(page)
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "page"), [("POST", "/version"), ("PUT", "/health")])
def test_method_not_allowed(api_client, method, page):
    assert api_client.request(method, page).status_code == 405
