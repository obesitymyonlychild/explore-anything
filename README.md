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

## API costs and limits

Every Anthropic API call is recorded with its cost in the `api_call` table. The sidebar shows today's
and this month's spend.

- **App budgets:** `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` in `.env` (defaults $2 / $20; 0 = no limit).
  Once one is reached, new turns and Surprise me are refused with a clear message, and the page warns
  from 80%. Days and months follow your computer's clock. Prices live in `apps/api/app/llm/pricing.py`.
- **Evals:** `evals/run_cards.py` shows an estimate and asks before spending, stops at `--max-cost`
  (default $5), and records its calls as `eval`/`judge`, which don't count toward the app budgets.
- **Hard ceiling:** set a monthly spend limit on the API key's workspace at console.anthropic.com.
  The app's limits are a convenience; the console's is the guarantee.
- **Tests never call the API:** the test setup forces a dummy key and fakes every model.

## Layout

```
apps/api/        FastAPI backend + the minimal static page (app/static)
  app/models.py  three layers: threads/messages · concepts/links · takeaways
  alembic/       migrations
  tests/
infra/db/        Postgres init scripts
docs/            architecture and specs
```
