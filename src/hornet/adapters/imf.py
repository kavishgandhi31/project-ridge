"""IMF data source adapter -- ports v1's IMFClient to Hornet.

Covers three distinct IMF datasets via a single adapter with three
fetch paths:

1. **WEO** (World Economic Outlook) -- semi-annual macro forecasts.
   Simple JSON REST API at ``https://www.imf.org/external/datamapper``.
   One call returns all countries for one indicator. Frequency =
   "forecast" (a semantic tag, not a calendar cadence).

2. **IFS** (International Financial Statistics) -- monthly/quarterly
   actuals. SDMX CompactData format at ``dataservices.imf.org``.
   Per-country per-indicator. Tries monthly first, falls back to
   quarterly if empty.

3. **BOP** (Balance of Payments) -- quarterly flows. Same SDMX
   endpoint as IFS, different dataset. Per-country per-indicator.

Routing: the ``source_native_code`` in the seed data uses a prefix
to identify the sub-API: ``weo:NGDP_RPCH``, ``ifs:PCPI_IX``,
``bop:BCA_BP6_USD``. The adapter parses the prefix to dispatch to
the right fetch method.

Coverage: 190+ countries for WEO, ~150 for IFS/BOP. All 5 pilot
countries are covered (including NGA, unlike OECD/BIS).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import httpx
import pandas as pd
import structlog

from hornet.adapters.base import HealthReport
from hornet.adapters.base_client import BaseClient
from hornet.adapters.sdmx import parse_sdmx_json
from hornet.domain import (
    FetchRequest,
    Observation,
    SourceIndicatorSpec,
    SourceManifest,
)

logger = structlog.get_logger(__name__)


WEO_BASE_URL = "https://www.imf.org/external/datamapper/api/v1"
IMF_SDMX_BASE = "http://dataservices.imf.org/REST/SDMX_JSON.svc"


class IMFAdapter(BaseClient):
    """Fetches IMF WEO forecasts, IFS actuals, and BOP flows.

    Satisfies the ``SourceAdapter`` protocol. Inherits HTTP session,
    rate limiting, and retries from ``BaseClient``. The WEO base URL
    is used for the initial BaseClient setup; IFS/BOP use their own
    SDMX base URL directly.

    Indicators are classified by their ``source_native_code`` prefix:
    ``weo:`` for WEO, ``ifs:`` for IFS, ``bop:`` for BOP. The prefix
    is stripped to get the native API identifier.
    """

    source_id: str = "imf"

    def __init__(
        self,
        indicators: Sequence[SourceIndicatorSpec],
        requests_per_minute: int = 20,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id=self.source_id,
            base_url=WEO_BASE_URL,
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

        self._weo_specs: list[SourceIndicatorSpec] = []
        self._ifs_specs: list[SourceIndicatorSpec] = []
        self._bop_specs: list[SourceIndicatorSpec] = []
        for spec in self._indicators:
            prefix = self._get_prefix(spec.source_native_code)
            if prefix == "weo":
                self._weo_specs.append(spec)
            elif prefix == "ifs":
                self._ifs_specs.append(spec)
            elif prefix == "bop":
                self._bop_specs.append(spec)

    @staticmethod
    def _get_prefix(native_code: str) -> str:
        """Extract the sub-API prefix from a source_native_code."""
        if ":" in native_code:
            return native_code.split(":", 1)[0].lower()
        return ""

    @staticmethod
    def _get_api_id(native_code: str) -> str:
        """Extract the API-specific identifier after the prefix."""
        if ":" in native_code:
            return native_code.split(":", 1)[1]
        return native_code

    @classmethod
    def _validate_indicators(
        cls,
        indicators: Iterable[SourceIndicatorSpec],
    ) -> list[SourceIndicatorSpec]:
        kept: list[SourceIndicatorSpec] = []
        for spec in indicators:
            if spec.source_id != cls.source_id:
                logger.warning(
                    "imf.indicator.wrong_source",
                    source_id=spec.source_id,
                    native_code=spec.source_native_code,
                )
                continue
            prefix = cls._get_prefix(spec.source_native_code)
            if prefix not in ("weo", "ifs", "bop"):
                logger.warning(
                    "imf.indicator.unknown_prefix",
                    native_code=spec.source_native_code,
                )
                continue
            kept.append(spec)
        return kept

    @staticmethod
    def _group_by_country(
        indicators: Sequence[SourceIndicatorSpec],
    ) -> dict[str, tuple[SourceIndicatorSpec, ...]]:
        by_country: dict[str, list[SourceIndicatorSpec]] = defaultdict(list)
        for spec in indicators:
            for iso3 in spec.countries_iso3:
                by_country[iso3].append(spec)
        return {iso3: tuple(specs) for iso3, specs in by_country.items()}

    async def discover(self) -> SourceManifest:
        return SourceManifest(
            source_id=self.source_id,
            indicators=tuple(spec.to_manifest_spec() for spec in self._indicators),
            discovered_at=datetime.datetime.now(datetime.UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        """Fetch observations across WEO, IFS, and BOP sub-APIs.

        WEO: bulk fetch (one request returns all countries per indicator).
        IFS/BOP: per-country per-indicator.
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        requested_countries = request.countries_iso3 or frozenset(self._by_country.keys())

        results: list[Observation] = []

        # WEO: bulk fetch per indicator
        for spec in self._weo_specs:
            if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                continue
            api_id = self._get_api_id(spec.source_native_code)
            weo_df = await self._fetch_weo(api_id)
            if weo_df.empty or "iso3" not in weo_df.columns:
                continue

            for _, row in weo_df.iterrows():
                iso3 = str(row["iso3"])
                if iso3 not in requested_countries:
                    continue
                if iso3 not in spec.countries_iso3:
                    continue

                obs_date = row["date"]
                if hasattr(obs_date, "date"):
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

        # IFS + BOP: per-country per-indicator
        for iso3 in requested_countries:
            specs = self._by_country.get(iso3)
            if specs is None:
                continue

            for spec in specs:
                if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                    continue

                prefix = self._get_prefix(spec.source_native_code)
                api_id = self._get_api_id(spec.source_native_code)

                if prefix == "weo":
                    continue  # already handled above
                elif prefix == "ifs":
                    df = await self._fetch_ifs(api_id, iso3)
                elif prefix == "bop":
                    df = await self._fetch_bop(api_id, iso3)
                else:
                    continue

                for _, row in df.iterrows():
                    obs_date = row["date"]
                    if hasattr(obs_date, "date"):
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
        return HealthReport(source_id=self.source_id, healthy=True)

    # ------------------------------------------------------------------
    # WEO fetch + parse
    # ------------------------------------------------------------------

    async def _fetch_weo(self, indicator_id: str) -> pd.DataFrame:
        """Fetch a WEO indicator for all countries (one bulk call).

        Returns DataFrame with columns: iso3, date, value.
        """
        url = f"{WEO_BASE_URL}/{indicator_id}"
        try:
            data = await self.get_json(url)
        except Exception as exc:
            logger.warning("imf.weo.fetch_failed", indicator=indicator_id, error=str(exc))
            return pd.DataFrame(columns=["iso3", "date", "value"])

        return self._parse_weo(data, indicator_id)

    @staticmethod
    def _parse_weo(data: Any, indicator_id: str) -> pd.DataFrame:
        """Parse WEO JSON: {values: {indicator: {iso3: {year: value}}}}.

        Ported verbatim from v1. WEO response shape varies slightly
        between endpoints; we check both ``data.values.{id}`` and
        ``data.{id}`` as fallback.
        """
        if not isinstance(data, dict):
            return pd.DataFrame(columns=["iso3", "date", "value"])

        indicator_data = data.get("values", {}).get(indicator_id, {})
        if not indicator_data:
            indicator_data = data.get(indicator_id, {})

        rows: list[dict[str, Any]] = []
        for iso3, year_values in indicator_data.items():
            iso3_upper = iso3.upper()
            if not isinstance(year_values, dict):
                continue

            for year, value in year_values.items():
                if value is None:
                    continue
                try:
                    rows.append(
                        {
                            "iso3": iso3_upper,
                            "date": str(year),
                            "value": float(value),
                        }
                    )
                except (ValueError, TypeError):
                    continue

        if not rows:
            return pd.DataFrame(columns=["iso3", "date", "value"])

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], format="%Y")
        return df

    # ------------------------------------------------------------------
    # IFS fetch (SDMX CompactData)
    # ------------------------------------------------------------------

    async def _fetch_ifs(self, indicator_id: str, iso3: str) -> pd.DataFrame:
        """Fetch an IFS indicator for one country.

        Tries monthly frequency first; falls back to quarterly if
        the monthly response is empty (some IFS series are quarterly
        only). Ported from v1.
        """
        current_year = datetime.datetime.now(datetime.UTC).year
        params: dict[str, str] = {
            "startPeriod": "2010",
            "endPeriod": str(current_year),
        }

        url_m = f"{IMF_SDMX_BASE}/CompactData/IFS/M.{iso3}.{indicator_id}"
        try:
            data = await self.get_json(url_m, params=params)
            df = parse_sdmx_json(data)
            if not df.empty:
                return df
        except Exception as exc:
            logger.debug(
                "imf.ifs.monthly_failed", iso3=iso3, indicator=indicator_id, error=str(exc)
            )

        # Fallback to quarterly
        url_q = f"{IMF_SDMX_BASE}/CompactData/IFS/Q.{iso3}.{indicator_id}"
        try:
            data_q = await self.get_json(url_q, params=params)
            return parse_sdmx_json(data_q)
        except Exception as exc:
            logger.debug(
                "imf.ifs.quarterly_failed", iso3=iso3, indicator=indicator_id, error=str(exc)
            )
            return pd.DataFrame(columns=["date", "value"])

    # ------------------------------------------------------------------
    # BOP fetch (SDMX CompactData)
    # ------------------------------------------------------------------

    async def _fetch_bop(self, indicator_id: str, iso3: str) -> pd.DataFrame:
        """Fetch a BOP indicator for one country (quarterly)."""
        current_year = datetime.datetime.now(datetime.UTC).year
        params: dict[str, str] = {
            "startPeriod": "2010",
            "endPeriod": str(current_year),
        }

        url = f"{IMF_SDMX_BASE}/CompactData/BOP/Q.{iso3}.{indicator_id}"
        try:
            data = await self.get_json(url, params=params)
            return parse_sdmx_json(data)
        except Exception as exc:
            logger.debug("imf.bop.failed", iso3=iso3, indicator=indicator_id, error=str(exc))
            return pd.DataFrame(columns=["date", "value"])
