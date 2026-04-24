"""Tests for the yfinance SourceAdapter.

All tests mock ``yf.download`` -- no real Yahoo Finance calls, no
network. Tests exercise the parse quirks (MultiIndex column flattening,
duplicate column removal, Close-price extraction), the fetch
orchestration (country/indicator filtering, graceful failure), and
the discover manifest.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from unittest.mock import patch

import pandas as pd

from ridge.adapters.yfinance_adapter import YFinanceAdapter
from ridge.domain import FetchRequest, SourceIndicatorSpec


def _pilot_indicators() -> list[SourceIndicatorSpec]:
    """Build the 9-series pilot fixture: 5 FX + 4 equity."""
    specs: list[SourceIndicatorSpec] = []

    fx_pairs = [
        ("NGA", "NGNUSD=X"),
        ("TUR", "TRYUSD=X"),
        ("ZAF", "ZARUSD=X"),
        ("BRA", "BRLUSD=X"),
        ("POL", "PLNUSD=X"),
    ]
    for iso3, ticker in fx_pairs:
        specs.append(
            SourceIndicatorSpec(
                source_id="yfinance",
                source_native_code=ticker,
                indicator_code="FX_USD",
                frequency="daily",
                countries_iso3=frozenset({iso3}),
            )
        )

    equity_indices = [
        ("TUR", "XU100.IS"),
        ("ZAF", "^J203.JO"),
        ("BRA", "^BVSP"),
        ("POL", "^WIG20"),
    ]
    for iso3, ticker in equity_indices:
        specs.append(
            SourceIndicatorSpec(
                source_id="yfinance",
                source_native_code=ticker,
                indicator_code="EQUITY_INDEX",
                frequency="daily",
                countries_iso3=frozenset({iso3}),
            )
        )

    return specs


def _adapter(
    indicators: Sequence[SourceIndicatorSpec] | None = None,
) -> YFinanceAdapter:
    return YFinanceAdapter(
        indicators=indicators if indicators is not None else _pilot_indicators(),
    )


def _make_ohlcv_df(
    dates: list[str],
    closes: list[float],
    ticker: str = "TRYUSD=X",
    multi_index: bool = True,
) -> pd.DataFrame:
    """Build a yfinance-shaped OHLCV DataFrame with DatetimeIndex.

    If ``multi_index`` is True, columns are MultiIndex like
    ``(Close, TRYUSD=X)`` -- the format yfinance >= 0.2.18 returns.
    Otherwise single-level columns like ``Close``.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    data = {
        "Open": closes,
        "High": [c * 1.01 for c in closes],
        "Low": [c * 0.99 for c in closes],
        "Close": closes,
        "Adj Close": closes,
        "Volume": [1000] * len(closes),
    }

    df = pd.DataFrame(data, index=idx)

    if multi_index:
        df.columns = pd.MultiIndex.from_tuples(
            [(col, ticker) for col in df.columns],
        )

    return df


class TestParseOhlcv:
    def test_extracts_close_price_from_multi_index(self) -> None:
        raw = _make_ohlcv_df(
            ["2024-01-02", "2024-01-03", "2024-01-04"],
            [0.033, 0.034, 0.032],
            multi_index=True,
        )
        df = YFinanceAdapter._parse_ohlcv(raw)
        assert len(df) == 3
        assert list(df.columns) == ["date", "value"]
        assert df["value"].tolist() == [0.033, 0.034, 0.032]

    def test_extracts_close_price_from_single_index(self) -> None:
        raw = _make_ohlcv_df(
            ["2024-01-02", "2024-01-03"],
            [100.0, 102.5],
            multi_index=False,
        )
        df = YFinanceAdapter._parse_ohlcv(raw)
        assert len(df) == 2
        assert df["value"].tolist() == [100.0, 102.5]

    def test_drops_nan_values(self) -> None:
        raw = _make_ohlcv_df(
            ["2024-01-02", "2024-01-03", "2024-01-04"],
            [0.033, float("nan"), 0.032],
            multi_index=True,
        )
        df = YFinanceAdapter._parse_ohlcv(raw)
        assert len(df) == 2
        assert df["value"].tolist() == [0.033, 0.032]

    def test_empty_input_returns_empty_df(self) -> None:
        raw = pd.DataFrame()
        df = YFinanceAdapter._parse_ohlcv(raw)
        assert df.empty


class TestConstructor:
    async def test_drops_non_yfinance_indicators(self) -> None:
        mixed = [
            SourceIndicatorSpec(
                source_id="yfinance",
                source_native_code="TRYUSD=X",
                indicator_code="FX_USD",
                frequency="daily",
                countries_iso3=frozenset({"TUR"}),
            ),
            SourceIndicatorSpec(
                source_id="fred",
                source_native_code="FPCPITOTLZGTUR",
                indicator_code="CPI_YOY",
                frequency="annual",
                countries_iso3=frozenset({"TUR"}),
            ),
        ]
        adapter = _adapter(indicators=mixed)
        manifest = await adapter.discover()
        assert len(manifest.indicators) == 1
        assert manifest.indicators[0].indicator_code == "FX_USD"


class TestFetch:
    async def test_returns_observations_from_mocked_download(self) -> None:
        ohlcv = _make_ohlcv_df(
            ["2024-06-03", "2024-06-04", "2024-06-05"],
            [0.031, 0.032, 0.030],
            ticker="TRYUSD=X",
        )

        with patch("ridge.adapters.yfinance_adapter.yf.download", return_value=ohlcv):
            adapter = _adapter()
            result = await adapter.fetch(
                FetchRequest(
                    source_id="yfinance",
                    countries_iso3=frozenset({"TUR"}),
                    indicator_codes=frozenset({"FX_USD"}),
                )
            )

        assert len(result) == 3
        for obs in result:
            assert obs.country_iso3 == "TUR"
            assert obs.indicator_code == "FX_USD"
            assert obs.source_id == "yfinance"
            assert obs.frequency == "daily"
        assert [o.value for o in result] == [0.031, 0.032, 0.030]

    async def test_empty_download_returns_empty(self) -> None:
        with patch(
            "ridge.adapters.yfinance_adapter.yf.download",
            return_value=pd.DataFrame(),
        ):
            adapter = _adapter()
            result = await adapter.fetch(
                FetchRequest(
                    source_id="yfinance",
                    countries_iso3=frozenset({"TUR"}),
                    indicator_codes=frozenset({"FX_USD"}),
                )
            )

        assert result == []

    async def test_exception_returns_empty_gracefully(self) -> None:
        with patch(
            "ridge.adapters.yfinance_adapter.yf.download",
            side_effect=Exception("network error"),
        ):
            adapter = _adapter()
            result = await adapter.fetch(
                FetchRequest(
                    source_id="yfinance",
                    countries_iso3=frozenset({"TUR"}),
                    indicator_codes=frozenset({"FX_USD"}),
                )
            )

        assert result == []

    async def test_unknown_country_is_skipped(self) -> None:
        with patch("ridge.adapters.yfinance_adapter.yf.download") as mock_dl:
            adapter = _adapter()
            result = await adapter.fetch(
                FetchRequest(
                    source_id="yfinance",
                    countries_iso3=frozenset({"XYZ"}),
                )
            )

        assert result == []
        mock_dl.assert_not_called()

    async def test_empty_country_filter_means_all(self) -> None:
        ohlcv = _make_ohlcv_df(["2024-06-03"], [1.0])

        with patch(
            "ridge.adapters.yfinance_adapter.yf.download",
            return_value=ohlcv,
        ):
            adapter = _adapter()
            result = await adapter.fetch(
                FetchRequest(
                    source_id="yfinance",
                    indicator_codes=frozenset({"FX_USD"}),
                )
            )

        countries_seen = {obs.country_iso3 for obs in result}
        assert countries_seen == {"NGA", "TUR", "ZAF", "BRA", "POL"}

    async def test_indicator_filter_restricts_output(self) -> None:
        ohlcv = _make_ohlcv_df(["2024-06-03"], [50000.0])

        with patch(
            "ridge.adapters.yfinance_adapter.yf.download",
            return_value=ohlcv,
        ):
            adapter = _adapter()
            result = await adapter.fetch(
                FetchRequest(
                    source_id="yfinance",
                    countries_iso3=frozenset({"TUR"}),
                    indicator_codes=frozenset({"EQUITY_INDEX"}),
                )
            )

        assert len(result) == 1
        assert result[0].indicator_code == "EQUITY_INDEX"

    async def test_date_range_is_forwarded(self) -> None:
        ohlcv = _make_ohlcv_df(["2024-06-03"], [1.0])

        with patch(
            "ridge.adapters.yfinance_adapter.yf.download",
            return_value=ohlcv,
        ) as mock_dl:
            adapter = YFinanceAdapter(
                indicators=[
                    SourceIndicatorSpec(
                        source_id="yfinance",
                        source_native_code="TRYUSD=X",
                        indicator_code="FX_USD",
                        frequency="daily",
                        countries_iso3=frozenset({"TUR"}),
                    )
                ],
            )
            await adapter.fetch(
                FetchRequest(
                    source_id="yfinance",
                    countries_iso3=frozenset({"TUR"}),
                    start=date(2024, 1, 1),
                    end=date(2024, 6, 30),
                )
            )

        mock_dl.assert_called_once()
        call_kwargs = mock_dl.call_args
        assert call_kwargs.kwargs["start"] == "2024-01-01"
        assert call_kwargs.kwargs["end"] == "2024-06-30"


class TestDiscover:
    async def test_manifest_covers_all_pilot_series(self) -> None:
        adapter = _adapter()
        manifest = await adapter.discover()

        assert manifest.source_id == "yfinance"
        assert len(manifest.indicators) == 9  # 5 FX + 4 equity

        all_countries: set[str] = set()
        all_canonical_codes: set[str] = set()
        for spec in manifest.indicators:
            all_countries.update(spec.countries_iso3)
            all_canonical_codes.add(spec.indicator_code)

        assert all_countries == {"NGA", "TUR", "ZAF", "BRA", "POL"}
        assert all_canonical_codes == {"FX_USD", "EQUITY_INDEX"}


class TestHealth:
    async def test_health_returns_report(self) -> None:
        adapter = _adapter()
        report = await adapter.health()
        assert report.source_id == "yfinance"
        assert report.healthy is True
