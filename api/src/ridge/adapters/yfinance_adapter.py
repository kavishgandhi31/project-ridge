"""yfinance data source adapter -- ports v1's YFinanceClient to Ridge.

Loads FX rates and equity index levels from Yahoo Finance via the
``yfinance`` library and normalizes them to canonical Observation
records. Parsing quirks (MultiIndex column flattening, duplicate
column removal, Close-price-as-value extraction) are ported verbatim
from v1's ``src/ingestion/yfinance_client.py``.

Unlike FRED and WorldBank, yfinance is a Python library (not a REST
API), so this adapter does NOT extend ``BaseClient``. There is no
HTTP session, rate limiter, or retry logic to manage -- yfinance
handles all of that internally. The adapter wraps synchronous
``yf.download`` calls in ``asyncio.to_thread()`` so they do not block
the event loop during concurrent ingest runs.

Commodities (GC=F, CL=F, etc.) are deferred -- they are global
instruments with no per-country mapping and need a design decision
about how global data flows through Phase 3 scoring. Only FX pairs
and equity indices are ported in this step.
"""

from __future__ import annotations

import asyncio
import datetime
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import structlog
import yfinance as yf

from ridge.adapters._dispatch import group_by_country, validate_indicators
from ridge.adapters.base import HealthReport
from ridge.domain import (
    FetchRequest,
    Observation,
    SourceIndicatorSpec,
    SourceManifest,
)

logger = structlog.get_logger(__name__)


# Lookback window ported from v1. 5 years of daily data gives ~1,250
# trading days -- plenty for downstream scoring z-scores.
_DEFAULT_LOOKBACK_YEARS = 5


class YFinanceAdapter:
    """Fetches FX and equity data from Yahoo Finance via yfinance.

    Satisfies the ``SourceAdapter`` protocol (``discover``, ``fetch``,
    ``health``) but does NOT extend ``BaseClient`` -- yfinance manages
    its own HTTP internals. A no-op ``close()`` is provided so tests
    can use the same try/finally pattern as other adapters.

    The ``indicators`` parameter is the registry of series this adapter
    should expose. Every entry must have ``source_id == 'yfinance'``.
    The ``source_native_code`` is the Yahoo Finance ticker symbol
    (e.g., ``TRYUSD=X`` for TRY/USD FX, ``^BVSP`` for Bovespa).
    """

    source_id: str = "yfinance"

    def __init__(
        self,
        indicators: Sequence[SourceIndicatorSpec],
    ) -> None:
        self._indicators: tuple[SourceIndicatorSpec, ...] = tuple(
            validate_indicators(self.source_id, indicators)
        )
        self._by_country: Mapping[str, tuple[SourceIndicatorSpec, ...]] = group_by_country(
            self._indicators
        )

    async def discover(self) -> SourceManifest:
        """Return a SourceManifest listing every registered series."""
        return SourceManifest(
            source_id=self.source_id,
            indicators=tuple(spec.to_manifest_spec() for spec in self._indicators),
            discovered_at=datetime.datetime.now(datetime.UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        """Fetch observations for the requested country/indicator scope.

        Tickers are deduplicated before fetching: a ticker registered to
        N countries (e.g. ``EURUSD=X`` for the EUR-zone bloc) is downloaded
        once and the resulting rows are fanned out to all N slots. yfinance
        has no rate limit, so distinct tickers fetch concurrently via
        ``asyncio.gather``. Failed tickers return an empty DataFrame and
        contribute zero observations -- same graceful-degradation pattern
        as FRED and WorldBank.
        """
        ingested_at = datetime.datetime.now(datetime.UTC)
        countries = request.countries_iso3 or frozenset(self._by_country.keys())

        # Group every (iso3, spec) slot under its source_native_code so each
        # unique ticker is downloaded once and broadcast to every slot.
        slots_by_ticker: dict[str, list[tuple[str, SourceIndicatorSpec]]] = defaultdict(list)
        for iso3 in countries:
            specs = self._by_country.get(iso3)
            if specs is None:
                logger.debug("yfinance.fetch.unknown_country", iso3=iso3)
                continue
            for spec in specs:
                if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                    continue
                slots_by_ticker[spec.source_native_code].append((iso3, spec))

        if not slots_by_ticker:
            return []

        tickers = list(slots_by_ticker.keys())
        dfs = await asyncio.gather(
            *(
                self._fetch_ticker(t, start=request.start, end=request.end)
                for t in tickers
            )
        )

        results: list[Observation] = []
        for ticker, df in zip(tickers, dfs, strict=True):
            if df.empty:
                continue
            for iso3, spec in slots_by_ticker[ticker]:
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

    async def close(self) -> None:
        """No-op -- yfinance has no persistent connections to close.

        Provided so tests can use the same try/finally pattern as
        BaseClient-derived adapters.
        """

    async def _fetch_ticker(
        self,
        ticker: str,
        start: datetime.date | None = None,
        end: datetime.date | None = None,
    ) -> pd.DataFrame:
        """Fetch a single ticker via yfinance, return a (date, value) DataFrame.

        Runs the synchronous ``yf.download`` in a thread so it does not
        block the event loop. Applies v1's column-flattening and
        close-price-extraction quirks verbatim.
        """
        start_str = (
            start.strftime("%Y-%m-%d")
            if start
            else (
                datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(days=_DEFAULT_LOOKBACK_YEARS * 365)
            ).strftime("%Y-%m-%d")
        )
        end_str = (
            end.strftime("%Y-%m-%d")
            if end
            else datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
        )

        try:
            raw: Any = await asyncio.to_thread(
                yf.download,
                ticker,
                start=start_str,
                end=end_str,
                progress=False,
            )
        except Exception as exc:
            logger.warning(
                "yfinance.fetch.failed",
                ticker=ticker,
                error=str(exc),
            )
            return self._empty_df()

        if not isinstance(raw, pd.DataFrame) or raw.empty:
            logger.debug("yfinance.fetch.empty", ticker=ticker)
            return self._empty_df()

        return self._parse_ohlcv(raw)

    @staticmethod
    def _parse_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """Extract (date, value) from a yfinance OHLCV DataFrame.

        Ports v1's parsing quirks verbatim:

        * **DatetimeIndex to column.** ``yf.download`` returns a
          DataFrame with a DatetimeIndex. We ``reset_index()`` to get
          a ``date`` column that downstream code expects.

        * **MultiIndex column flattening.** yfinance >= 0.2.18 returns
          MultiIndex columns like ``(Close, TRYUSD=X)`` even for
          single-ticker downloads. We flatten to lowercase metric
          names (``close``, ``high``, etc.).

        * **Duplicate column removal.** ``adj close`` and ``close``
          can both flatten to similar names. ``~df.columns.duplicated()``
          keeps the first occurrence.

        * **Close price as value.** We extract the ``close`` column as
          the observation value and drop everything else.
        """
        df = df.reset_index()

        # Flatten MultiIndex columns (yfinance >= 0.2.18).
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.Index([str(col[0]).lower() for col in df.columns])
        else:
            df.columns = pd.Index([str(col).lower() for col in df.columns])

        # Drop duplicate column names (adj close vs close).
        df = df.loc[:, ~df.columns.duplicated()]

        if "close" not in df.columns or "date" not in df.columns:
            return YFinanceAdapter._empty_df()

        result = pd.DataFrame({"date": df["date"], "value": df["close"]})
        result = result.dropna(subset=["value"])
        result["value"] = pd.to_numeric(result["value"], errors="coerce")
        result = result.dropna(subset=["value"])
        return result.reset_index(drop=True)

    @staticmethod
    def _empty_df() -> pd.DataFrame:
        """Return an empty DataFrame with the right column dtypes."""
        return pd.DataFrame(
            {
                "date": pd.Series(dtype="datetime64[ns]"),
                "value": pd.Series(dtype="float64"),
            }
        )
