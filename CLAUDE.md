# project-ridge

Macro/country risk dashboard. Python backend in [api/](api/) (FastAPI + async SQLAlchemy + Timescale), Next.js frontend in [web/](web/). v2 rewrite of an earlier SQLite-backed Streamlit tool at `~/Documents/macro-tool` (referred to as "v1").

## Read these once per session

- [docs/HANDOFF.md](docs/HANDOFF.md) — locked architectural decisions ("north stars" section §1) and phase-by-phase status. Treat the north stars as load-bearing; do not silently relitigate.
- [README.md](README.md) — quick-start commands.
- [web/AGENTS.md](web/AGENTS.md) — applies to anything under [web/](web/). Next.js 16 has breaking changes from training data; read `node_modules/next/dist/docs/` before writing frontend code.

## Refinement of global rules

My global [~/.claude/CLAUDE.md](/Users/kavishgandhi/.claude/CLAUDE.md) already defaults to "build for the long term" with an escape hatch for genuine short-term wins (must be flagged with reasoning + options). **In this project the bar is tighter**: shortcuts are allowed only for explicitly temporary checks or fixtures, per [docs/HANDOFF.md:88](docs/HANDOFF.md#L88). The general "genuine win" escape hatch does not apply to non-temporary code here — if I think it's warranted, I'll surface it and wait for an explicit yes before writing it that way.

## Stack and commands

All Python commands run from [api/](api/) using `uv`:

| Task | Command |
|---|---|
| Install deps | `uv sync --all-groups` |
| Run tests | `uv run pytest` (or `uv run pytest tests/test_foo.py -x` for one file) |
| Lint | `uv run ruff check src tests` |
| Format | `uv run ruff format src tests` |
| Type-check | `uv run mypy src tests` |
| All pre-commit hooks | `uv run pre-commit run --all-files` |
| Migrations | `uv run alembic upgrade head` / `uv run alembic revision --autogenerate -m "..."` |
| FastAPI | `uv run uvicorn ridge.api.main:app --port 8000` |
| Full pipeline | `uv run python -m ridge.cli` |
| Streamlit admin | `uv run streamlit run streamlit_admin/app.py --server.port 8502` (port 8501 belongs to v1, do not use) |
| Postgres + Timescale | `docker compose up -d` |

Frontend commands run from [web/](web/): `npm install`, `npm run dev`, `npm run build`, `npm run lint`.

## Conventions (Python)

- **Strict mypy + ruff are non-negotiable.** Every commit must pass [.pre-commit-config.yaml](.pre-commit-config.yaml). Never bypass with `--no-verify`; fix the underlying issue.
- **Async SQLAlchemy throughout.** No sync sessions. Engine is lazy and lifespan-managed.
- **Domain types are Pydantic v2, frozen, `extra="forbid"`.** `Observation` ([api/src/ridge/domain/observation.py](api/src/ridge/domain/observation.py)) is the hinge type — everything downstream reads it.
- **ORM rows ≠ domain types.** `ObservationRow` (SQLAlchemy) is separate from `Observation` (Pydantic). Convert via `from_domain()` / `to_domain()`. Do not collapse the boundary.
- **Append-only writes with `vintage`.** Source revisions create a new row; never mutate existing values.
- **Adapter parsing ports v1 verbatim.** v1's quirk handling is load-bearing IP. If an adapter looks weird, assume it's deliberate — ask before "cleaning up".
- **News/event sources write `EventRecord`, not `Observation`.** Do not bucket news into synthetic numeric indicators.
- **Indicator lists come from `SourceAdapter.discover()` → DB seeded `source_indicator` table.** Don't hardcode indicator lists in YAML or code.
- **Settings**: `pydantic-settings`, all env vars prefixed `RIDGE_`, single source of truth in [api/src/ridge/config.py](api/src/ridge/config.py). Alembic reads the DB URL from `Settings` too.

## Conventions (general)

- **DB-backed config over YAML-only.** YAML in [api/src/ridge/seeds/data/](api/src/ridge/seeds/data/) seeds initial values; runtime changes go through the DB.
- **Tests live in [api/tests/](api/tests/), one `test_*.py` per module.** `pytest-asyncio` is in `asyncio_mode = "auto"` — async tests don't need a decorator. Use existing fixtures from [api/tests/conftest.py](api/tests/conftest.py) and [api/tests/fixtures/](api/tests/fixtures/).
- **Add a test or a regression test** for behavior changes / bug fixes. If you can't, say why.
- **Migrations are auto-generated then hand-reviewed.** Always read the generated migration before committing — autogen misses Timescale hypertable details and enum changes.
- **Don't edit `~/Documents/macro-tool` (v1).** It still runs daily for Kavish's personal workflow. v2 will run in parallel until 14+ days of shadow scores match.

## Pipeline vocabulary

When discussing the pipeline, use the actual stage names. Stages run in order via [api/src/ridge/cli.py](api/src/ridge/cli.py): **ingest → quality → scoring → derived → llm → alerts**. Sources are referred to by name (`fred`, `worldbank`, `imf`, `oecd`, `bis`, `yfinance`, `gdelt`, `googlenews`). Don't invent generic terms like "the data layer".

## LLM layer

- Routing via `LLMProvider` protocol, config-driven. Three providers: Claude (Anthropic SDK), Ollama (local `qwen3:14b-q4_K_M`), and OpenAI-compatible (vLLM / LM Studio / llama.cpp).
- **Grounded RAG only — no hallucinated numbers.** Context builder injects data with `[N]` citation markers; output parser validates every numeric claim has a marker. This is non-negotiable in a financial product.
- Not vector-search RAG — deterministic retrieval from the `Observation` store.

## Things I should flag but not act on

- If you spot v1 quirks in adapter code that look like bugs, ask before "fixing" — they're likely deliberate.
- If a change would touch a north-star decision in [docs/HANDOFF.md §1](docs/HANDOFF.md#L71), surface it explicitly before writing code.
- If you find yourself adding YAML config for runtime values, stop — it should go to the DB.
