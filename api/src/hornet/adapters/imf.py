"""IMF data source adapter -- new SDMX 3.0 API backend.

The IMF retired its legacy SDMX-JSON 1.0 endpoint at ``dataservices.imf.org``
in June 2025 and restructured the IFS dataset into topical dataflows (CPI,
ER, MFS_IR, MFS_MA, IRFCL). This adapter targets the replacement SDMX 3.0
API at ``api.imf.org`` and uses ``parse_sdmx3_json`` for responses.

Three distinct fetch paths, routed by the ``source_native_code`` prefix:

1. **WEO** (prefix ``weo:``) -- World Economic Outlook forecasts at
   ``imf.org/external/datamapper``. A single REST call returns all countries
   for one indicator. Frequency = "forecast".

2. **Actuals via SDMX 3.0** (prefixes ``cpi:``, ``er:``, ``mfs_ir:``,
   ``mfs_ma:``, ``irfcl:``, ``bop:``) -- live time series from
   ``api.imf.org/external/sdmx/3.0``. Per-country per-indicator requests
   with fully specified keys. The prefix names the dataflow; the key
   after the colon is the full dimension key after COUNTRY.

The YAML ``source_native_code`` encodes the dataflow + full key so the
adapter doesn't need a hardcoded mapping:

    weo:NGDP_RPCH                          -> WEO indicator id
    cpi:CPI._T.IX.M                        -> IMF.STA:CPI / {C}.CPI._T.IX.M
    er:XDC_USD.PA_RT.M                     -> IMF.STA:ER  / {C}.XDC_USD.PA_RT.M
    mfs_ir:MFS162_RT_PT_A_PT.M             -> IMF.STA:MFS_IR / {C}.MFS162_RT_PT_A_PT.M
    mfs_ma:BM_MAI.XDC.M                    -> IMF.STA:MFS_MA / {C}.BM_MAI.XDC.M
    irfcl:IRFCLDT1_IRFCL65_USD.S1XS1311.M  -> IMF.STA:IRFCL / {C}.IRFCLDT1_IRFCL65_USD.S1XS1311.M
    bop:NETCD_T.CAB.USD.Q                  -> IMF.STA:BOP / {C}.NETCD_T.CAB.USD.Q
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
from hornet.adapters.sdmx3 import parse_sdmx3_json
from hornet.domain import (
    FetchRequest,
    Observation,
    SourceIndicatorSpec,
    SourceManifest,
)

logger = structlog.get_logger(__name__)


WEO_BASE_URL = "https://www.imf.org/external/datamapper/api/v1"
IMF_SDMX3_BASE = "https://api.imf.org/external/sdmx/3.0"
IMF_SDMX3_AGENCY = "IMF.STA"

# SDMX 3.0 REST requires explicit content negotiation; without this header
# the server returns structure-only skeletons with no observations.
IMF_SDMX3_HEADERS = {
    "Accept": "application/vnd.sdmx.data+json;version=2.0.0",
}

# Prefix -> SDMX 3.0 dataflow ID. "weo" is handled separately (different endpoint).
SDMX3_PREFIXES: dict[str, str] = {
    "cpi": "CPI",
    "er": "ER",
    "mfs_ir": "MFS_IR",
    "mfs_ma": "MFS_MA",
    "irfcl": "IRFCL",
    "bop": "BOP",
}

# How much history to request per series. SDMX 3.0's only working time filter
# is ``lastNObservations``; start/endPeriod are silently ignored. 60 gives us
# 5 years of monthly or 15 years of quarterly -- enough for any downstream
# rolling window computation.
SDMX3_LAST_N_OBS = 60


class IMFAdapter(BaseClient):
    """Fetches IMF WEO forecasts and SDMX 3.0 actuals (CPI, ER, MFS, IRFCL, BOP).

    Satisfies the ``SourceAdapter`` protocol. Inherits HTTP session, rate
    limiting, and retries from ``BaseClient``. The default_headers wire the
    mandatory SDMX 3.0 Accept header onto every outbound request; WEO is
    tolerant to the extra header.
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
            default_headers=IMF_SDMX3_HEADERS,
        )
        self._indicators: tuple[SourceIndicatorSpec, ...] = tuple(
            self._validate_indicators(indicators)
        )
        self._by_country: Mapping[str, tuple[SourceIndicatorSpec, ...]] = self._group_by_country(
            self._indicators
        )
        self._weo_specs: list[SourceIndicatorSpec] = [
            s for s in self._indicators if self._get_prefix(s.source_native_code) == "weo"
        ]
        self._sdmx3_specs: list[SourceIndicatorSpec] = [
            s for s in self._indicators if self._get_prefix(s.source_native_code) in SDMX3_PREFIXES
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_prefix(native_code: str) -> str:
        if ":" in native_code:
            return native_code.split(":", 1)[0].lower()
        return ""

    @staticmethod
    def _get_key(native_code: str) -> str:
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
            if prefix != "weo" and prefix not in SDMX3_PREFIXES:
                logger.warning(
                    "imf.indicator.unknown_prefix",
                    native_code=spec.source_native_code,
                    prefix=prefix,
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

    # ------------------------------------------------------------------
    # SourceAdapter protocol
    # ------------------------------------------------------------------

    async def discover(self) -> SourceManifest:
        return SourceManifest(
            source_id=self.source_id,
            indicators=tuple(spec.to_manifest_spec() for spec in self._indicators),
            discovered_at=datetime.datetime.now(datetime.UTC),
        )

    async def health(self) -> HealthReport:
        return HealthReport(source_id=self.source_id, healthy=True)

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        """Fetch observations across WEO and SDMX 3.0 sub-APIs.

        WEO: bulk fetch per indicator (one call per indicator returns all
        countries). SDMX 3.0: per-country per-indicator (one call per series).
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        requested_countries = request.countries_iso3 or frozenset(self._by_country.keys())

        results: list[Observation] = []

        # ---- WEO: bulk per indicator ----
        for spec in self._weo_specs:
            if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                continue
            indicator_id = self._get_key(spec.source_native_code)
            weo_df = await self._fetch_weo(indicator_id)
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

        # ---- SDMX 3.0: per-country per-indicator ----
        for iso3 in requested_countries:
            specs = self._by_country.get(iso3)
            if specs is None:
                continue

            for spec in specs:
                prefix = self._get_prefix(spec.source_native_code)
                if prefix not in SDMX3_PREFIXES:
                    continue
                if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                    continue

                observations = await self._fetch_sdmx3(iso3, spec, ingested_at)
                results.extend(observations)

        return results

    # ------------------------------------------------------------------
    # WEO fetch + parse (unchanged from v1 -- still works)
    # ------------------------------------------------------------------

    async def _fetch_weo(self, indicator_id: str) -> pd.DataFrame:
        """Fetch one WEO indicator for all countries in a single bulk request."""
        url = f"{WEO_BASE_URL}/{indicator_id}"
        try:
            data = await self.get_json(url)
        except Exception as exc:
            logger.warning("imf.weo.fetch_failed", indicator=indicator_id, error=str(exc))
            return pd.DataFrame(columns=["iso3", "date", "value"])

        return self._parse_weo(data, indicator_id)

    @staticmethod
    def _parse_weo(data: Any, indicator_id: str) -> pd.DataFrame:
        """Parse WEO JSON: ``{values: {indicator: {iso3: {year: value}}}}``.

        WEO response shape varies slightly between endpoints; check both
        ``data.values.{id}`` and ``data.{id}`` as fallback.
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
    # SDMX 3.0 fetch + adapt
    # ------------------------------------------------------------------

    async def _fetch_sdmx3(
        self,
        iso3: str,
        spec: SourceIndicatorSpec,
        ingested_at: datetime.datetime,
    ) -> list[Observation]:
        """Fetch a single SDMX 3.0 series and return Observation records."""
        prefix = self._get_prefix(spec.source_native_code)
        flow = SDMX3_PREFIXES[prefix]
        key_suffix = self._get_key(spec.source_native_code)
        full_key = f"{iso3}.{key_suffix}"
        url = f"{IMF_SDMX3_BASE}/data/dataflow/{IMF_SDMX3_AGENCY}/{flow}/+/{full_key}"
        params: dict[str, Any] = {"lastNObservations": SDMX3_LAST_N_OBS}

        try:
            payload = await self.get_json(url, params=params)
        except Exception as exc:
            logger.debug(
                "imf.sdmx3.fetch_failed",
                flow=flow,
                country=iso3,
                indicator=spec.indicator_code,
                error=str(exc),
            )
            return []

        records = parse_sdmx3_json(payload)
        if not records:
            logger.debug(
                "imf.sdmx3.empty",
                flow=flow,
                country=iso3,
                indicator=spec.indicator_code,
            )
            return []

        return [
            Observation(
                country_iso3=iso3,
                indicator_code=spec.indicator_code,
                source_id=self.source_id,
                date=r["date"],
                value=r["value"],
                frequency=spec.frequency,
                vintage=ingested_at,
                ingested_at=ingested_at,
            )
            for r in records
        ]
