"""Пользователи: найти по логину, задать хеш пароля"""

from uuid import uuid4

import psycopg2


class UserStore:
    """Таблица users в Postgres."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    def find(self, login: str) -> tuple[str, str | None] | None:
        """(id, хеш пароля) по логину или None, если такого нет."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, password_hash FROM users WHERE login = %s", (login,))
                    return cur.fetchone()
        finally:
            conn.close()

    def set_password_hash(self, login: str, password_hash: str) -> bool:
        """Записать хеш. False - такого логина нет."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET password_hash = %s WHERE login = %s",
                        (password_hash, login),
                    )
                    return cur.rowcount == 1
        finally:
            conn.close()

    def add(self, login: str, password_hash: str) -> str:
        """Завести пользователя с паролем. Возвращает id."""
        user_id = uuid4().hex
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (id, login, password_hash) VALUES (%s, %s, %s)",
                        (user_id, login, password_hash),
                    )
        finally:
            conn.close()
        return user_id

    def ensure(self, login: str) -> str:
        """Id пользователя; нет такого — завести без пароля (войти можно только особым путём)."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (id, login) VALUES (%s, %s)"
                        " ON CONFLICT (login) DO NOTHING",
                        (uuid4().hex, login),
                    )
                    cur.execute("SELECT id FROM users WHERE login = %s", (login,))
                    return cur.fetchone()[0]
        finally:
            conn.close()
