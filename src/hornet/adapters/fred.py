"""FRED data source adapter — ports v1's FredClient to Hornet.

Loads macroeconomic time series from the St. Louis Fed's FRED REST API
and normalizes them to canonical Observation records. The parsing
quirks (dot-for-missing, string dates, annual 20-year lookback) are
ported verbatim from v1's ``src/ingestion/fred_client.py``.

Phase 1 uses a hardcoded series dictionary for the 5 pilot countries
(NGA, TUR, ZAF, BRA, POL) — just enough to prove the adapter works
end-to-end against the canonical schema. Production config moves to
a DB-backed ``source_indicator`` table in Phase 2.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

import httpx
import pandas as pd
import structlog

from hornet.adapters.base import HealthReport
from hornet.adapters.base_client import BaseClient
from hornet.domain import (
    FetchRequest,
    Frequency,
    IndicatorSpec,
    Observation,
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


@dataclass(frozen=True)
class _SeriesSpec:
    """Hardcoded metadata for a single FRED series.

    Phase 1 fixture data only — moves to the ``source_indicator`` DB
    table in Phase 2.
    """

    fred_id: str
    """Native FRED series ID (e.g. 'FPCPITOTLZGNGA')."""

    indicator_code: str
    """Canonical Hornet indicator code (e.g. 'CPI_YOY')."""

    frequency: Frequency
    """Observation frequency tier, drives lookback window."""


_PILOT_SERIES: dict[str, list[_SeriesSpec]] = {
    "NGA": [
        _SeriesSpec("FPCPITOTLZGNGA", "CPI_YOY", "annual"),
        _SeriesSpec("NGANGDPRPCH", "GDP_GROWTH", "annual"),
    ],
    "TUR": [
        _SeriesSpec("FPCPITOTLZGTUR", "CPI_YOY", "annual"),
        _SeriesSpec("TURNGDPRPCH", "GDP_GROWTH", "annual"),
    ],
    "ZAF": [
        _SeriesSpec("FPCPITOTLZGZAF", "CPI_YOY", "annual"),
        _SeriesSpec("ZAFNGDPRPCH", "GDP_GROWTH", "annual"),
    ],
    "BRA": [
        _SeriesSpec("FPCPITOTLZGBRA", "CPI_YOY", "annual"),
        _SeriesSpec("BRANGDPRPCH", "GDP_GROWTH", "annual"),
    ],
    "POL": [
        _SeriesSpec("FPCPITOTLZGPOL", "CPI_YOY", "annual"),
        _SeriesSpec("POLNGDPRPCH", "GDP_GROWTH", "annual"),
    ],
}


class FredAdapter(BaseClient):
    """Fetches FRED time series and yields canonical Observations.

    Satisfies the ``SourceAdapter`` protocol (``discover``, ``fetch``,
    ``health``). Inherits HTTP session, rate limiting, and retries
    from ``BaseClient``.
    """

    def __init__(
        self,
        api_key: str,
        requests_per_minute: int = 60,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id="fred",
            base_url=FRED_BASE_URL,
            requests_per_minute=requests_per_minute,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )
        self._api_key = api_key

    async def discover(self) -> SourceManifest:
        """Return a SourceManifest listing every (country, indicator) pair.

        Phase 1: derived from ``_PILOT_SERIES``. Each FRED series is
        country-specific (the ISO3 is encoded in the series ID), so we
        emit one ``IndicatorSpec`` per pair rather than aggregating.
        """
        specs: list[IndicatorSpec] = []
        for iso3, series_list in _PILOT_SERIES.items():
            for series in series_list:
                specs.append(
                    IndicatorSpec(
                        indicator_code=series.indicator_code,
                        source_native_code=series.fred_id,
                        frequency=series.frequency,
                        countries_iso3=frozenset({iso3}),
                    )
                )
        return SourceManifest(
            source_id=self.source_id,
            indicators=tuple(specs),
            discovered_at=datetime.datetime.now(datetime.UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        """Fetch observations for the requested country/indicator scope.

        Empty ``countries_iso3`` means "all pilot countries." Empty
        ``indicator_codes`` means "all indicators each country has."
        Unknown countries are silently skipped. Series that fail to
        fetch (404, timeout, etc.) return an empty DataFrame and
        contribute zero observations — one broken series never tanks
        the whole fetch.
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        countries = request.countries_iso3 or frozenset(_PILOT_SERIES.keys())

        results: list[Observation] = []
        for iso3 in countries:
            if iso3 not in _PILOT_SERIES:
                logger.debug("fred.fetch.unknown_country", iso3=iso3)
                continue

            for series in _PILOT_SERIES[iso3]:
                if request.indicator_codes and series.indicator_code not in request.indicator_codes:
                    continue

                df = await self._fetch_series(
                    series.fred_id,
                    series.frequency,
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
                            indicator_code=series.indicator_code,
                            source_id=self.source_id,
                            date=obs_date,
                            value=float(row["value"]),
                            frequency=series.frequency,
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
            else datetime.datetime.now().strftime(FRED_DATE_FORMAT)
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
        cutoff = datetime.datetime.now() - datetime.timedelta(days=years * 365)
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
