"""Подключение к базе для репозиториев «Расходов»: одна транзакция на вызов."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg2


class Postgres:  # pylint: disable=too-few-public-methods  # база для тематических частей
    """Подключение к базе от имени одного пользователя."""

    def __init__(self, database_url: str, user_id: str) -> None:
        self._url = database_url
        self._user_id = user_id

    @contextmanager
    def _cursor(self) -> Iterator:
        """Курсор в одной транзакции: вышли без ошибки — COMMIT, с ошибкой — ROLLBACK."""
        conn = psycopg2.connect(self._url)
        try:
            with conn, conn.cursor() as cur:
                yield cur
        finally:
            conn.close()
