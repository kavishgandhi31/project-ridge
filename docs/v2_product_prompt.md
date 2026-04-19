# v2 Product Build — Chat Prompt

Copy everything below the line into a new Claude chat to start the v2 planning session.

---

## Context

I'm a senior macro/country risk analyst at an asset manager ($2.1bn AUM) covering Eastern Europe and Africa across FX, rates, equities, and sovereign credit. I built a personal macro monitoring tool called macro-tool that runs a daily pipeline: ingest from free sources (FRED, yfinance, World Bank, BIS, IMF, OECD), score 183 countries across 4 dimensions (growth_momentum, external_balance, monetary_stance, risk_sentiment), dispatch alerts (WATCH/ALERT/ESCALATE tiers), generate a daily digest, and display everything on a Streamlit dashboard.

The tool works — it runs on a Mac Mini via launchd, scores countries, catches outliers, validates cross-source data, and produces a digest every morning. But it was built incrementally over many sessions and the architecture reflects that. I want to rebuild it as a product I can sell to other macro analysts and portfolio managers.

## What exists today (v1)

**Pipeline stages:** ingest -> quality -> score -> analyse -> headlines -> digest -> record
**Sources:** FRED (177 countries), yfinance (157 countries, FX/equity/commodities), World Bank (182 countries, 7 indicators), BIS (47 countries, credit gap/property prices), IMF (WEO forecasts, IFS monthly, BOP quarterly), OECD (CLI/BCI monthly)
**Scoring:** 4 dimensions equally weighted (0.25 each), z-score based, composite range -3 to +3, tier thresholds at 1.0/1.5/2.0
**Quality layer:** outlier detection (4-sigma gate), cross-source FX validation, series staleness monitoring, FRED revision detection, backfill detection, score stability checks
**Dashboard:** Streamlit with 10 pages (overview, region, country, market pulse, FX pulse, news, contagion, watchlists, data quality, digest)
**Storage:** SQLite (cache.db for API responses, macro_tool.db for history/health tracking)
**Also built:** FX hourly monitor (independent pipeline), series validator, backtester, peer-relative scoring, contagion scoring

**Key learnings from v1 (hard-won, don't lose these):**
- WorldBank API returns regional aggregates on page 1; country data starts page 2+. Must paginate.
- FRED returns DataFrames with date as a column, not as DatetimeIndex. Code that assumes DatetimeIndex breaks silently.
- yfinance ticker mapping for EM/FM currencies is fragile — many pairs don't exist or use inverted conventions (USD/X vs X/USD).
- BIS CSV bulk downloads are more reliable than their API.
- IMF WEO/IFS APIs have inconsistent country code mappings and change response format between vintages.
- Sanctioned markets (RUS, IRN, PRK, SYR, etc.) need special handling — no market data, but important for regional spillover monitoring.
- Scoring with <50% indicator coverage produces unreliable composites. Need a minimum coverage gate.
- Cross-source FX validation catches real issues (FRED/yfinance unit inversions for BRL, PEN).

## What I want to build (v2)

### Product vision
A subscription macro dashboard for buy-side analysts and PMs. Think "budget Bloomberg macro monitor" — daily country risk scoring, alert dispatch, event tracking, and LLM-powered analysis. Start with free data sources, architect so paid sources (Bloomberg B-PIPE, Haver, Refinitiv) are drop-in replacements.

### Core design principle: adaptive, not hardcoded
v1's biggest weakness is hardcoding disguised as config. Country lists, indicator mappings, scoring dimensions, source-specific parsing logic, tier thresholds, alert rules — all of these should be data-driven and runtime-configurable, not baked into code or static YAML that requires a deploy to change. The system should adapt to: new countries appearing in a source, new indicators being added, scoring models being swapped, alert rules being tuned per user — all without touching Python files. If I have to edit code to add a new indicator or change a scoring weight, the architecture is wrong.

### Key requirements
1. **Clean restart** — new repo, proper domain model, typed throughout, production-grade from day one
2. **Pluggable data sources** — every source is an adapter behind a standard interface. Swapping FRED for Bloomberg should be a config change + one new adapter file, not a rewrite. Source metadata (what indicators exist, what countries are covered, what frequency they update) should be discoverable at runtime, not enumerated in config files.
3. **Canonical internal data model** — all sources normalize to the same schema before hitting the pipeline. No more source-specific DataFrame shapes leaking into scoring/analysis.
4. **Three source frequency tiers designed in from the start:**
   - Batch (GDP, trade, WEO) — daily/weekly pull
   - Near-real-time (FX, equities, CDS) — sub-hourly, eventually streaming
   - Event-driven (central bank decisions, elections, sanctions) — push-based
5. **User-configurable scoring** — weights, thresholds, and dimension definitions should be adjustable per user, not baked into YAML that requires a code deploy to change.
6. **Multi-tenant ready** — even if v2.0 is single-user, the data model should support multiple users with different watchlists, alert preferences, and scoring configs.
7. **Dashboard that doesn't look like a prototype** — the Streamlit dashboard works but looks like a data science project, not a product. Need to decide: stay with Streamlit (fast iteration) or move to a proper frontend (React/Next.js)?

### Technical constraints
- I'm one person. Needs to be buildable solo.
- Mac Mini M4 24GB is the server for now. No cloud infra yet.
- Python is the language (my strength, and the data/ML ecosystem is here).
- Budget: ~$50-100/month for APIs and services initially.

## What I need from this session

1. **Architecture design** — domain model, data flow, module boundaries, interface contracts. Show me the folder structure and the key abstractions.
2. **Technology choices** — framework for the API layer, database (stay SQLite or move to Postgres?), task scheduling (stay launchd or move to something like Celery/APScheduler?), frontend decision.
3. **Data model spec** — what does the canonical internal time series look like? How do indicators, countries, sources, and observations relate?
4. **Migration plan** — what do I build first, second, third? What can I extract from v1 vs rebuild? Concrete phases with deliverables.
5. **Monetization architecture** — auth, user management, subscription tiers, what's free vs paid. Just the technical architecture, not business strategy.

Be direct. Tell me where my instincts are wrong. I'd rather hear "that's overengineered for a solo dev" than build something I can't maintain.
