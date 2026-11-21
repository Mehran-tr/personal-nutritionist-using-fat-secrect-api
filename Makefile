.PHONY: install run lint fmt typecheck arch test check up down db migrate revision loadtest audit

install:      ## Install all dependencies (incl. dev)
	uv sync

run:          ## Run the API with auto-reload
	uv run uvicorn nutritionist.main:create_app --factory --reload --no-server-header

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

db:           ## Start only Postgres + Redis for local development
	docker compose up -d postgres redis

migrate:      ## Apply all migrations
	uv run alembic upgrade head

revision:     ## New migration from model changes: make revision m="add diary"
	uv run alembic revision --autogenerate -m "$(m)"

loadtest:     ## Load test with a fake fatsecret: make loadtest users=50 seconds=60
	perf/run_loadtest.sh "run-$$(date +%H%M%S)" $${users:-50} $${seconds:-60}

audit:        ## Check locked dependencies for known vulnerabilities
	uv export --frozen --no-hashes --format requirements-txt > /tmp/req.txt && uvx pip-audit -r /tmp/req.txt
