"""OECD data source adapter -- ports v1's OECDClient to Ridge.

Loads leading indicators (CLI, BCI, CCI, INDPROD) from the OECD SDMX
REST API and normalizes them to canonical Observation records. The
SDMX-JSON parsing is delegated to the shared ``sdmx`` module.

Quirks ported verbatim from v1's ``src/ingestion/oecd_client.py``:

* **Bulk fetch.** OECD SDMX supports "+" separated country codes in
  the data key, returning all countries in one response. This turns
  ~44 requests per indicator into 1 -- a 97% reduction.
* **Rate limit: 10 req/min.** OECD does not publish limits but
  aggressive scraping triggers 429s. Conservative default.
* **Timeout: 60s.** OECD bulk responses for all countries can be slow.

Coverage: OECD members + key partners (~44 countries). From the pilot
set, TUR/ZAF/BRA/POL are covered; NGA is not (not an OECD member or
partner). The seed data reflects this -- NGA has no OECD entries.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import httpx
import structlog

from ridge.adapters.base import HealthReport
from ridge.adapters.base_client import BaseClient
from ridge.adapters.sdmx import parse_sdmx_json_multi
from ridge.domain import (
    FetchRequest,
    Observation,
    SourceIndicatorSpec,
    SourceManifest,
)

logger = structlog.get_logger(__name__)


OECD_BASE_URL = "https://sdmx.oecd.org/public/rest"

# Ported verbatim from v1's OECD adapter. Don't shrink without re-checking
# scoring's z-score lookback assumptions against the resulting history depth.
_OECD_START_YEAR = "2010"

# OECD SDMX dataflow configuration. Maps canonical indicator code ->
# SDMX endpoint details. The key_pattern uses {country} as a placeholder
# that gets resolved at fetch time (single country) or joined with "+"
# (bulk fetch). Ported verbatim from v1's OECD_DATAFLOWS dict.
#
# Key structure for DSD_KEI v4.0 (7 dimensions):
# REF_AREA.FREQ.MEASURE.UNIT_MEASURE.ACTIVITY.ADJUSTMENT.TRANSFORMATION
_DATAFLOWS: dict[str, dict[str, str]] = {
    "CLI": {
        "agency": "OECD.SDD.STES",
        "dataflow": "DSD_KEI@DF_KEI",
        "version": "4.0",
        "key_pattern": "{country}.M.LI.IX._T.AA._Z",
    },
    "BCI": {
        "agency": "OECD.SDD.STES",
        "dataflow": "DSD_KEI@DF_KEI",
        "version": "4.0",
        "key_pattern": "{country}.M.BCICP.PB.C.Y._Z",
    },
    "CCI": {
        "agency": "OECD.SDD.STES",
        "dataflow": "DSD_KEI@DF_KEI",
        "version": "4.0",
        "key_pattern": "{country}.M.CCICP.PB._Z.Y._Z",
    },
    "INDPROD": {
        "agency": "OECD.SDD.STES",
        "dataflow": "DSD_KEI@DF_KEI",
        "version": "4.0",
        "key_pattern": "{country}.M.PRVM.IX.BTE.Y._Z",
    },
}


class OECDAdapter(BaseClient):
    """Fetches OECD leading indicators and yields canonical Observations.

    Satisfies the ``SourceAdapter`` protocol. Inherits HTTP session,
    rate limiting, and retries from ``BaseClient``.

    Uses bulk fetch: one SDMX request per indicator returns data for
    ALL registered countries simultaneously (via "+" separated codes
    in the data key). The response is split by country using the
    SDMX multi-series parser.
    """

    source_id: str = "oecd"

    def __init__(
        self,
        indicators: Sequence[SourceIndicatorSpec],
        requests_per_minute: int = 10,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id=self.source_id,
            base_url=OECD_BASE_URL,
            requests_per_minute=requests_per_minute,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )
        self._indicators: tuple[SourceIndicatorSpec, ...] = tuple(
            self._validate_indicators(indicators)
        )
        self._by_country: Mapping[str, tuple[SourceIndicatorSpec, ...]] = self._group_by_country(
            self._indicators
        )

    @classmethod
    def _validate_indicators(
        cls,
        indicators: Iterable[SourceIndicatorSpec],
    ) -> list[SourceIndicatorSpec]:
        """Drop any non-OECD rows and log a warning if found."""
        kept: list[SourceIndicatorSpec] = []
        for spec in indicators:
            if spec.source_id != cls.source_id:
                logger.warning(
                    "oecd.indicator.wrong_source",
                    source_id=spec.source_id,
                    native_code=spec.source_native_code,
                )
                continue
            if spec.indicator_code not in _DATAFLOWS:
                logger.warning(
                    "oecd.indicator.unknown_dataflow",
                    indicator_code=spec.indicator_code,
                )
                continue
            kept.append(spec)
        return kept

    @staticmethod
    def _group_by_country(
        indicators: Sequence[SourceIndicatorSpec],
    ) -> dict[str, tuple[SourceIndicatorSpec, ...]]:
        """Produce a (country_iso3 -> specs) map for fast fetch() lookup."""
        by_country: dict[str, list[SourceIndicatorSpec]] = defaultdict(list)
        for spec in indicators:
            for iso3 in spec.countries_iso3:
                by_country[iso3].append(spec)
        return {iso3: tuple(specs) for iso3, specs in by_country.items()}

    async def discover(self) -> SourceManifest:
        """Return a SourceManifest listing every registered series."""
        return SourceManifest(
            source_id=self.source_id,
            indicators=tuple(spec.to_manifest_spec() for spec in self._indicators),
            discovered_at=datetime.datetime.now(datetime.UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        """Fetch observations for the requested country/indicator scope.

        Uses bulk fetch: one SDMX request per indicator returns all
        countries. Then filters client-side to the requested scope.
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        requested_countries = request.countries_iso3 or frozenset(self._by_country.keys())

        # Group requested indicators by their canonical code so we make
        # one bulk request per indicator (not per country x indicator).
        specs_by_indicator: dict[str, SourceIndicatorSpec] = {}
        for spec in self._indicators:
            if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                continue
            specs_by_indicator[spec.indicator_code] = spec

        results: list[Observation] = []
        for indicator_code, spec in specs_by_indicator.items():
            country_dfs = await self._fetch_bulk(
                indicator_code,
                countries=sorted(requested_countries & spec.countries_iso3),
            )

            for iso3, df in country_dfs.items():
                if iso3 not in requested_countries:
                    continue

                for _, row in df.iterrows():
                    obs_date = row["date"]
                    if hasattr(obs_date, "date"):
                        obs_date = obs_date.date()

                    results.append(
                        Observation(
                            country_iso3=iso3,
                            indicator_code=indicator_code,
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

    async def _fetch_bulk(
        self,
        indicator_code: str,
        countries: list[str],
    ) -> dict[str, Any]:
        """Fetch one indicator for multiple countries in a single SDMX request.

        Joins country codes with "+" in the SDMX data key so the API
        returns all countries in one response. Falls back to empty dict
        on any error.
        """
        dataflow = _DATAFLOWS.get(indicator_code)
        if not dataflow or not countries:
            return {}

        all_countries = "+".join(countries)
        data_key = dataflow["key_pattern"].format(country=all_countries)

        url = (
            f"{OECD_BASE_URL}/data/"
            f"{dataflow['agency']},{dataflow['dataflow']},{dataflow['version']}"
            f"/{data_key}"
        )
        params: dict[str, str] = {
            "startPeriod": _OECD_START_YEAR,
            "format": "jsondata",
        }

        try:
            raw = await self.get_json(url, params=params)
        except Exception as exc:
            logger.warning(
                "oecd.bulk_fetch.failed",
                indicator=indicator_code,
                error=str(exc),
            )
            return {}

        if not isinstance(raw, dict):
            return {}

        # series_dim_index=0 because REF_AREA (country) is dimension 0
        parsed = parse_sdmx_json_multi(raw, series_dim_index=0)
        logger.debug(
            "oecd.bulk_fetch.ok",
            indicator=indicator_code,
            countries_returned=len(parsed),
        )
        return parsed
