from fastapi import FastAPI, Response

from we_finance import __version__
from we_finance.db import check_db
from we_finance.routers import money
from we_finance.schemas import HealthResponse, VersionResponse
from we_finance.settings import get_app_env

app = FastAPI(title="We Finance", version=__version__)
app.include_router(money.router, prefix="/api/v1")


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
