# We Finance

Приложение для финансовой аналитики личного и семейного бюджета

## How install
1. Развернуть venv
2. Запустить py -m pip install -r requirements-dev.txt


## How start tests
1. Start all tests: py -m pytest -v
2. Start quick tests: py -m pytest -v -m "not slow"
3. Show collect: py -m pytest --collect-only

## How to enable api
1. Enable api: uvicorn we_finance.api:app
2. Send request: curl -i http://127.0.0.1:8000/{health | version}
3. Swagger docs: http://127.0.0.1:8000/docs

## How to start compose
1. copy .env.example to .env
2. Write secrets from ...(requests in @kornev)
    2.1 APP_ENV = dev | test | stage | prod
3. bash: ${project_path} docker compose up -d --build
4. Check start compose: docker ps
5. Stop compose: docker compose down -v
6. Stop compose with save data: docker compose down

## Start pytest in different system
1. прогнать как CI, без внешних систем:
*   env -u APP_ENV -u DATABASE_URL python -m pytest -q
2. проверить код против своей compose-базы:
*   env $(grep '^DATABASE_URL=' .env) python -m pytest -m integration -v
3. всё, кроме интеграционных:
*	python -m pytest -m "not integration" -q
#
## «Локальная разработка»:
база: docker compose up -d db (только база, без контейнера api);
API: uvicorn we_finance.api:app --env-file .env --reload;
в .env нужен DATABASE_URL с localhost в формате postgresql://;
проверка: curl http://127.0.0.1:8000/health

# [Roadmap](ROADMAP.md)
