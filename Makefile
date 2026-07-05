.PHONY: up down build lint format typecheck import-lint test migrate migrate-down lock bootstrap

up:
	docker compose up --build

down:
	docker compose down -v

build:
	docker compose build

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy src/

import-lint:
	lint-imports

test:
	pytest --cov=src/georisk --cov-report=term-missing

migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade base

lock:
	pip-compile --output-file=requirements.lock pyproject.toml
	pip-compile --extra=dev --output-file=requirements-dev.lock pyproject.toml

bootstrap:
	./scripts/bootstrap_dev.sh
