.PHONY: dev test lint format typecheck check

dev:
	uvicorn app.main:app --reload

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check app tests scripts infrastructure
	ruff format --check app tests scripts infrastructure

format:
	ruff check --fix app tests scripts infrastructure
	ruff format app tests scripts infrastructure

typecheck:
	mypy app

check: lint typecheck test
