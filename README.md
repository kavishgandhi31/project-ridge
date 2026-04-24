# Project Ridge

Macro/country risk dashboard with LLM-powered analyst narratives. Ingests economic data from FRED, World Bank, IMF, OECD, BIS, yfinance, and news sources, scores countries across four risk dimensions, and generates analyst-grade narratives.

## Repo structure

```
api/             Python backend (FastAPI + async pipeline)
  src/ridge/    Python package (imports as `ridge`)
  migrations/    Alembic database migrations
  scripts/       One-off and scheduled pipeline scripts
  tests/         pytest test suite
web/             Next.js frontend dashboard
docs/            Product specs and design docs
```

## Quick start

### Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Node.js 20+ (see `web/.node-version`)
- Docker (for Postgres/TimescaleDB)

### 1. Start the database

```bash
cd api
docker compose up -d
```

### 2. Set up the API

```bash
cd api
cp .env.example .env          # fill in API keys
uv sync --all-groups           # install Python deps
uv run alembic upgrade head    # run migrations
uv run uvicorn ridge.api.main:app --port 8000
```

### 3. Start the frontend

```bash
cd web
npm install
npm run dev
```

## Running tests and linters

```bash
# Python (from api/)
cd api
uv run pytest tests/ -x
uv run ruff check src tests
uv run mypy src tests

# TypeScript (from web/)
cd web
npm run build
npm run lint
```

## Pipeline

Run the full data pipeline manually:

```bash
cd api
uv run python -m ridge.cli run
```

See `api/scripts/` for scheduled run scripts used by launchd.
