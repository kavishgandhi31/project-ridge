"""Shared SDMX-JSON parser for the OECD adapter.

OECD returns data in SDMX-JSON 2.0 format -- a deeply nested JSON
structure that encodes time series as observation arrays inside
"dataSets". This module normalizes one common shape (multi-series
responses keyed by a country dimension) into flat pandas DataFrames
with (date, value) columns.

Ported verbatim from v1's ``src/utils/sdmx_parser.py``. The parsing
logic handles SDMX-JSON 1.0 and 2.0 structural differences. IMF moved
to SDMX 3.0 (see ``sdmx3.py``); BIS parses CSV inline in its adapter.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


def parse_sdmx_json_multi(
    response: dict[str, Any],
    series_dim_index: int = 0,
    value_index: int = 0,
) -> dict[str, pd.DataFrame]:
    """Parse an SDMX-JSON response containing multiple series.

    When OECD returns data for all countries in one request, the series
    dict has keys like ``"0:0:0"``, ``"1:0:0"`` where the first index
    is the country dimension. This function splits the response into
    one DataFrame per series-dimension value (typically the country code).
    """
    try:
        inner = response.get("data", response)

        data_sets = inner.get("dataSets", inner.get("dataSet", []))
        if not data_sets:
            return {}

        data_set = data_sets[0] if isinstance(data_sets, list) else data_sets

        series_dict = data_set.get("series", {})
        if not series_dict:
            return {}

        time_periods = _extract_time_periods(inner)
        if not time_periods:
            return {}

        dim_values = _extract_dimension_values(inner, series_dim_index)

        result: dict[str, list[dict[str, Any]]] = {}
        for series_key, series_data in series_dict.items():
            parts = series_key.split(":")
            dim_idx = int(parts[series_dim_index]) if series_dim_index < len(parts) else -1
            dim_label = dim_values.get(dim_idx, str(dim_idx))

            observations = series_data.get("observations", {})
            rows = _build_rows(observations, time_periods, value_index)

            if rows:
                if dim_label not in result:
                    result[dim_label] = []
                result[dim_label].extend(rows)

        output: dict[str, pd.DataFrame] = {}
        for label, rows in result.items():
            output[label] = _rows_to_df(rows)

        return output

    except Exception as exc:
        logger.warning("sdmx.parse_multi.error", error=str(exc))
        return {}


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _extract_time_periods(response: dict[str, Any]) -> list[str]:
    """Extract ordered time period labels from SDMX-JSON structure.

    Handles both SDMX-JSON 1.0 ("structure" dict) and 2.0
    ("structures" list).
    """
    structure = response.get("structure", {})
    if not structure:
        structures = response.get("structures", [])
        if structures:
            structure = structures[0]
    dimensions = structure.get("dimensions", {})

    obs_dims = dimensions.get("observation", [])
    for dim in obs_dims:
        role = dim.get("role", "")
        dim_id = dim.get("id", "")
        if role == "time" or dim_id in ("TIME_PERIOD", "TIME"):
            return [v.get("id", v.get("name", "")) for v in dim.get("values", [])]

    for dim in obs_dims:
        values = dim.get("values", [])
        if values and _looks_like_dates(values):
            return [v.get("id", v.get("name", "")) for v in values]

    return []


def _extract_dimension_values(
    response: dict[str, Any],
    dim_index: int,
) -> dict[int, str]:
    """Map dimension position index to its label (e.g., 0 -> "USA")."""
    structure = response.get("structure", {})
    if not structure:
        structures = response.get("structures", [])
        if structures:
            structure = structures[0]
    dimensions = structure.get("dimensions", {})
    series_dims = dimensions.get("series", [])

    dim_values: dict[int, str] = {}
    if dim_index < len(series_dims):
        dim_def = series_dims[dim_index]
        for i, v in enumerate(dim_def.get("values", [])):
            dim_values[i] = v.get("id", v.get("name", str(i)))
    return dim_values


def _looks_like_dates(values: list[dict[str, Any]]) -> bool:
    """Quick heuristic: do the dimension values look like date strings?"""
    if not values:
        return False
    sample = values[0].get("id", values[0].get("name", ""))
    return len(sample) >= 4 and sample[:4].isdigit()


def _build_rows(
    observations: dict[str, Any],
    time_periods: list[str],
    value_index: int,
) -> list[dict[str, Any]]:
    """Build (date, value) row dicts from SDMX observations."""
    rows: list[dict[str, Any]] = []
    for obs_idx, obs_values in observations.items():
        idx = int(obs_idx)
        if idx >= len(time_periods):
            continue

        val = obs_values[value_index] if isinstance(obs_values, list) else obs_values
        if val is None:
            continue

        rows.append({"date": time_periods[idx], "value": float(val)})
    return rows


def _rows_to_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert row dicts to a sorted DataFrame(date, value)."""
    if not rows:
        return _empty_df()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _empty_df() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical (date, value) columns."""
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "value": pd.Series(dtype="float64"),
        }
    )
