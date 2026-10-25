FROM python:3.14-slim

WORKDIR /app

RUN useradd --create-home --uid 1000 app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

COPY alembic.ini .
COPY migrations ./migrations

EXPOSE 8000

USER app

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
   CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn we_finance.api:app --host 0.0.0.0 --port 8000"]
