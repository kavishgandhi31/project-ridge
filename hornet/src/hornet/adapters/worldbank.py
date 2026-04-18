"""WorldBank data source adapter — ports v1's WorldBankClient to Hornet.

Loads annual macro indicators from the World Bank REST API and
normalizes them to canonical Observation records. Parsing quirks
(ISO2 -> ISO3 mapping, pagination with metadata-on-page-1, JSON null
handling, year-string dates) are ported verbatim from v1's
``src/ingestion/worldbank_client.py``.

Phase 2 removed the hardcoded ``_INDICATORS`` list and
``_ISO2_TO_ISO3`` map that Phase 1 shipped. The adapter now accepts
both as constructor arguments: ``indicators`` from the
``source_indicator`` DB table, ``iso2_to_iso3`` from the ``country``
registry. The adapter itself stays pure — no DB dependency, still
trivially unit-testable with an ``httpx.MockTransport`` and a literal
indicator/country fixture.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import httpx
import pandas as pd
import structlog

from hornet.adapters.base import HealthReport
from hornet.adapters.base_client import BaseClient
from hornet.domain import (
    FetchRequest,
    Observation,
    SourceIndicatorSpec,
    SourceManifest,
)

logger = structlog.get_logger(__name__)


WB_BASE_URL = "https://api.worldbank.org/v2"

# Pagination and lookback constants ported from v1. WB_START_YEAR = 2000
# gives 26 years of annual observations, which is well above the
# 12-observation minimum downstream scoring needs for meaningful
# z-scores on annual data. WB_PER_PAGE = 5000 is WB's maximum page
# size; at 190+ countries x 26 years per indicator that's 2 pages max.
WB_START_YEAR = 2000
WB_PER_PAGE = 5000


class WorldBankAdapter(BaseClient):
    """Fetches WorldBank indicators and yields canonical Observations.

    Satisfies the ``SourceAdapter`` protocol. Inherits HTTP session,
    rate limiting, and retries from ``BaseClient`` — WB rate limits
    are intentionally lower than FRED (30/min vs 60/min) because WB
    doesn't publish limits and conservative defaults avoid 429s.
    Timeout is raised to 60 seconds because WB is genuinely slow on
    multi-page indicator fetches.

    Two pre-loaded dependencies in the constructor:

    * ``indicators`` — the registry of series to expose, filtered to
      ``source_id == 'worldbank'``. Non-matching rows are dropped with
      a warning.
    * ``iso2_to_iso3`` — the country code map used at the parse
      boundary to translate WB's native ISO2 responses to canonical
      ISO3. Populated from the ``country`` table by the ingest runner.
    """

    source_id: str = "worldbank"

    def __init__(
        self,
        indicators: Sequence[SourceIndicatorSpec],
        iso2_to_iso3: Mapping[str, str],
        requests_per_minute: int = 30,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id=self.source_id,
            base_url=WB_BASE_URL,
            requests_per_minute=requests_per_minute,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )
        self._indicators: tuple[SourceIndicatorSpec, ...] = tuple(
            self._validate_indicators(indicators)
        )
        # Store as a plain dict for O(1) lookup in the parse hot path.
        self._iso2_to_iso3: dict[str, str] = {
            iso2.upper(): iso3.upper() for iso2, iso3 in iso2_to_iso3.items()
        }

    @classmethod
    def _validate_indicators(
        cls,
        indicators: Iterable[SourceIndicatorSpec],
    ) -> list[SourceIndicatorSpec]:
        """Drop any non-WB rows and log a warning if found."""
        kept: list[SourceIndicatorSpec] = []
        for spec in indicators:
            if spec.source_id != cls.source_id:
                logger.warning(
                    "worldbank.indicator.wrong_source",
                    source_id=spec.source_id,
                    native_code=spec.source_native_code,
                )
                continue
            kept.append(spec)
        return kept

    async def discover(self) -> SourceManifest:
        """Return a SourceManifest listing every registered indicator."""
        return SourceManifest(
            source_id=self.source_id,
            indicators=tuple(spec.to_manifest_spec() for spec in self._indicators),
            discovered_at=datetime.datetime.now(datetime.UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        """Fetch observations for the requested scope.

        Bulk-fetches each indicator once (one API call returns all ~190
        countries for that indicator), then filters client-side to the
        requested country set. This is vastly more efficient than
        per-country fetches: N indicators x ~2 pages is the total call
        count, regardless of how many countries are requested.
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        all_known_countries: frozenset[str] = frozenset(self._iso2_to_iso3.values())
        requested_countries = request.countries_iso3 or all_known_countries

        indicators_to_fetch = [
            spec
            for spec in self._indicators
            if not request.indicator_codes or spec.indicator_code in request.indicator_codes
        ]

        results: list[Observation] = []
        for spec in indicators_to_fetch:
            df = await self._fetch_indicator(spec.source_native_code)
            if df.empty:
                continue

            # Client-side filter to requested countries.
            filtered = df[df["iso3"].isin(requested_countries)]

            for _, row in filtered.iterrows():
                obs_date = row["date"]
                if isinstance(obs_date, pd.Timestamp):
                    obs_date = obs_date.date()

                results.append(
                    Observation(
                        country_iso3=str(row["iso3"]),
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

    async def _fetch_indicator(self, wb_id: str) -> pd.DataFrame:
        """Fetch all pages for one indicator and return a combined DataFrame.

        Pagination quirk: the WorldBank response is a two-element list
        where index 0 is metadata (``{"page", "pages", "per_page", "total"}``)
        and index 1 is the records array. On any page we need the total
        ``pages`` count from metadata to know when to stop. Easy to
        reach for ``data[0]`` by reflex and be wrong — the records live
        at index 1.
        """
        url = f"{WB_BASE_URL}/country/all/indicator/{wb_id}"
        current_year = datetime.datetime.now(datetime.UTC).year

        all_records: list[dict[str, Any]] = []
        page = 1
        total_pages = 1  # updated after first response

        while page <= total_pages:
            params: dict[str, Any] = {
                "format": "json",
                "per_page": WB_PER_PAGE,
                "date": f"{WB_START_YEAR}:{current_year}",
                "page": page,
            }

            try:
                raw = await self.get_json(url, params=params)
            except Exception as exc:
                logger.warning(
                    "worldbank.fetch.failed",
                    indicator=wb_id,
                    page=page,
                    error=str(exc),
                )
                return self._empty_df()

            if not isinstance(raw, list) or len(raw) < 2:
                logger.warning(
                    "worldbank.fetch.malformed_response",
                    indicator=wb_id,
                    page=page,
                )
                return self._empty_df()

            metadata = raw[0]
            records = raw[1] or []

            if isinstance(metadata, dict):
                total_pages = int(metadata.get("pages", 1))
            all_records.extend(records)

            if page >= total_pages:
                break
            page += 1

        return self._parse(all_records, self._iso2_to_iso3)

    @staticmethod
    def _parse(
        records: list[dict[str, Any]],
        iso2_to_iso3: Mapping[str, str],
    ) -> pd.DataFrame:
        """Parse a list of WorldBank records into a DataFrame.

        Ports v1's parsing quirks verbatim:

        * **JSON null = missing value.** Unlike FRED (which uses the
          string ``"."`` as a sentinel and needs coerce-to-NaN), WB
          uses actual JSON null (Python ``None``). Skip those rows
          entirely — never add them to the DataFrame.
        * **ISO2 -> ISO3 mapping at the parse boundary.** WB responses
          contain ISO2 country codes. Rows whose ISO2 isn't in the
          injected map are silently dropped — these include WB's
          regional aggregates ("WLD" for World, "HIC" for High-Income
          Countries, etc.) which have ISO2-like codes but no country
          mapping. The map comes from the ``country`` DB table via
          the constructor, not from a hardcoded dict.
        * **Date is a year string** (``"2024"``), not ``"YYYY-MM-DD"``
          like FRED. Parsed with ``format="%Y"`` so the resulting
          ``datetime64[ns]`` snaps to Jan 1 of that year.
        """
        if not records:
            return WorldBankAdapter._empty_df()

        rows: list[dict[str, Any]] = []
        for record in records:
            value = record.get("value")
            if value is None:
                continue  # JSON null - skip entirely, don't coerce

            country = record.get("country") or {}
            iso2 = str(country.get("id", "")).upper()
            iso3 = iso2_to_iso3.get(iso2)
            if not iso3:
                continue  # not a country we track (regional aggregate, etc.)

            try:
                value_float = float(value)
            except (ValueError, TypeError):
                continue

            date_str = str(record.get("date", ""))
            if not date_str:
                continue

            rows.append(
                {
                    "iso3": iso3,
                    "date": date_str,
                    "value": value_float,
                }
            )

        if not rows:
            return WorldBankAdapter._empty_df()

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], format="%Y")
        return df.sort_values(["iso3", "date"]).reset_index(drop=True)

    @staticmethod
    def _empty_df() -> pd.DataFrame:
        """Empty DataFrame with the right column dtypes."""
        return pd.DataFrame(
            {
                "iso3": pd.Series(dtype="object"),
                "date": pd.Series(dtype="datetime64[ns]"),
                "value": pd.Series(dtype="float64"),
            }
        )
