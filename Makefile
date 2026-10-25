API := apps/api

# Docker Desktop on macOS doesn't always put its CLI on PATH.
DOCKER_BIN := /Applications/Docker.app/Contents/Resources/bin
export PATH := $(PATH):$(DOCKER_BIN)
DOCKER ?= $(shell command -v docker 2>/dev/null || echo $(DOCKER_BIN)/docker)

.PHONY: dev api db-up db-down db-reset migrate migration test lint fmt psql

dev: db-up migrate api ## start DB, apply migrations, run the API + page on :8000

api:
	cd $(API) && uv run uvicorn app.main:app --reload --port 8000

db-up:
	$(DOCKER) compose up -d --wait db

db-down:
	$(DOCKER) compose down

db-reset: ## wipe the database volume (destroys all local data)
	$(DOCKER) compose down -v

migrate:
	cd $(API) && uv run alembic upgrade head

migration: ## usage: make migration m="add foo"
	cd $(API) && uv run alembic revision --autogenerate -m "$(m)"

test: db-up
	cd $(API) && uv run pytest

lint:
	cd $(API) && uv run ruff check . && uv run ruff format --check .

fmt:
	cd $(API) && uv run ruff check --fix . && uv run ruff format .

psql:
	$(DOCKER) compose exec db psql -U explore -d explore
