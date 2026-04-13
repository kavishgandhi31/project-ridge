"""Hornet CLI -- modular pipeline execution.

Usage examples:
    # Full pipeline (all stages, pilot countries)
    hornet run

    # Ingest only, specific sources
    hornet run --stages ingest --sources fred,yfinance

    # Score and alert without re-ingesting
    hornet run --stages score,alert

    # Ingest specific category
    hornet run --stages ingest --sources treasuries
    hornet run --stages ingest --sources commodities
    hornet run --stages ingest --sources macro
    hornet run --stages ingest --sources news

    # All countries (not just pilots)
    hornet run --all-countries

Launch:
    cd hornet && .venv/bin/python -m hornet.cli run
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import uuid
from typing import Annotated, Any

import typer

app = typer.Typer(
    name="hornet",
    help="Hornet macro risk pipeline CLI.",
    no_args_is_help=True,
)

# Source category aliases
SOURCE_CATEGORIES: dict[str, list[str]] = {
    "treasuries": ["fred"],  # Treasury yields are all FRED
    "commodities": ["fred", "yfinance"],  # FRED spot + yfinance futures
    "macro": ["fred", "worldbank", "imf", "oecd", "bis"],
    "markets": ["fred", "yfinance"],  # yields, FX, equity, commodities
    "news": ["gdelt", "googlenews"],
    "all": ["fred", "worldbank", "yfinance", "oecd", "bis", "imf", "gdelt", "googlenews"],
}

ALL_STAGES = ["seed", "ingest", "quality", "score", "alert", "llm", "digest"]
PILOT_COUNTRIES = [
    "NGA",
    "TUR",
    "ZAF",
    "BRA",
    "POL",  # original 5
    "MEX",
    "IND",
    "IDN",
    "CHL",
    "THA",  # EM with deep data
    "EGY",
    "KEN",
    "SAU",
    "CZE",
    "COL",  # FM/EM diversity
]


def _export_score_history(score_results: list[Any], run_id: str, run_date: datetime.date) -> None:
    """Append scores to a CSV file for easy analysis.

    Creates hornet/logs/score_history.csv with one row per country per run.
    Appends on each run so the file grows as a time series.
    """
    import csv
    from pathlib import Path

    csv_path = Path("logs/score_history.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists()

    with open(csv_path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                [
                    "run_id",
                    "run_date",
                    "scored_at",
                    "country_iso3",
                    "composite",
                    "coverage",
                    "growth_momentum",
                    "external_balance",
                    "monetary_stance",
                    "risk_sentiment",
                    "news_heat_sigma",
                ]
            )
        for sr in score_results:
            dims = sr.dimensions if hasattr(sr, "dimensions") else {}
            writer.writerow(
                [
                    run_id,
                    run_date.isoformat(),
                    sr.scored_at.isoformat() if hasattr(sr, "scored_at") else "",
                    sr.country_iso3,
                    f"{sr.composite:.4f}" if sr.composite is not None else "",
                    f"{sr.coverage_fraction:.2f}",
                    f"{dims.get('growth_momentum', type('', (), {'value': None})).value:.4f}"
                    if dims.get("growth_momentum") and dims["growth_momentum"].value is not None
                    else "",
                    f"{dims.get('external_balance', type('', (), {'value': None})).value:.4f}"
                    if dims.get("external_balance") and dims["external_balance"].value is not None
                    else "",
                    f"{dims.get('monetary_stance', type('', (), {'value': None})).value:.4f}"
                    if dims.get("monetary_stance") and dims["monetary_stance"].value is not None
                    else "",
                    f"{dims.get('risk_sentiment', type('', (), {'value': None})).value:.4f}"
                    if dims.get("risk_sentiment") and dims["risk_sentiment"].value is not None
                    else "",
                    f"{sr.news_heat.sigma:.2f}" if sr.news_heat else "",
                ]
            )


def _resolve_sources(sources_str: str) -> list[str]:
    """Resolve source names, expanding category aliases."""
    result: list[str] = []
    for token in sources_str.split(","):
        token = token.strip().lower()
        if token in SOURCE_CATEGORIES:
            result.extend(SOURCE_CATEGORIES[token])
        else:
            result.append(token)
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for s in result:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def _resolve_stages(stages_str: str) -> list[str]:
    """Parse comma-separated stage names."""
    stages = [s.strip().lower() for s in stages_str.split(",")]
    for s in stages:
        if s not in ALL_STAGES:
            typer.echo(f"Unknown stage: {s}. Valid: {', '.join(ALL_STAGES)}", err=True)
            raise typer.Exit(1)
    return stages


@app.command()
def run(
    stages: Annotated[
        str,
        typer.Option("--stages", "-s", help="Comma-separated stages to run. Default: all"),
    ] = "all",
    sources: Annotated[
        str,
        typer.Option(
            "--sources",
            help="Comma-separated sources or categories: fred,yfinance,treasuries,commodities,macro,markets,news,all",
        ),
    ] = "all",
    all_countries: Annotated[
        bool,
        typer.Option("--all-countries", help="Score all 183 countries (default: 5 pilots only)"),
    ] = False,
    skip_llm: Annotated[
        bool,
        typer.Option("--skip-llm", help="Skip LLM narrative generation"),
    ] = False,
) -> None:
    """Run the Hornet pipeline with optional stage/source filtering."""
    # Resolve stages
    stage_list = ALL_STAGES[:] if stages == "all" else _resolve_stages(stages)

    if skip_llm and "llm" in stage_list:
        stage_list.remove("llm")

    # Resolve sources
    source_list = _resolve_sources(sources)

    typer.echo(f"Stages: {', '.join(stage_list)}")
    typer.echo(f"Sources: {', '.join(source_list)}")
    typer.echo(f"Countries: {'all 183' if all_countries else '5 pilots'}")
    typer.echo("")

    asyncio.run(_run_pipeline(stage_list, source_list, all_countries))


async def _run_pipeline(
    stages: list[str],
    sources: list[str],
    all_countries: bool,
) -> None:
    """Async pipeline execution."""
    # Import here to avoid circular imports and slow CLI startup
    from hornet.db.repos.country import list_countries
    from hornet.db.repos.pipeline_run import mark_stage_completed, upsert_pipeline_run
    from hornet.db.session import dispose_engine, session_scope
    from hornet.domain.pipeline import PipelineRun, RunStatus, RunType
    from hornet.seeds.loader import seed_all

    run_id = uuid.uuid4().hex[:16]
    today = datetime.date.today()
    now = datetime.datetime.now(datetime.UTC)

    def _log(stage: str, msg: str) -> None:
        ts = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S")
        typer.echo(f"[{ts}] [{stage:12s}] {msg}")

    # Create run record
    pipeline_run = PipelineRun(
        run_id=run_id,
        run_type=RunType.MANUAL,
        started_at=now,
        status=RunStatus.RUNNING,
    )
    async with session_scope() as session:
        await upsert_pipeline_run(session, pipeline_run)

    try:
        # --- SEED ---
        if "seed" in stages:
            _log("seed", "Seeding registry tables...")
            async with session_scope() as session:
                n_c, n_i = await seed_all(session=session)
            _log("seed", f"Seeded {n_c} countries, {n_i} indicators")
            async with session_scope() as session:
                await mark_stage_completed(session, run_id, "seed")

        # Determine scoring countries
        async with session_scope() as session:
            all_country_specs = await list_countries(session)
        country_names = {c.iso3: c.name for c in all_country_specs}
        country_regions = {c.iso3: c.region for c in all_country_specs}

        score_countries = [c.iso3 for c in all_country_specs] if all_countries else PILOT_COUNTRIES

        # USA always in ingest set for global signals
        ingest_countries = list(set([*score_countries, "USA"]))

        # --- INGEST ---
        if "ingest" in stages:
            _log("ingest", f"Ingesting from {len(sources)} sources...")
            await _run_ingest(sources, ingest_countries, _log)
            async with session_scope() as session:
                await mark_stage_completed(session, run_id, "ingest")

        # --- QUALITY ---
        if "quality" in stages:
            from hornet.quality.runner import run_quality_checks

            _log("quality", "Running quality checks...")
            async with session_scope() as session:
                quality_issues = await run_quality_checks(session, reference_date=today)
            n_crit = sum(1 for i in quality_issues if i.severity == "critical")
            n_warn = sum(1 for i in quality_issues if i.severity == "warning")
            _log("quality", f"  {len(quality_issues)} issues ({n_crit} critical, {n_warn} warning)")
            async with session_scope() as session:
                await mark_stage_completed(session, run_id, "quality")
        else:
            quality_issues = []

        # --- SCORE ---
        if "score" in stages:
            from hornet.db.repos.event_record import list_events_for_scoring
            from hornet.db.repos.observation import list_observations_for_scoring
            from hornet.db.repos.score_result import upsert_score_results
            from hornet.domain.observation import Observation
            from hornet.scoring.engine import ScoringEngine
            from hornet.seeds.loader import (
                load_scoring_config_from_yaml,
                load_source_indicators_from_yaml,
            )

            _log("score", f"Scoring {len(score_countries)} countries...")
            config = load_scoring_config_from_yaml()
            specs = load_source_indicators_from_yaml()
            engine = ScoringEngine(config, specs)

            obs_by_country: dict[str, list[Observation]] = {}
            events_by_country: dict[str, list[object]] = {}
            async with session_scope() as session:
                for iso3 in score_countries:
                    obs_by_country[iso3] = await list_observations_for_scoring(
                        session, country_iso3=iso3
                    )
                    events_by_country[iso3] = await list_events_for_scoring(
                        session, country_iso3=iso3
                    )

            score_results = engine.score_all(
                countries=score_countries,
                observations_by_country=obs_by_country,
                events_by_country=events_by_country,
                reference_date=today,
            )
            async with session_scope() as session:
                await upsert_score_results(session, score_results)
            for sr in score_results:
                comp = f"{sr.composite:+.2f}" if sr.composite is not None else "N/A"
                _log(
                    "score",
                    f"  {sr.country_iso3}: composite={comp}, coverage={sr.coverage_fraction:.0%}",
                )

            # Append scores to CSV history for analysis
            _export_score_history(score_results, run_id, today)
            async with session_scope() as session:
                await mark_stage_completed(session, run_id, "score")
        else:
            score_results = []

        # --- ALERT ---
        if "alert" in stages and score_results:
            from hornet.alerts.dispatcher import dispatch
            from hornet.alerts.tier import assign_tier
            from hornet.db.repos.alert_record import list_prior_records, upsert_alert_records
            from hornet.seeds.loader import load_alert_config_from_yaml

            _log("alert", "Evaluating alert tiers...")
            alert_config = load_alert_config_from_yaml()
            assignments = []
            for sr in score_results:
                async with session_scope() as session:
                    prior = await list_prior_records(session, sr.country_iso3)
                a = assign_tier(
                    sr,
                    alert_config,
                    country_name=country_names.get(sr.country_iso3, sr.country_iso3),
                    region=country_regions.get(sr.country_iso3),
                    prior_records=prior,
                )
                assignments.append(a)
                tier_str = a.effective_tier.value if a.effective_tier else "none"
                _log("alert", f"  {sr.country_iso3}: {tier_str}")

            dispatch_result = dispatch(assignments, alert_config)
            async with session_scope() as session:
                await upsert_alert_records(session, assignments)
            _log(
                "alert",
                f"  E:{len(dispatch_result.escalate)} A:{len(dispatch_result.alert)} W:{len(dispatch_result.watch)}",
            )
            async with session_scope() as session:
                await mark_stage_completed(session, run_id, "alert")
        else:
            from hornet.domain.alerting import DispatchResult

            dispatch_result = DispatchResult()

        # --- LLM ---
        if "llm" in stages and score_results:
            _log("llm", "Generating narratives...")
            await _run_llm(
                score_results,
                dispatch_result,
                obs_by_country,
                events_by_country,
                country_names,
                run_id,
                today,
                _log,
            )
            async with session_scope() as session:
                await mark_stage_completed(session, run_id, "llm")

        # --- DIGEST ---
        if "digest" in stages and score_results:
            from hornet.alerts.digest import compose_digest, render_digest_text

            _log("digest", "Composing digest...")
            digest = compose_digest(dispatch_result, quality_issues, score_results, run_id)
            digest_text = render_digest_text(digest)
            _log(
                "digest",
                f"  {digest.summary.total_scored} scored, "
                f"E:{digest.summary.n_escalate} A:{digest.summary.n_alert} W:{digest.summary.n_watch}",
            )
            async with session_scope() as session:
                await mark_stage_completed(session, run_id, "digest")
            typer.echo("")
            typer.echo(digest_text)

        # Mark complete
        completed = PipelineRun(
            run_id=run_id,
            run_type=RunType.MANUAL,
            started_at=now,
            completed_at=datetime.datetime.now(datetime.UTC),
            status=RunStatus.COMPLETED,
            stages_completed=tuple(stages),
            n_countries_scored=len(score_results),
            n_escalate=len(dispatch_result.escalate),
            n_alert=len(dispatch_result.alert),
            n_watch=len(dispatch_result.watch),
        )
        async with session_scope() as session:
            await upsert_pipeline_run(session, completed)
        _log("done", "Pipeline complete.")

    except Exception as e:
        _log("ERROR", f"{type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        failed = PipelineRun(
            run_id=run_id,
            run_type=RunType.MANUAL,
            started_at=now,
            completed_at=datetime.datetime.now(datetime.UTC),
            status=RunStatus.FAILED,
            error_message=str(e)[:500],
        )
        async with session_scope() as session:
            await upsert_pipeline_run(session, failed)
        sys.exit(1)
    finally:
        await dispose_engine()


async def _run_ingest(
    sources: list[str],
    countries: list[str],
    _log: Any,
) -> None:
    """Run ingest for selected sources."""
    from hornet.db.session import session_scope
    from hornet.derived.spreads import DEFAULT_SPREADS, compute_spreads
    from hornet.domain.source import FetchRequest
    from hornet.ingest.runner import run_event_ingest, run_ingest
    from hornet.quality.coverage import filter_countries_for_source

    log = _log  # type: ignore[assignment]
    country_set = frozenset(countries)

    # Build adapters for requested sources
    adapters: dict[str, object] = {}
    async with session_scope() as session:
        if "fred" in sources:
            from hornet.ingest.factory import build_fred_adapter

            adapters["fred"] = await build_fred_adapter(session)
        if "worldbank" in sources:
            from hornet.ingest.factory import build_worldbank_adapter

            adapters["worldbank"] = await build_worldbank_adapter(session)
        if "yfinance" in sources:
            from hornet.ingest.factory import build_yfinance_adapter

            adapters["yfinance"] = await build_yfinance_adapter(session)
        if "oecd" in sources:
            from hornet.ingest.factory import build_oecd_adapter

            adapters["oecd"] = await build_oecd_adapter(session)
        if "bis" in sources:
            from hornet.ingest.factory import build_bis_adapter

            adapters["bis"] = await build_bis_adapter(session)
        if "imf" in sources:
            from hornet.ingest.factory import build_imf_adapter

            adapters["imf"] = await build_imf_adapter(session)
        if "gdelt" in sources:
            from hornet.ingest.factory import build_gdelt_adapter

            adapters["gdelt"] = await build_gdelt_adapter(session)
        if "googlenews" in sources:
            from hornet.ingest.factory import build_googlenews_adapter

            adapters["googlenews"] = await build_googlenews_adapter(session)

    # Numeric sources
    numeric_sources = ["fred", "worldbank", "yfinance", "oecd", "bis", "imf"]
    total_obs = 0
    for src in numeric_sources:
        adapter = adapters.get(src)
        if adapter is None:
            continue
        # Filter countries for sources with limited coverage
        filtered = filter_countries_for_source(src, countries)
        log("ingest", f"Fetching {src} ({len(filtered)} countries)...")  # type: ignore[operator]
        try:
            req = FetchRequest(
                source_id=src,
                countries_iso3=frozenset(filtered),
                start=datetime.date(2020, 1, 1),
            )
            result = await run_ingest(adapter, req)  # type: ignore[arg-type]
            total_obs += result.observations_written
            log(
                "ingest",
                f"  {src}: {result.observations_fetched} fetched, {result.observations_written} written",
            )  # type: ignore[operator]
        except Exception as e:
            log("ingest", f"  {src}: FAILED -- {type(e).__name__}: {e!s:.100}")  # type: ignore[operator]

    # Event sources
    event_sources = ["gdelt", "googlenews"]
    total_events = 0
    for src in event_sources:
        adapter = adapters.get(src)
        if adapter is None:
            continue
        log("ingest", f"Fetching {src}...")  # type: ignore[operator]
        try:
            req = FetchRequest(
                source_id=src,
                countries_iso3=country_set,
            )
            events = await adapter.fetch_events(req)  # type: ignore[union-attr]
            result = await run_event_ingest(src, events)
            total_events += result.events_written
            log(
                "ingest",
                f"  {src}: {result.events_received} received, {result.events_written} written",
            )  # type: ignore[operator]
        except Exception as e:
            log("ingest", f"  {src}: FAILED -- {type(e).__name__}: {e!s:.100}")  # type: ignore[operator]

    log("ingest", f"Total: {total_obs} observations, {total_events} events")  # type: ignore[operator]

    # Spreads
    if "fred" in sources:
        from hornet.db.repos.observation import list_observations_for_scoring

        log("ingest", "Computing yield spreads...")  # type: ignore[operator]
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
            log("ingest", f"  Spreads: {len(spread_obs)} computed")  # type: ignore[operator]


async def _run_llm(
    score_results: list[Any],
    dispatch_result: Any,
    obs_by_country: dict[str, list[Any]],
    events_by_country: dict[str, list[Any]],
    country_names: dict[str, str],
    run_id: str,
    reference_date: datetime.date,
    _log: Any,
) -> None:
    """Run LLM stage if Ollama is available."""
    import httpx

    from hornet.db.repos.llm_response import upsert_llm_response
    from hornet.db.session import session_scope
    from hornet.llm.providers.ollama import OllamaProvider
    from hornet.llm.router import LLMRouter
    from hornet.llm.runner import run_llm_stage
    from hornet.seeds.loader import load_llm_config_from_yaml

    log = _log  # type: ignore[assignment]
    llm_config = load_llm_config_from_yaml()

    try:
        resp = httpx.get(f"{llm_config.ollama.base_url}/api/tags", timeout=5)
        if resp.status_code != 200:
            log("llm", "Ollama not available -- skipping")  # type: ignore[operator]
            return
    except Exception:
        log("llm", "Ollama not available -- skipping")  # type: ignore[operator]
        return

    ollama = OllamaProvider(llm_config.ollama)
    providers: dict[str, object] = {"ollama": ollama}

    from hornet.config import get_settings

    settings = get_settings()
    if settings.anthropic_api_key:
        from hornet.llm.providers.claude import ClaudeProvider

        providers["claude"] = ClaudeProvider(
            llm_config.claude,
            api_key=settings.anthropic_api_key.get_secret_value(),
        )

    router = LLMRouter(llm_config, providers)  # type: ignore[arg-type]
    result = await run_llm_stage(
        router=router,
        dispatch=dispatch_result,  # type: ignore[arg-type]
        observations_by_country=obs_by_country,  # type: ignore[arg-type]
        scores_by_country={sr.country_iso3: sr for sr in score_results},  # type: ignore[union-attr]
        events_by_country=events_by_country,  # type: ignore[arg-type]
        country_names=country_names,
        run_id=run_id,
        reference_date=reference_date,
    )

    async with session_scope() as session:
        for resp in [*result.narratives, *result.rationales]:  # type: ignore[misc]
            await upsert_llm_response(session, resp)

    log(
        "llm",
        f"  {len(result.narratives)} narratives, {len(result.rationales)} rationales, {result.total_errors} errors",
    )  # type: ignore[operator]
    for nr in result.narratives:
        log("llm", f"  {nr.country_iso3}: grounding={nr.grounding_score:.0%}")  # type: ignore[operator]

    await ollama.close()


if __name__ == "__main__":
    app()
