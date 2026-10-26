"""Сессии: случайный токен на руках у браузера, в базе - только его хеш."""

import hashlib
import secrets

import psycopg2


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SessionStore:
    """Таблица sessions в Postgres."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    def create(self, user_id: str) -> str:
        """Выдать новый токен. Сам токен возвращается один раз и больше нигде не хранится."""
        token = secrets.token_urlsafe(32)
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO sessions (token_hash, user_id) VALUES (%s, %s)",
                        (_hash(token), user_id),
                    )
        finally:
            conn.close()
        return token

    def user_id(self, token: str) -> str | None:
        """Чей токен; None - нет такого или срок вышел."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT user_id FROM sessions WHERE token_hash = %s AND expires_at > now()",
                        (_hash(token),),
                    )
                    row = cur.fetchone()
                    return row[0] if row else None
        finally:
            conn.close()
