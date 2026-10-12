import psycopg2

from we_finance.settings import get_database_url


def check_db() -> bool:
    url = get_database_url()
    try:
        conn = psycopg2.connect(url, connect_timeout=2)
    except psycopg2.Error:
        return False
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except psycopg2.Error:
        return False
    finally:
        conn.close()
