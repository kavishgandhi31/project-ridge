"""Live data validation: pull all FRED and yfinance indicators, report results.

Requires:
- RIDGE_FRED_API_KEY set in .env
- Postgres running (seeds the registry, stores observations)
- Docker compose up for TimescaleDB

Usage:
    cd api && .venv/bin/python scripts/validate_live_data.py
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import time

from ridge.config import get_settings
from ridge.db.session import dispose_engine, session_scope
from ridge.derived.spreads import DEFAULT_SPREADS, compute_spreads
from ridge.domain.observation import Observation
from ridge.domain.source import FetchRequest, SourceIndicatorSpec
from ridge.quality.liveness import check_series_liveness
from ridge.seeds.loader import (
    load_source_indicators_from_yaml,
    seed_all,
)


async def _fetch_fred(
    specs: list[SourceIndicatorSpec],
) -> tuple[list[Observation], list[dict[str, str]]]:
    """Pull all FRED indicators."""
    from ridge.adapters.fred import FredAdapter

    settings = get_settings()
    api_key = settings.fred_api_key
    if api_key is None:
        print("ERROR: RIDGE_FRED_API_KEY not set")
        return [], [{"source": "fred", "error": "no API key"}]

    # Build adapter with indicator specs
    fred_specs = [s for s in specs if s.source_id == "fred" and s.enabled]
    adapter = FredAdapter(api_key=api_key.get_secret_value(), indicators=fred_specs)

    observations: list[Observation] = []
    errors: list[dict[str, str]] = []

    # Fetch one indicator at a time so we can report per-series
    for spec in fred_specs:
        request = FetchRequest(
            source_id="fred",
            countries_iso3=spec.countries_iso3,
            indicator_codes=frozenset({spec.indicator_code}),
            start=datetime.date(2024, 1, 1),
        )
        try:
            start = time.monotonic()
            result = await adapter.fetch(request)
            elapsed = int((time.monotonic() - start) * 1000)

            if result:
                latest = max(o.date for o in result)
                observations.extend(result)
                print(
                    f"  OK   {spec.source_native_code:25s} -> {spec.indicator_code:25s} "
                    f"| {len(result):4d} obs | latest: {latest} | {elapsed}ms"
                )
            else:
                print(
                    f"  EMPTY {spec.source_native_code:24s} -> {spec.indicator_code:25s} "
                    f"| 0 obs | {elapsed}ms"
                )
                errors.append(
                    {
                        "source": "fred",
                        "native_code": spec.source_native_code,
                        "indicator": spec.indicator_code,
                        "error": "empty response",
                    }
                )
        except Exception as e:
            print(
                f"  FAIL {spec.source_native_code:24s} -> {spec.indicator_code:25s} "
                f"| {type(e).__name__}: {str(e)[:80]}"
            )
            errors.append(
                {
                    "source": "fred",
                    "native_code": spec.source_native_code,
                    "indicator": spec.indicator_code,
                    "error": str(e)[:200],
                }
            )

    return observations, errors


async def _fetch_yfinance(
    specs: list[SourceIndicatorSpec],
) -> tuple[list[Observation], list[dict[str, str]]]:
    """Pull all yfinance indicators."""
    from ridge.adapters.yfinance_adapter import YFinanceAdapter

    yf_specs = [s for s in specs if s.source_id == "yfinance" and s.enabled]
    adapter = YFinanceAdapter(indicators=yf_specs)

    observations: list[Observation] = []
    errors: list[dict[str, str]] = []

    for spec in yf_specs:
        request = FetchRequest(
            source_id="yfinance",
            countries_iso3=spec.countries_iso3,
            indicator_codes=frozenset({spec.indicator_code}),
            start=datetime.date(2024, 1, 1),
        )
        try:
            start = time.monotonic()
            result = await adapter.fetch(request)
            elapsed = int((time.monotonic() - start) * 1000)

            if result:
                latest = max(o.date for o in result)
                observations.extend(result)
                print(
                    f"  OK   {spec.source_native_code:25s} -> {spec.indicator_code:25s} "
                    f"| {len(result):4d} obs | latest: {latest} | {elapsed}ms"
                )
            else:
                print(
                    f"  EMPTY {spec.source_native_code:24s} -> {spec.indicator_code:25s} "
                    f"| 0 obs | {elapsed}ms"
                )
                errors.append(
                    {
                        "source": "yfinance",
                        "native_code": spec.source_native_code,
                        "indicator": spec.indicator_code,
                        "error": "empty response",
                    }
                )
        except Exception as e:
            print(
                f"  FAIL {spec.source_native_code:24s} -> {spec.indicator_code:25s} "
                f"| {type(e).__name__}: {str(e)[:80]}"
            )
            errors.append(
                {
                    "source": "yfinance",
                    "native_code": spec.source_native_code,
                    "indicator": spec.indicator_code,
                    "error": str(e)[:200],
                }
            )

    return observations, errors


async def main() -> None:
    print("=" * 80)
    print("LIVE DATA VALIDATION")
    print(f"Date: {datetime.date.today().isoformat()}")
    print("=" * 80)

    # 1. Seed the registry
    print("\n--- Seeding registry ---")
    async with session_scope() as session:
        n_countries, n_indicators = await seed_all(session=session)
    print(f"Seeded {n_countries} countries, {n_indicators} indicators")

    specs = load_source_indicators_from_yaml()

    # 2. Pull FRED
    print(f"\n--- FRED ({sum(1 for s in specs if s.source_id == 'fred')} indicators) ---")
    fred_obs, fred_errors = await _fetch_fred(specs)

    # 3. Pull yfinance
    print(f"\n--- yfinance ({sum(1 for s in specs if s.source_id == 'yfinance')} indicators) ---")
    yf_obs, yf_errors = await _fetch_yfinance(specs)

    all_obs = fred_obs + yf_obs
    all_errors = fred_errors + yf_errors

    # 4. Compute spreads from real Treasury data
    print("\n--- Spread builder ---")
    treasury_obs = [o for o in all_obs if o.source_id == "fred" and o.country_iso3 == "USA"]
    spread_obs = compute_spreads(treasury_obs, DEFAULT_SPREADS)
    for spec in DEFAULT_SPREADS:
        spread_for_spec = [o for o in spread_obs if o.indicator_code == spec.result_code]
        if spread_for_spec:
            latest = max(o.date for o in spread_for_spec)
            latest_val = next(o.value for o in spread_for_spec if o.date == latest)
            print(
                f"  {spec.result_code:25s} | {len(spread_for_spec):4d} points "
                f"| latest: {latest} = {latest_val:+.3f}%"
            )
        else:
            print(f"  {spec.result_code:25s} | NO DATA (missing leg)")

    # 5. Liveness check
    print("\n--- Liveness check ---")
    fred_yf_specs = [s for s in specs if s.source_id in ("fred", "yfinance")]
    issues = check_series_liveness(
        all_obs,
        fred_yf_specs,
        reference_date=datetime.date.today(),
    )
    if issues:
        for issue in issues:
            print(f"  STALE  {issue.source_id}/{issue.indicator_code}: {issue.message}")
    else:
        print(f"  All {len(fred_yf_specs)} FRED/yfinance series are live")

    # 6. Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total observations pulled: {len(all_obs):,}")
    print(f"  FRED:     {len(fred_obs):,}")
    print(f"  yfinance: {len(yf_obs):,}")
    print(f"  Spreads:  {len(spread_obs):,}")
    print(f"Errors: {len(all_errors)}")
    for err in all_errors:
        print(f"  {err['source']}/{err.get('native_code', '?')}: {err['error'][:100]}")
    print(f"Liveness issues: {len(issues)}")

    success = len(all_errors) == 0
    print(f"\n{'VALIDATION PASSED' if success else 'VALIDATION HAS ISSUES'}")
    print(f"{'=' * 80}")

    await dispose_engine()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
