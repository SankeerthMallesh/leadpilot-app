.PHONY: init install dev test lint migrate seed admin

init:            ## create .env with a fresh SECRET_KEY (only if .env is missing)
	@test -f .env || (cp .env.example .env && python scripts/gen_key.py --write-env && echo ".env created")

install:
	python -m pip install -e ".[dev]"

migrate:
	alembic upgrade head

admin:
	python scripts/create_admin.py

seed:
	python scripts/seed.py

dev: migrate
	uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

test:
	pytest -q

lint:
	ruff check . && ruff format --check .
