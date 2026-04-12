"""Shared SDMX-JSON and SDMX-CSV parser for OECD, IMF, and BIS adapters.

Both the IMF (IFS, BOP datasets) and OECD (KEI, CLI datasets) return
data in SDMX-JSON format -- a deeply nested JSON structure that encodes
time series as observation arrays inside "dataSets". BIS returns data
in SDMX-CSV format. This module normalizes all three into flat pandas
DataFrames with (date, value) columns.

Ported verbatim from v1's ``src/utils/sdmx_parser.py``. The parsing
logic handles structural differences between SDMX-JSON 1.0 (IMF) and
2.0 (OECD), the IMF CompactData XML-to-JSON format, and the BIS CSV
column-name variations.

Three public functions:

* ``parse_sdmx_json(response)`` -- single series from JSON
* ``parse_sdmx_json_multi(response, series_dim_index)`` -- multi-series
  bulk JSON (e.g., all countries in one OECD request)
* ``parse_sdmx_csv(csv_text)`` -- BIS CSV format
"""

from __future__ import annotations

from io import StringIO
from typing import Any

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


def parse_sdmx_json(
    response: dict[str, Any],
    value_index: int = 0,
) -> pd.DataFrame:
    """Parse an SDMX-JSON response into DataFrame(date, value).

    Works for:
    - IMF IFS (dataservices.imf.org SDMX_JSON.svc)
    - IMF BOP (same endpoint, BOP dataset)
    - OECD SDMX API (sdmx.oecd.org)

    Extracts the first series found in the response. If the response
    contains multiple series, only the first is returned -- callers
    should request one series at a time via their query parameters.
    """
    try:
        # SDMX-JSON 2.0 (OECD) nests under "data"; 1.0 (IMF) is top-level
        inner = response.get("data", response)

        data_sets = inner.get("dataSets", inner.get("dataSet", []))
        if not data_sets:
            compact = response.get("CompactData", {})
            data_set = compact.get("DataSet", {})
            return _parse_imf_compact(data_set)

        data_set = data_sets[0] if isinstance(data_sets, list) else data_sets

        series_dict = data_set.get("series", {})
        if not series_dict:
            observations = data_set.get("observations", {})
            if observations:
                return _parse_flat_observations(observations, inner, value_index)
            logger.debug("sdmx.parse.no_series")
            return _empty_df()

        first_key = next(iter(series_dict))
        series = series_dict[first_key]
        observations = series.get("observations", {})

        if not observations:
            logger.debug("sdmx.parse.no_observations")
            return _empty_df()

        time_periods = _extract_time_periods(inner)
        if not time_periods:
            logger.warning("sdmx.parse.no_time_periods")
            return _empty_df()

        rows = _build_rows(observations, time_periods, value_index)
        return _rows_to_df(rows)

    except Exception as exc:
        logger.warning("sdmx.parse.error", error=str(exc))
        return _empty_df()


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


def parse_sdmx_csv(csv_text: str) -> pd.DataFrame:
    """Parse an SDMX-CSV response (used by BIS bulk data API).

    BIS returns CSV with columns like TIME_PERIOD, OBS_VALUE, FREQ,
    REF_AREA, etc. We extract just the date and value columns.
    """
    try:
        df = pd.read_csv(StringIO(csv_text))

        date_col = None
        value_col = None

        for col in df.columns:
            col_upper = col.upper().strip()
            if col_upper in ("TIME_PERIOD", "DATE", "PERIOD"):
                date_col = col
            elif col_upper in ("OBS_VALUE", "VALUE", "OBSERVATION_VALUE"):
                value_col = col

        if date_col is None or value_col is None:
            logger.warning(
                "sdmx.csv.missing_columns",
                columns=list(df.columns),
            )
            return _empty_df()

        result = pd.DataFrame(
            {
                "date": pd.to_datetime(df[date_col]),
                "value": pd.to_numeric(df[value_col], errors="coerce"),
            }
        )

        result = result.dropna(subset=["value"])
        return result.sort_values("date").reset_index(drop=True)

    except Exception as exc:
        logger.warning("sdmx.csv.parse_error", error=str(exc))
        return _empty_df()


def parse_sdmx_csv_multi(
    csv_text: str,
    country_column: str = "REF_AREA",
) -> dict[str, pd.DataFrame]:
    """Parse an SDMX-CSV response with multiple countries.

    BIS bulk downloads contain a country dimension column (typically
    ``REF_AREA``). This function splits the CSV by that column and
    returns one DataFrame per country code.
    """
    try:
        df = pd.read_csv(StringIO(csv_text))

        date_col = None
        value_col = None
        ref_col = None

        for col in df.columns:
            col_upper = col.upper().strip()
            if col_upper in ("TIME_PERIOD", "DATE", "PERIOD"):
                date_col = col
            elif col_upper in ("OBS_VALUE", "VALUE", "OBSERVATION_VALUE"):
                value_col = col
            elif col_upper == country_column.upper():
                ref_col = col

        if date_col is None or value_col is None or ref_col is None:
            logger.warning(
                "sdmx.csv_multi.missing_columns",
                columns=list(df.columns),
            )
            return {}

        output: dict[str, pd.DataFrame] = {}
        for ref_area, group in df.groupby(ref_col):
            result = pd.DataFrame(
                {
                    "date": pd.to_datetime(group[date_col]),
                    "value": pd.to_numeric(group[value_col], errors="coerce"),
                }
            )
            result = result.dropna(subset=["value"])
            result = result.sort_values("date").reset_index(drop=True)
            if not result.empty:
                output[str(ref_area)] = result

        return output

    except Exception as exc:
        logger.warning("sdmx.csv_multi.parse_error", error=str(exc))
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


def _parse_flat_observations(
    observations: dict[str, Any],
    response: dict[str, Any],
    value_index: int,
) -> pd.DataFrame:
    """Parse flat-format SDMX-JSON (dimensionAtObservation=AllDimensions).

    Some OECD endpoints put observations at the dataset level instead
    of nesting them inside series.
    """
    time_periods = _extract_time_periods(response)
    if not time_periods:
        return _empty_df()

    rows: list[dict[str, Any]] = []
    for key, obs_values in observations.items():
        parts = key.split(":")
        time_idx = int(parts[-1]) if parts else -1

        if time_idx < 0 or time_idx >= len(time_periods):
            continue

        val = obs_values[value_index] if isinstance(obs_values, list) else obs_values
        if val is None:
            continue

        rows.append({"date": time_periods[time_idx], "value": float(val)})

    if not rows:
        return _empty_df()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.groupby("date", as_index=False).agg(value=("value", "mean"))
    return df.sort_values("date").reset_index(drop=True)


def _parse_imf_compact(data_set: dict[str, Any]) -> pd.DataFrame:
    """Parse IMF CompactData XML-to-JSON format.

    The IMF's older API returns ``{"CompactData": {"DataSet": {"Series":
    {"Obs": [...]}}}}`` where each Obs has @TIME_PERIOD and @OBS_VALUE.
    """
    series = data_set.get("Series", {})
    if isinstance(series, list):
        series = series[0] if series else {}

    obs_list = series.get("Obs", [])
    if not obs_list:
        return _empty_df()

    if isinstance(obs_list, dict):
        obs_list = [obs_list]

    rows: list[dict[str, Any]] = []
    for obs in obs_list:
        date_str = obs.get("@TIME_PERIOD", "")
        val_str = obs.get("@OBS_VALUE", "")
        if not date_str or not val_str:
            continue
        try:
            rows.append({"date": date_str, "value": float(val_str)})
        except (ValueError, TypeError):
            continue

    return _rows_to_df(rows)


def _empty_df() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical (date, value) columns."""
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "value": pd.Series(dtype="float64"),
        }
    )
