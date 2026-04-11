"""WorldBank data source adapter — ports v1's WorldBankClient to Hornet.

Loads annual macro indicators from the World Bank REST API and
normalizes them to canonical Observation records. Parsing quirks
(ISO2 → ISO3 mapping, pagination with metadata-on-page-1, JSON null
handling, year-string dates) are ported verbatim from v1's
``src/ingestion/worldbank_client.py``.

Phase 1 uses a hardcoded set of 7 indicators and a small ISO2↔ISO3
map covering the 5 pilot countries. Real production config moves to
DB-backed tables in a later phase.
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
    IndicatorSpec,
    Observation,
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


@dataclass(frozen=True)
class _IndicatorMetadata:
    """Hardcoded metadata for a WorldBank indicator.

    Phase 1 only — moves to DB-backed config in Phase 2+.
    """

    wb_id: str
    """Native WorldBank indicator code (e.g. 'NY.GDP.MKTP.KD.ZG')."""

    indicator_code: str
    """Canonical Hornet indicator code (e.g. 'GDP_GROWTH')."""


# The 7 indicators v1 pulls from WorldBank, with canonical codes chosen
# to match FRED where the concept overlaps (CPI_YOY, GDP_GROWTH). The
# remaining 5 are WorldBank-only for now.
_INDICATORS: list[_IndicatorMetadata] = [
    _IndicatorMetadata("NY.GDP.MKTP.KD.ZG", "GDP_GROWTH"),
    _IndicatorMetadata("FP.CPI.TOTL.ZG", "CPI_YOY"),
    _IndicatorMetadata("BN.CAB.XOKA.GD.ZS", "CURRENT_ACCOUNT_GDP"),
    _IndicatorMetadata("FI.RES.TOTL.MO", "RESERVES_MONTHS_IMPORTS"),
    _IndicatorMetadata("GC.DOD.TOTL.GD.ZS", "GOVT_DEBT_GDP"),
    _IndicatorMetadata("SL.UEM.TOTL.ZS", "UNEMPLOYMENT"),
    _IndicatorMetadata("NE.TRD.GNFS.ZS", "TRADE_OPENNESS"),
]


# ISO2 → ISO3 map for the 5 pilot countries. WorldBank returns ISO2
# in its JSON responses, but Hornet's canonical Observation.country_iso3
# is ISO3, so we map at the parse boundary. Phase 2 will replace this
# with a DB-backed lookup populated from countries.yaml.
_ISO2_TO_ISO3: dict[str, str] = {
    "NG": "NGA",
    "TR": "TUR",
    "ZA": "ZAF",
    "BR": "BRA",
    "PL": "POL",
}


class WorldBankAdapter(BaseClient):
    """Fetches WorldBank indicators and yields canonical Observations.

    Satisfies the ``SourceAdapter`` protocol. Inherits HTTP session,
    rate limiting, and retries from ``BaseClient`` — WB rate limits
    are intentionally lower than FRED (30/min vs 60/min) because WB
    doesn't publish limits and conservative defaults avoid 429s.
    Timeout is raised to 60 seconds because WB is genuinely slow on
    multi-page indicator fetches.
    """

    def __init__(
        self,
        requests_per_minute: int = 30,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id="worldbank",
            base_url=WB_BASE_URL,
            requests_per_minute=requests_per_minute,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )

    async def discover(self) -> SourceManifest:
        """Return a SourceManifest listing every WorldBank indicator available.

        Unlike FRED (which has per-country native codes), WorldBank
        indicators are global: one native code like ``NY.GDP.MKTP.KD.ZG``
        applies to every country. So each ``IndicatorSpec`` covers the
        full set of pilot countries rather than a single country.
        """
        all_countries = frozenset(_ISO2_TO_ISO3.values())
        specs: list[IndicatorSpec] = []
        for indicator in _INDICATORS:
            specs.append(
                IndicatorSpec(
                    indicator_code=indicator.indicator_code,
                    source_native_code=indicator.wb_id,
                    frequency="annual",
                    countries_iso3=all_countries,
                )
            )
        return SourceManifest(
            source_id=self.source_id,
            indicators=tuple(specs),
            discovered_at=datetime.datetime.now(datetime.UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        """Fetch observations for the requested scope.

        Bulk-fetches each indicator once (one API call returns all ~190
        countries for that indicator), then filters client-side to the
        requested country set. This is vastly more efficient than
        per-country fetches: 7 indicators x 2 pages is ~14 calls for
        the entire run, regardless of how many countries are requested.
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        requested_countries = request.countries_iso3 or frozenset(_ISO2_TO_ISO3.values())

        # Apply indicator filter if present; otherwise fetch all.
        indicators_to_fetch = [
            ind
            for ind in _INDICATORS
            if not request.indicator_codes or ind.indicator_code in request.indicator_codes
        ]

        results: list[Observation] = []
        for indicator in indicators_to_fetch:
            df = await self._fetch_indicator(indicator.wb_id)
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
                        indicator_code=indicator.indicator_code,
                        source_id=self.source_id,
                        date=obs_date,
                        value=float(row["value"]),
                        frequency="annual",
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
        current_year = datetime.datetime.now().year

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

        return self._parse(all_records)

    @staticmethod
    def _parse(records: list[dict[str, Any]]) -> pd.DataFrame:
        """Parse a list of WorldBank records into a DataFrame.

        Ports v1's parsing quirks verbatim:

        * **JSON null = missing value.** Unlike FRED (which uses the
          string ``"."`` as a sentinel and needs coerce-to-NaN), WB
          uses actual JSON null (Python ``None``). Skip those rows
          entirely — never add them to the DataFrame.
        * **ISO2 → ISO3 mapping at the parse boundary.** WB responses
          contain ISO2 country codes. Rows whose ISO2 isn't in our
          pilot map are silently dropped — these include WB's regional
          aggregates ("WLD" for World, "HIC" for High-Income Countries,
          etc.) which have ISO2-like codes but no country mapping.
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
                continue  # JSON null — skip entirely, don't coerce

            country = record.get("country") or {}
            iso2 = str(country.get("id", "")).upper()
            iso3 = _ISO2_TO_ISO3.get(iso2)
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
