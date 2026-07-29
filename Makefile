.PHONY: bootstrap services migrate api worker dispatcher web contracts lint test build check down

bootstrap:
	uv sync --all-groups
	npm install

services:
	docker compose up -d postgres redis

migrate:
	uv run alembic upgrade head

api:
	uv run uvicorn apps.api.app.main:app --reload --port 8800

worker:
	uv run celery -A workers.orchestrator.celery_app:celery_app worker -Q fast_http --loglevel=INFO

dispatcher:
	uv run python -m workers.maintenance.outbox_dispatcher

web:
	npm run dev:web

contracts:
	uv run python scripts/validate_contracts.py

lint:
	uv run ruff check apps workers scripts
	npm run lint:web

test:
	uv run pytest
	npm run test:web

build:
	npm run build:web

check: contracts lint test build

down:
	docker compose down
