"""Full pipeline execution: seed -> ingest -> quality -> score -> alert -> LLM -> digest.

This is the end-to-end daily pipeline. Each stage logs its progress
and errors are caught per-source/per-country so one failure doesn't
block the rest.

Usage:
    cd hornet && .venv/bin/python scripts/run_pipeline.py

Requires:
    - Postgres running (docker-compose up)
    - HORNET_FRED_API_KEY in .env
    - Ollama running locally (for LLM narratives)
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import uuid

from hornet.alerts.digest import compose_digest, render_digest_text
from hornet.alerts.dispatcher import dispatch
from hornet.alerts.tier import assign_tier
from hornet.db.repos.alert_record import list_prior_records, upsert_alert_records
from hornet.db.repos.country import list_countries
from hornet.db.repos.event_record import list_events_for_scoring
from hornet.db.repos.llm_response import upsert_llm_response
from hornet.db.repos.observation import list_observations_for_scoring
from hornet.db.repos.pipeline_run import mark_stage_completed, upsert_pipeline_run
from hornet.db.repos.score_result import upsert_score_results
from hornet.db.session import dispose_engine, session_scope
from hornet.derived.spreads import DEFAULT_SPREADS, compute_spreads
from hornet.domain.observation import Observation
from hornet.domain.pipeline import PipelineRun, RunStatus, RunType
from hornet.domain.source import FetchRequest
from hornet.ingest.factory import (
    build_bis_adapter,
    build_fred_adapter,
    build_gdelt_adapter,
    build_googlenews_adapter,
    build_imf_adapter,
    build_oecd_adapter,
    build_worldbank_adapter,
    build_yfinance_adapter,
)
from hornet.ingest.runner import run_event_ingest, run_ingest
from hornet.quality.runner import run_quality_checks
from hornet.scoring.engine import ScoringEngine
from hornet.seeds.loader import (
    load_alert_config_from_yaml,
    load_llm_config_from_yaml,
    load_scoring_config_from_yaml,
    load_source_indicators_from_yaml,
    seed_all,
)

PILOT_COUNTRIES = ["NGA", "TUR", "ZAF", "BRA", "POL"]
# USA is included in the ingest set for global signals (Treasury yields,
# commodities, VIX, etc.) but not in the scoring/alert set.
INGEST_COUNTRIES = [*PILOT_COUNTRIES, "USA"]


def _log(stage: str, msg: str) -> None:
    ts = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S")
    print(f"[{ts}] [{stage:12s}] {msg}")


async def main() -> None:
    run_id = uuid.uuid4().hex[:16]
    today = datetime.date.today()
    now = datetime.datetime.now(datetime.UTC)

    print("=" * 70)
    print(f"HORNET PIPELINE  |  run_id: {run_id}  |  date: {today}")
    print("=" * 70)

    # Create pipeline run record
    pipeline_run = PipelineRun(
        run_id=run_id,
        run_type=RunType.MANUAL,
        started_at=now,
        status=RunStatus.RUNNING,
    )
    async with session_scope() as session:
        await upsert_pipeline_run(session, pipeline_run)

    try:
        # =============================================================
        # Stage 1: SEED
        # =============================================================
        _log("seed", "Seeding registry tables...")
        async with session_scope() as session:
            n_countries, n_indicators = await seed_all(session=session)
        _log("seed", f"Seeded {n_countries} countries, {n_indicators} indicators")

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, "seed")

        # =============================================================
        # Stage 2: INGEST (all sources)
        # =============================================================
        _log("ingest", "Building adapters...")
        async with session_scope() as session:
            fred = await build_fred_adapter(session)
            worldbank = await build_worldbank_adapter(session)
            yfinance = await build_yfinance_adapter(session)
            oecd = await build_oecd_adapter(session)
            bis = await build_bis_adapter(session)
            imf = await build_imf_adapter(session)
            gdelt = await build_gdelt_adapter(session)
            googlenews = await build_googlenews_adapter(session)

        # Numeric sources (produce Observations)
        numeric_adapters = [
            ("FRED", fred),
            ("WorldBank", worldbank),
            ("yfinance", yfinance),
            ("OECD", oecd),
            ("BIS", bis),
            ("IMF", imf),
        ]

        # Event sources (produce EventRecords)
        event_adapters = [
            ("GDELT", gdelt),
            ("GoogleNews", googlenews),
        ]

        # Adapters run concurrently: each has its own rate limiter, HTTP
        # session, and DB session, so wall time is max() not sum().
        async def _fetch_numeric(name: str, adapter: object) -> int:
            _log("ingest", f"Fetching {name}...")
            try:
                req = FetchRequest(
                    source_id=adapter.source_id,  # type: ignore[attr-defined]
                    countries_iso3=frozenset(INGEST_COUNTRIES),
                    start=datetime.date(2020, 1, 1),
                )
                result = await run_ingest(adapter, req)  # type: ignore[arg-type]
                _log(
                    "ingest",
                    f"  {name}: {result.observations_fetched} fetched, {result.observations_written} written",
                )
                return result.observations_written
            except Exception as e:
                _log("ingest", f"  {name}: FAILED -- {type(e).__name__}: {e!s:.100}")
                return 0

        async def _fetch_event(name: str, adapter: object) -> int:
            _log("ingest", f"Fetching {name}...")
            try:
                req = FetchRequest(
                    source_id=adapter.source_id,  # type: ignore[attr-defined]
                    countries_iso3=frozenset(INGEST_COUNTRIES),
                )
                events = await adapter.fetch_events(req)  # type: ignore[attr-defined]
                result = await run_event_ingest(adapter.source_id, events)  # type: ignore[attr-defined]
                _log(
                    "ingest",
                    f"  {name}: {result.events_received} received, {result.events_written} written",
                )
                return result.events_written
            except Exception as e:
                _log("ingest", f"  {name}: FAILED -- {type(e).__name__}: {e!s:.100}")
                return 0

        numeric_task = asyncio.gather(
            *(_fetch_numeric(name, adapter) for name, adapter in numeric_adapters)
        )
        event_task = asyncio.gather(
            *(_fetch_event(name, adapter) for name, adapter in event_adapters)
        )
        numeric_counts, event_counts = await asyncio.gather(numeric_task, event_task)
        total_obs = sum(numeric_counts)
        total_events = sum(event_counts)

        _log("ingest", f"Total: {total_obs} observations, {total_events} events written")

        # Compute and persist spreads
        _log("ingest", "Computing yield spreads...")
        async with session_scope() as session:
            usa_obs = await list_observations_for_scoring(session, country_iso3="USA")
        spread_obs = compute_spreads(usa_obs, DEFAULT_SPREADS)
        if spread_obs:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            from hornet.db.models.observation import ObservationRow

            values = [
                {
                    "country_iso3": o.country_iso3,
                    "indicator_code": o.indicator_code,
                    "source_id": o.source_id,
                    "date": o.date,
                    "value": o.value,
                    "frequency": o.frequency,
                    "vintage": o.vintage,
                    "ingested_at": o.ingested_at,
                    "quality_flags": list(o.quality_flags),
                }
                for o in spread_obs
            ]
            async with session_scope() as session:
                stmt = (
                    pg_insert(ObservationRow)
                    .values(values)
                    .on_conflict_do_nothing(
                        index_elements=[
                            "country_iso3",
                            "indicator_code",
                            "source_id",
                            "date",
                            "vintage",
                        ],
                    )
                )
                await session.execute(stmt)
            _log("ingest", f"  Spreads: {len(spread_obs)} computed")

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, "ingest")

        # =============================================================
        # Stage 3: QUALITY
        # =============================================================
        _log("quality", "Running quality checks...")
        async with session_scope() as session:
            quality_issues = await run_quality_checks(session, reference_date=today)
        n_critical = sum(1 for i in quality_issues if i.severity == "critical")
        n_warning = sum(1 for i in quality_issues if i.severity == "warning")
        _log(
            "quality",
            f"  {len(quality_issues)} issues ({n_critical} critical, {n_warning} warning)",
        )

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, "quality")

        # =============================================================
        # Stage 4: SCORE
        # =============================================================
        import time as _time

        _log("score", "Scoring pilot countries...")
        scoring_config = load_scoring_config_from_yaml()
        indicator_specs = load_source_indicators_from_yaml()
        engine = ScoringEngine(scoring_config, indicator_specs)

        async with session_scope() as session:
            countries = await list_countries(session)
            country_names = {c.iso3: c.name for c in countries}
            country_regions = {c.iso3: c.region for c in countries}

        # Per-country loop: load, score, log, discard. Bounds peak memory to
        # ~30-50MB (one country's obs) instead of holding all 183 in RAM.
        score_results = []
        for iso3 in PILOT_COUNTRIES:
            async with session_scope() as session:
                obs = await list_observations_for_scoring(session, country_iso3=iso3)
                evts = await list_events_for_scoring(session, country_iso3=iso3)
            t0 = _time.perf_counter()
            sr = engine.score_country(iso3, obs, evts, today)
            elapsed = _time.perf_counter() - t0
            score_results.append(sr)
            comp = f"{sr.composite:+.2f}" if sr.composite is not None else "N/A"
            _log(
                "score",
                f"  {sr.country_iso3}: composite={comp}, coverage={sr.coverage_fraction:.0%}, {elapsed:.2f}s",
            )

        # Single bulk upsert at end
        async with session_scope() as session:
            n_scores = await upsert_score_results(session, score_results)
        _log("score", f"  {n_scores} countries scored")

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, "score")

        # =============================================================
        # Stage 5: ALERT
        # =============================================================
        _log("alert", "Evaluating alert tiers...")
        alert_config = load_alert_config_from_yaml()
        scores_by_country = {sr.country_iso3: sr for sr in score_results}

        assignments = []
        for sr in score_results:
            async with session_scope() as session:
                prior = await list_prior_records(session, sr.country_iso3)
            assignment = assign_tier(
                sr,
                alert_config,
                country_name=country_names.get(sr.country_iso3, sr.country_iso3),
                region=country_regions.get(sr.country_iso3),
                prior_records=prior,
            )
            assignments.append(assignment)
            tier_str = assignment.effective_tier.value if assignment.effective_tier else "none"
            _log("alert", f"  {sr.country_iso3}: {tier_str}")

        dispatch_result = dispatch(assignments, alert_config)

        # Persist alert records
        async with session_scope() as session:
            await upsert_alert_records(session, assignments)

        _log(
            "alert",
            f"  ESCALATE: {len(dispatch_result.escalate)}, ALERT: {len(dispatch_result.alert)}, WATCH: {len(dispatch_result.watch)}",
        )

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, "alert")

        # =============================================================
        # Stage 6: LLM
        # =============================================================
        _log("llm", "Generating narratives...")
        llm_config = load_llm_config_from_yaml()

        # Check if Ollama is reachable before attempting LLM stage
        import httpx

        ollama_available = False
        try:
            resp = httpx.get(f"{llm_config.ollama.base_url}/api/tags", timeout=5)
            ollama_available = resp.status_code == 200
        except Exception:
            pass

        if ollama_available:
            from hornet.llm.providers.ollama import OllamaProvider
            from hornet.llm.router import LLMRouter
            from hornet.llm.runner import run_llm_stage

            # Reload obs/events only for dispatched countries (escalate/alert/
            # watch). Score stage no longer pre-builds these dicts; we fetch
            # on-demand for the (typically small) dispatched set.
            dispatched_iso3s = {
                a.country_iso3
                for tier_list in (
                    dispatch_result.escalate,
                    dispatch_result.alert,
                    dispatch_result.watch,
                )
                for a in tier_list
            }
            observations_by_country: dict[str, list[Observation]] = {}
            events_by_country: dict[str, list[object]] = {}
            if dispatched_iso3s:
                async with session_scope() as session:
                    for iso3 in dispatched_iso3s:
                        observations_by_country[iso3] = await list_observations_for_scoring(
                            session, country_iso3=iso3
                        )
                        events_by_country[iso3] = await list_events_for_scoring(
                            session, country_iso3=iso3
                        )

            ollama_provider = OllamaProvider(llm_config.ollama)
            # Claude provider requires API key -- skip if not configured
            providers: dict[str, object] = {"ollama": ollama_provider}

            from hornet.config import get_settings

            settings = get_settings()
            if settings.anthropic_api_key:
                from hornet.llm.providers.claude import ClaudeProvider

                claude_provider = ClaudeProvider(
                    llm_config.claude,
                    api_key=settings.anthropic_api_key.get_secret_value(),
                )
                providers["claude"] = claude_provider

            router = LLMRouter(llm_config, providers)  # type: ignore[arg-type]

            llm_result = await run_llm_stage(
                router=router,
                dispatch=dispatch_result,
                observations_by_country=observations_by_country,
                scores_by_country=scores_by_country,
                events_by_country=events_by_country,
                country_names=country_names,
                run_id=run_id,
                reference_date=today,
            )

            # Persist LLM responses
            async with session_scope() as session:
                for resp in [*llm_result.narratives, *llm_result.rationales]:
                    await upsert_llm_response(session, resp)

            _log(
                "llm",
                f"  {len(llm_result.narratives)} narratives, {len(llm_result.rationales)} rationales",
            )
            _log("llm", f"  {llm_result.total_errors} errors")

            for nr in llm_result.narratives:
                _log("llm", f"  {nr.country_iso3}: grounding={nr.grounding_score:.0%}")

            await ollama_provider.close()
        else:
            _log("llm", "  Ollama not available -- skipping LLM stage")

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, "llm")

        # =============================================================
        # Stage 7: DIGEST
        # =============================================================
        _log("digest", "Composing digest...")
        digest = compose_digest(
            dispatch_result,
            quality_issues,
            score_results,
            run_id,
        )
        digest_text = render_digest_text(digest)

        _log(
            "digest",
            f"  {digest.summary.total_scored} countries, "
            f"{digest.summary.n_escalate} escalate, "
            f"{digest.summary.n_alert} alert, "
            f"{digest.summary.n_watch} watch",
        )

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, "digest")

        # Mark pipeline complete
        completed_run = PipelineRun(
            run_id=run_id,
            run_type=RunType.MANUAL,
            started_at=pipeline_run.started_at,
            completed_at=datetime.datetime.now(datetime.UTC),
            status=RunStatus.COMPLETED,
            stages_completed=("seed", "ingest", "quality", "score", "alert", "llm", "digest"),
            n_countries_scored=len(score_results),
            n_escalate=len(dispatch_result.escalate),
            n_alert=len(dispatch_result.alert),
            n_watch=len(dispatch_result.watch),
        )
        async with session_scope() as session:
            await upsert_pipeline_run(session, completed_run)

        print()
        print("=" * 70)
        print("PIPELINE COMPLETE")
        print("=" * 70)
        print()
        print(digest_text)

    except Exception as e:
        _log("ERROR", f"{type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()

        failed_run = PipelineRun(
            run_id=run_id,
            run_type=RunType.MANUAL,
            started_at=pipeline_run.started_at,
            completed_at=datetime.datetime.now(datetime.UTC),
            status=RunStatus.FAILED,
            error_message=str(e)[:500],
        )
        async with session_scope() as session:
            await upsert_pipeline_run(session, failed_run)

        sys.exit(1)

    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
