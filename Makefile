.PHONY: install install-dev test lint format typecheck check docker-up docker-down requirements

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

requirements:
	pip-compile pyproject.toml --output-file=backend/requirements.txt --strip-extras --no-header --no-annotate --no-emit-index-url

test:
	cd backend && python -m pytest

lint:
	ruff check backend/

format:
	ruff format backend/

typecheck:
	mypy backend/app/

check: lint format-check typecheck test

format-check:
	ruff format --check backend/

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
