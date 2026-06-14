"""Tests for the shared SDMX parser.

Exercises ``parse_sdmx_json_multi`` against hand-crafted SDMX fixtures.
No network, no external dependencies.
"""

from __future__ import annotations

from typing import Any

from ridge.adapters.sdmx import parse_sdmx_json_multi


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
