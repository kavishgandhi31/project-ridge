"""FRED data source adapter — ports v1's FredClient to Ridge.

Loads macroeconomic time series from the St. Louis Fed's FRED REST API
and normalizes them to canonical Observation records. The parsing
quirks (dot-for-missing, string dates, annual 20-year lookback) are
ported verbatim from v1's ``src/ingestion/fred_client.py``.

Phase 2 removed the hardcoded ``_PILOT_SERIES`` dict that Phase 1
shipped. The adapter now accepts a pre-loaded list of
``SourceIndicatorSpec`` in its constructor — the ingest runner loads
these from the ``source_indicator`` DB table at startup and passes
them through. The adapter itself stays pure: no DB dependency, still
trivially unit-testable with ``httpx.MockTransport``.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
import pandas as pd
import structlog

from ridge.adapters._dispatch import group_by_country, validate_indicators
from ridge.adapters.base import HealthReport
from ridge.adapters.base_client import BaseClient
from ridge.domain import (
    FetchRequest,
    Frequency,
    Observation,
    SourceIndicatorSpec,
    SourceManifest,
)

logger = structlog.get_logger(__name__)


FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_DATE_FORMAT = "%Y-%m-%d"

# Lookback windows ported from v1. Annual series need 20 years because
# downstream scoring requires at least ~12 observations for a meaningful
# z-score, and 5 years of annual data is only 5 points.
_ANNUAL_LOOKBACK_YEARS = 20
_DEFAULT_LOOKBACK_YEARS = 5


class FredAdapter(BaseClient):
    """Fetches FRED time series and yields canonical Observations.

    Satisfies the ``SourceAdapter`` protocol (``discover``, ``fetch``,
    ``health``). Inherits HTTP session, rate limiting, and retries
    from ``BaseClient``.

    The ``indicators`` parameter is the registry of series this adapter
    should expose. Every entry must have ``source_id == 'fred'`` —
    the constructor validates and skips anything else, logging a
    warning. FRED's native codes are country-coded (one country per
    series), so each spec's ``countries_iso3`` should contain exactly
    one ISO3 — multi-country specs get expanded into one
    (country, spec) pair per country internally.
    """

    source_id: str = "fred"

    def __init__(
        self,
        api_key: str,
        indicators: Sequence[SourceIndicatorSpec],
        requests_per_minute: int = 60,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id=self.source_id,
            base_url=FRED_BASE_URL,
            requests_per_minute=requests_per_minute,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )
        self._api_key = api_key
        self._indicators: tuple[SourceIndicatorSpec, ...] = tuple(
            validate_indicators(self.source_id, indicators)
        )
        self._by_country: Mapping[str, tuple[SourceIndicatorSpec, ...]] = group_by_country(
            self._indicators
        )

    async def discover(self) -> SourceManifest:
        """Return a SourceManifest listing every registered series.

        One ``IndicatorSpec`` per ``SourceIndicatorSpec`` in the
        registry — the manifest type is just a lighter shape that
        drops ``source_id``.
        """
        return SourceManifest(
            source_id=self.source_id,
            indicators=tuple(spec.to_manifest_spec() for spec in self._indicators),
            discovered_at=datetime.datetime.now(datetime.UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        """Fetch observations for the requested country/indicator scope.

        Empty ``countries_iso3`` means "all countries the adapter
        knows." Empty ``indicator_codes`` means "all indicators each
        country has." Unknown countries are silently skipped. Series
        that fail to fetch (404, timeout, etc.) return an empty
        DataFrame and contribute zero observations — one broken
        series never tanks the whole fetch.
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        countries = request.countries_iso3 or frozenset(self._by_country.keys())

        results: list[Observation] = []
        for iso3 in countries:
            specs = self._by_country.get(iso3)
            if specs is None:
                logger.debug("fred.fetch.unknown_country", iso3=iso3)
                continue

            for spec in specs:
                if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                    continue

                df = await self._fetch_series(
                    spec.source_native_code,
                    spec.frequency,
                    start=request.start,
                    end=request.end,
                )

                for _, row in df.iterrows():
                    obs_date = row["date"]
                    if isinstance(obs_date, pd.Timestamp):
                        obs_date = obs_date.date()

                    results.append(
                        Observation(
                            country_iso3=iso3,
                            indicator_code=spec.indicator_code,
                            source_id=self.source_id,
                            date=obs_date,
                            value=float(row["value"]),
                            frequency=spec.frequency,
                            vintage=ingested_at,
                            ingested_at=ingested_at,
                        )
                    )

        return results

    async def health(self) -> HealthReport:
        """Minimal health report. Phase 4 will wire real monitoring."""
        return HealthReport(source_id=self.source_id, healthy=True)

    async def _fetch_series(
        self,
        fred_id: str,
        frequency: Frequency,
        start: datetime.date | None = None,
        end: datetime.date | None = None,
    ) -> pd.DataFrame:
        """Fetch a single FRED series and return a parsed DataFrame.

        Applies v1's frequency-aware default lookback: 20 years for
        annual series, 5 years for everything else. Explicit ``start``
        and ``end`` from the request override the defaults.
        """
        start_str = (
            start.strftime(FRED_DATE_FORMAT) if start else self._compute_start_date(frequency)
        )
        end_str = (
            end.strftime(FRED_DATE_FORMAT)
            if end
            else datetime.datetime.now(datetime.UTC).strftime(FRED_DATE_FORMAT)
        )

        params: dict[str, Any] = {
            "series_id": fred_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": start_str,
            "observation_end": end_str,
        }

        try:
            raw = await self.get_json(FRED_BASE_URL, params=params)
        except Exception as exc:
            logger.warning(
                "fred.fetch.failed",
                series_id=fred_id,
                error=str(exc),
            )
            return self._empty_df()

        return self._parse(raw)

    @staticmethod
    def _compute_start_date(frequency: Frequency) -> str:
        """Return default ``observation_start`` for a given frequency."""
        years = _ANNUAL_LOOKBACK_YEARS if frequency == "annual" else _DEFAULT_LOOKBACK_YEARS
        cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=years * 365)
        return cutoff.strftime(FRED_DATE_FORMAT)

    @staticmethod
    def _parse(raw: Any) -> pd.DataFrame:
        """Parse a FRED observations response into a DataFrame.

        Ports v1's parsing quirks verbatim:

        * ``.`` (literal dot) is FRED's missing-value sentinel.
          ``pd.to_numeric(errors="coerce")`` turns it — and any other
          non-numeric string — into NaN, then ``dropna`` removes the
          rows. This is the single most load-bearing quirk: silently
          dropping "." rows is how we avoid poisoning downstream
          calculations with NaN propagation.
        * Date column is a string ``"YYYY-MM-DD"``. Pandas does not
          auto-infer datetime dtype; callers expect ``datetime64[ns]``,
          so ``pd.to_datetime`` is required.
        """
        if not isinstance(raw, dict):
            return FredAdapter._empty_df()

        observations = raw.get("observations", [])
        if not observations:
            return FredAdapter._empty_df()

        df = pd.DataFrame(observations)
        if "date" not in df.columns or "value" not in df.columns:
            return FredAdapter._empty_df()

        df = df[["date", "value"]].copy()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])
        df["date"] = pd.to_datetime(df["date"])
        return df.reset_index(drop=True)

    @staticmethod
    def _empty_df() -> pd.DataFrame:
        """Return an empty DataFrame with the right column dtypes."""
        return pd.DataFrame(
            {
                "date": pd.Series(dtype="datetime64[ns]"),
                "value": pd.Series(dtype="float64"),
            }
        )
