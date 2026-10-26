"""Вход: логин и пароль → токен сессии."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from we_finance.auth.password import check_password
from we_finance.auth.sessions import SessionStore
from we_finance.auth.users import UserStore
from we_finance.settings import get_database_url

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
