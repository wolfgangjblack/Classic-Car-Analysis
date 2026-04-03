.PHONY: install install-dev test lint format typecheck docker-up docker-down

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

test:
	cd backend && python -m pytest

lint:
	ruff check backend/

format:
	ruff format backend/

typecheck:
	mypy backend/app/

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
