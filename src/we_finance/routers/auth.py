"""Вход: логин и пароль → токен сессии."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from we_finance.auth.password import check_password
from we_finance.auth.sessions import SessionStore
from we_finance.auth.users import UserStore
from we_finance.settings import get_app_env, get_database_url

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    """Логин и пароль."""

    login: str
    password: str


class TokenOut(BaseModel):
    """Токен сессии: присылать в заголовке Authorization: Bearer <token>."""

    token: str


@router.post("/login", summary="Войти")
def login(body: LoginIn) -> TokenOut:
    """Верный логин и пароль → новый токен; иначе 401 с одним и тем же текстом."""
    url = get_database_url()
    user = UserStore(url).find(body.login)
    if user is None or not check_password(user[1], body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return TokenOut(token=SessionStore(url).create(user[0]))


TEST_LOGIN = "owner"  # решение 2026-10-26: на dev и test — сразу в учётку владельца


@router.post("/test-login", summary="Войти в тестовую учётку (только dev и test)")
def test_login() -> TokenOut:
    """Вход без пароля под tester — для разработки и тестов. На stage и prod — 404."""
    if get_app_env() not in ("dev", "test"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    url = get_database_url()
    return TokenOut(token=SessionStore(url).create(UserStore(url).ensure(TEST_LOGIN)))
