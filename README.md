# explore-anything

A chat-first curiosity engine: explore concepts through hook cards, connect them yourself, and keep
your own takeaways. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/P0_SPEC.md](docs/P0_SPEC.md).

## Quickstart

Needs Docker Desktop (running) and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env      # add ANTHROPIC_API_KEY (needed from M2)
make dev                  # Postgres in Docker → migrations → API + page on http://localhost:8000
```

API docs: http://localhost:8000/docs

| Command | What it does |
|---|---|
| `make dev` | Start the DB, apply migrations, run the API with reload |
| `make test` | Run the test suite (uses the separate `explore_test` database) |
| `make lint` / `make fmt` | Ruff checks / auto-fix and format |
| `make migration m="..."` | Autogenerate a migration from model changes |
| `make psql` | Open psql on the dev database |
| `make db-reset` | Delete the DB volume (all local data) |

## Layout

```
apps/api/        FastAPI backend + the minimal static page (app/static)
  app/models.py  three layers: threads/messages · concepts/links · takeaways
  alembic/       migrations
  tests/
infra/db/        Postgres init scripts
docs/            architecture and specs
```
