"""Tests for the shared SDMX parser.

Exercises all three public functions against hand-crafted SDMX
fixtures. No network, no external dependencies.
"""

from __future__ import annotations

from typing import Any

from ridge.adapters.sdmx import (
    parse_sdmx_csv,
    parse_sdmx_csv_multi,
    parse_sdmx_json,
    parse_sdmx_json_multi,
)


def _oecd_response(
    country_values: dict[str, list[float]],
    time_periods: list[str],
) -> dict[str, Any]:
    """Build a minimal OECD-shaped SDMX-JSON 2.0 response.

    ``country_values`` maps country code -> list of values aligned
    with ``time_periods``.
    """
    country_codes = sorted(country_values.keys())
    series: dict[str, Any] = {}
    for i, code in enumerate(country_codes):
        obs = {str(t): [v] for t, v in enumerate(country_values[code]) if v is not None}
        series[f"{i}:0:0:0:0:0:0"] = {"observations": obs}

    return {
        "data": {
            "dataSets": [{"series": series}],
            "structure": {
                "dimensions": {
                    "series": [
                        {
                            "id": "REF_AREA",
                            "values": [{"id": code} for code in country_codes],
                        },
                    ],
                    "observation": [
                        {
                            "id": "TIME_PERIOD",
                            "role": "time",
                            "values": [{"id": tp} for tp in time_periods],
                        },
                    ],
                },
            },
        },
    }


def _single_series_response(
    values: list[float],
    time_periods: list[str],
) -> dict[str, Any]:
    """Build a minimal single-series SDMX-JSON response."""
    obs = {str(i): [v] for i, v in enumerate(values)}
    return {
        "data": {
            "dataSets": [{"series": {"0:0:0": {"observations": obs}}}],
            "structure": {
                "dimensions": {
                    "series": [],
                    "observation": [
                        {
                            "id": "TIME_PERIOD",
                            "role": "time",
                            "values": [{"id": tp} for tp in time_periods],
                        },
                    ],
                },
            },
        },
    }


class TestParseSdmxJson:
    def test_parses_single_series(self) -> None:
        resp = _single_series_response(
            [99.5, 100.2, 101.1],
            ["2024-01", "2024-02", "2024-03"],
        )
        df = parse_sdmx_json(resp)
        assert len(df) == 3
        assert df["value"].tolist() == [99.5, 100.2, 101.1]

    def test_skips_none_values(self) -> None:
        obs = {"0": [99.5], "1": [None], "2": [101.1]}
        resp: dict[str, Any] = {
            "data": {
                "dataSets": [{"series": {"0:0:0": {"observations": obs}}}],
                "structure": {
                    "dimensions": {
                        "series": [],
                        "observation": [
                            {
                                "id": "TIME_PERIOD",
                                "role": "time",
                                "values": [
                                    {"id": "2024-01"},
                                    {"id": "2024-02"},
                                    {"id": "2024-03"},
                                ],
                            }
                        ],
                    }
                },
            }
        }
        df = parse_sdmx_json(resp)
        assert len(df) == 2

    def test_empty_response_returns_empty_df(self) -> None:
        df = parse_sdmx_json({})
        assert df.empty

    def test_missing_time_periods_returns_empty(self) -> None:
        resp: dict[str, Any] = {
            "data": {
                "dataSets": [{"series": {"0": {"observations": {"0": [1.0]}}}}],
                "structure": {"dimensions": {"series": [], "observation": []}},
            }
        }
        df = parse_sdmx_json(resp)
        assert df.empty

    def test_imf_compact_format(self) -> None:
        resp: dict[str, Any] = {
            "CompactData": {
                "DataSet": {
                    "Series": {
                        "Obs": [
                            {"@TIME_PERIOD": "2024", "@OBS_VALUE": "3.5"},
                            {"@TIME_PERIOD": "2023", "@OBS_VALUE": "2.1"},
                        ]
                    }
                }
            }
        }
        df = parse_sdmx_json(resp)
        assert len(df) == 2
        assert df["value"].iloc[0] == 2.1
        assert df["value"].iloc[1] == 3.5


class TestParseSdmxJsonMulti:
    def test_splits_by_country(self) -> None:
        resp = _oecd_response(
            {"BRA": [99.0, 100.0], "TUR": [101.0, 102.0]},
            ["2024-01", "2024-02"],
        )
        result = parse_sdmx_json_multi(resp, series_dim_index=0)
        assert set(result.keys()) == {"BRA", "TUR"}
        assert len(result["BRA"]) == 2
        assert len(result["TUR"]) == 2
        assert result["BRA"]["value"].tolist() == [99.0, 100.0]
        assert result["TUR"]["value"].tolist() == [101.0, 102.0]

    def test_empty_response(self) -> None:
        assert parse_sdmx_json_multi({}) == {}

    def test_skips_none_observations(self) -> None:
        # Build a response where POL has a None value at index 1.
        # The _oecd_response helper filters None from country_values,
        # so we build the raw response manually.
        obs = {"0": [99.0], "2": [101.0]}  # index 1 omitted = no value
        resp: dict[str, Any] = {
            "data": {
                "dataSets": [{"series": {"0:0:0:0:0:0:0": {"observations": obs}}}],
                "structure": {
                    "dimensions": {
                        "series": [
                            {"id": "REF_AREA", "values": [{"id": "POL"}]},
                        ],
                        "observation": [
                            {
                                "id": "TIME_PERIOD",
                                "role": "time",
                                "values": [
                                    {"id": "2024-01"},
                                    {"id": "2024-02"},
                                    {"id": "2024-03"},
                                ],
                            },
                        ],
                    },
                },
            },
        }
        result = parse_sdmx_json_multi(resp, series_dim_index=0)
        assert len(result["POL"]) == 2


class TestParseSdmxCsv:
    def test_parses_bis_style_csv(self) -> None:
        csv = "TIME_PERIOD,OBS_VALUE,REF_AREA\n2024-01,1.5,US\n2024-02,1.6,US\n"
        df = parse_sdmx_csv(csv)
        assert len(df) == 2
        assert df["value"].tolist() == [1.5, 1.6]

    def test_handles_alternative_column_names(self) -> None:
        csv = "DATE,VALUE,COUNTRY\n2024-01,3.0,BR\n"
        df = parse_sdmx_csv(csv)
        assert len(df) == 1
        assert df["value"].iloc[0] == 3.0

    def test_missing_columns_returns_empty(self) -> None:
        csv = "FOO,BAR\n1,2\n"
        df = parse_sdmx_csv(csv)
        assert df.empty

    def test_coerces_non_numeric_values(self) -> None:
        csv = "TIME_PERIOD,OBS_VALUE\n2024-01,1.5\n2024-02,N/A\n2024-03,2.0\n"
        df = parse_sdmx_csv(csv)
        assert len(df) == 2


class TestParseSdmxCsvMulti:
    def test_splits_by_country(self) -> None:
        csv = (
            "TIME_PERIOD,OBS_VALUE,REF_AREA\n"
            "2024-01,1.5,US\n"
            "2024-01,2.5,BR\n"
            "2024-02,1.6,US\n"
            "2024-02,2.6,BR\n"
        )
        result = parse_sdmx_csv_multi(csv)
        assert set(result.keys()) == {"US", "BR"}
        assert len(result["US"]) == 2
        assert len(result["BR"]) == 2
