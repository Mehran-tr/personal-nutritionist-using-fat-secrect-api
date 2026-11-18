.PHONY: install run lint fmt typecheck arch test check up down

install:      ## Install all dependencies (incl. dev)
	uv sync

run:          ## Run the API with auto-reload
	uv run uvicorn nutritionist.main:create_app --factory --reload

fmt:          ## Format and auto-fix
	uv run ruff format . && uv run ruff check --fix .

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy

arch:         ## Enforce layer boundaries
	uv run lint-imports

test:
	uv run pytest

check: lint typecheck arch test  ## Everything CI runs

up:
	docker compose up --build

down:
	docker compose down
