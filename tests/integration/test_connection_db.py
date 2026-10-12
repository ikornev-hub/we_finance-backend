import os

import pytest

from we_finance.db import check_db

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL не задан - база не настроена"),
]


def test_check_db_with_real_database():
    assert check_db() is True
