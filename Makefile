API := apps/api

# Docker Desktop on macOS doesn't always put its CLI on PATH.
DOCKER_BIN := /Applications/Docker.app/Contents/Resources/bin
export PATH := $(PATH):$(DOCKER_BIN)
DOCKER ?= $(shell command -v docker 2>/dev/null || echo $(DOCKER_BIN)/docker)

.PHONY: dev lan lan-password api db-up db-down db-reset migrate migration test lint fmt psql

dev: db-up migrate api ## start DB, apply migrations, run the API + page on :8000

lan: lan-password db-up migrate ## serve on your home Wi-Fi, for your phone and other computers
	@echo "On your phone or another computer on this Wi-Fi, open:"
	@echo "  http://$$(scutil --get LocalHostName 2>/dev/null || hostname -s).local:8000"
	@ip=$$(ipconfig getifaddr en0 || ipconfig getifaddr en1); [ -n "$$ip" ] && echo "  http://$$ip:8000  (if the .local name doesn't work)" || true
	cd $(API) && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

lan-password:
	@grep -Eq '^APP_PASSWORD=.+' .env 2>/dev/null || { echo "Set APP_PASSWORD in .env first: anyone on your Wi-Fi could open the app (and spend API credit)."; exit 1; }

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
