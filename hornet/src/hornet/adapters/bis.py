"""BIS (Bank for International Settlements) data source adapter.

Ports v1's BISClient to Hornet. Fetches financial stability indicators
from the BIS Statistics API and normalizes them to canonical Observation
records. BIS returns data in CSV format via a SDMX REST API.

Quirks ported verbatim from v1's ``src/ingestion/bis_client.py``:

* **CSV format.** BIS responses are SDMX-CSV (not JSON like OECD/IMF).
  Column names vary by dataset (TIME_PERIOD vs DATE, OBS_VALUE vs
  VALUE). The parser handles all known variants.
* **BIS date formats.** Quarterly dates arrive as ``"2024-Q1"`` (not
  standard ISO), monthly as ``"2024-01"``, annual as ``"2024"``. All
  three formats are normalized to pandas Timestamps.
* **ISO2 country codes.** BIS uses ISO2 in its API. The adapter
  resolves ISO3 -> ISO2 via the country registry (same pattern as
  WorldBank's ISO2 -> ISO3 mapping, just reversed).
* **Per-country fetches.** Unlike OECD (which supports bulk "+"
  country queries), BIS requires one request per (dataset, country)
  pair. Rate limit is conservative at 10 req/min.
* **Timeout: 90s.** BIS CSV responses for long time series are slow.

Coverage: G20 + major EMs (~60 countries). From the pilot set,
TUR/ZAF/BRA/POL are covered; NGA is not.

Three datasets:
- WS_CREDIT_GAP: Credit-to-GDP gap (Basel gap, quarterly)
- WS_SPP: Residential property prices (quarterly)
- WS_EER: Real effective exchange rate (monthly)
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from io import StringIO

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


BIS_BASE_URL = "https://stats.bis.org/api/v1"

# BIS SDMX data key patterns. Maps canonical indicator code ->
# (dataset_id, key_pattern). The {country} placeholder is resolved
# at fetch time with the ISO2 code from the country registry.
_DATASETS: dict[str, dict[str, str]] = {
    "CREDIT_GAP": {
        "dataset_id": "WS_CREDIT_GAP",
        "key_pattern": "Q.{country}.P.A.C",
    },
    "PROPERTY_PRICE": {
        "dataset_id": "WS_SPP",
        "key_pattern": "Q.{country}.R.771",
    },
    "REER": {
        "dataset_id": "WS_EER",
        "key_pattern": "M.R.B.{country}",
    },
}


class BISAdapter(BaseClient):
    """Fetches BIS financial stability indicators as canonical Observations.

    Satisfies the ``SourceAdapter`` protocol. Inherits HTTP session,
    rate limiting, and retries from ``BaseClient``.

    Requires an ISO3 -> ISO2 country code map (``iso3_to_iso2``) in the
    constructor because BIS uses ISO2 in its API. The ingest factory
    builds this from the ``country`` table.
    """

    source_id: str = "bis"

    def __init__(
        self,
        indicators: Sequence[SourceIndicatorSpec],
        iso3_to_iso2: Mapping[str, str],
        requests_per_minute: int = 10,
        timeout_seconds: float = 90.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id=self.source_id,
            base_url=BIS_BASE_URL,
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
        self._iso3_to_iso2: dict[str, str] = {
            iso3.upper(): iso2.upper() for iso3, iso2 in iso3_to_iso2.items()
        }

    @classmethod
    def _validate_indicators(
        cls,
        indicators: Iterable[SourceIndicatorSpec],
    ) -> list[SourceIndicatorSpec]:
        """Drop any non-BIS rows and log a warning if found."""
        kept: list[SourceIndicatorSpec] = []
        for spec in indicators:
            if spec.source_id != cls.source_id:
                logger.warning(
                    "bis.indicator.wrong_source",
                    source_id=spec.source_id,
                    native_code=spec.source_native_code,
                )
                continue
            if spec.indicator_code not in _DATASETS:
                logger.warning(
                    "bis.indicator.unknown_dataset",
                    indicator_code=spec.indicator_code,
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
        """Fetch observations for the requested scope.

        Per-country fetches (BIS does not support bulk country queries).
        Each (country, indicator) pair is one CSV request.
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        countries = request.countries_iso3 or frozenset(self._by_country.keys())

        results: list[Observation] = []
        for iso3 in countries:
            specs = self._by_country.get(iso3)
            if specs is None:
                logger.debug("bis.fetch.unknown_country", iso3=iso3)
                continue

            iso2 = self._iso3_to_iso2.get(iso3)
            if not iso2:
                logger.debug("bis.fetch.no_iso2_mapping", iso3=iso3)
                continue

            for spec in specs:
                if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                    continue

                df = await self._fetch_dataset(spec.indicator_code, iso2)

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

    async def _fetch_dataset(
        self,
        indicator_code: str,
        iso2: str,
    ) -> pd.DataFrame:
        """Fetch one BIS dataset for one country, return (date, value) DataFrame."""
        config = _DATASETS.get(indicator_code)
        if not config:
            return self._empty_df()

        data_key = config["key_pattern"].format(country=iso2)
        url = f"{BIS_BASE_URL}/data/{config['dataset_id']}/{data_key}/all"
        params: dict[str, str] = {
            "startPeriod": "2000",
            "detail": "dataonly",
            "format": "csv",
        }

        try:
            csv_text = await self.get_text(url, params=params)
        except Exception as exc:
            logger.warning(
                "bis.fetch.failed",
                indicator=indicator_code,
                iso2=iso2,
                error=str(exc),
            )
            return self._empty_df()

        return self._parse_csv(csv_text)

    @staticmethod
    def _parse_csv(csv_text: str) -> pd.DataFrame:
        """Parse BIS CSV response into DataFrame(date, value).

        Ports v1's parse quirks verbatim:
        - Column name detection is case-insensitive and handles
          BIS column-name variations
        - Date parsing handles quarterly ("2024-Q1"), monthly
          ("2024-01"), and annual ("2024") formats
        - Non-numeric values are coerced to NaN and dropped
        """
        if not csv_text or not csv_text.strip():
            return BISAdapter._empty_df()

        try:
            df = pd.read_csv(StringIO(csv_text))
        except Exception:
            return BISAdapter._empty_df()

        date_col = None
        value_col = None
        for col in df.columns:
            col_upper = col.upper().strip()
            if col_upper in ("TIME_PERIOD", "DATE", "PERIOD"):
                date_col = col
            elif col_upper in ("OBS_VALUE", "VALUE", "OBSERVATION_VALUE"):
                value_col = col

        if date_col is None or value_col is None:
            return BISAdapter._empty_df()

        result = pd.DataFrame(
            {
                "date": df[date_col].astype(str),
                "value": pd.to_numeric(df[value_col], errors="coerce"),
            }
        )
        result = result.dropna(subset=["value"])
        result["date"] = result["date"].apply(BISAdapter._parse_bis_date)
        result = result.dropna(subset=["date"])
        return result.sort_values("date").reset_index(drop=True)

    @staticmethod
    def _parse_bis_date(date_str: str) -> pd.Timestamp | None:
        """Parse BIS date strings into pandas Timestamps.

        Handles: "2024-Q1", "2024-Q2", "2024-01", "2024"
        """
        date_str = date_str.strip()

        # Quarterly: "2024-Q1" -> first month of quarter
        if "-Q" in date_str.upper():
            parts = date_str.upper().split("-Q")
            try:
                year = int(parts[0])
                quarter = int(parts[1])
                month = (quarter - 1) * 3 + 1
                return pd.Timestamp(year=year, month=month, day=1)
            except (ValueError, IndexError):
                return None

        # Monthly: "2024-01"
        if len(date_str) == 7 and date_str[4] == "-":
            try:
                return pd.Timestamp(date_str + "-01")
            except Exception:
                return None

        # Annual: "2024"
        if len(date_str) == 4 and date_str.isdigit():
            try:
                return pd.Timestamp(year=int(date_str), month=1, day=1)
            except Exception:
                return None

        # Fallback
        try:
            return pd.Timestamp(date_str)
        except Exception:
            return None

    @staticmethod
    def _empty_df() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.Series(dtype="datetime64[ns]"),
                "value": pd.Series(dtype="float64"),
            }
        )
