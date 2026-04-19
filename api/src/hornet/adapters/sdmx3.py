"""Parser for SDMX 3.0 JSON data responses.

The IMF retired its legacy SDMX-JSON 1.0 endpoint at dataservices.imf.org
in June 2025. The replacement is a SDMX 3.0 REST API at api.imf.org that
returns a different JSON shape. This module parses the new format.

The legacy ``hornet.adapters.sdmx`` module is still used by OECD, so it is
left untouched. Only the IMF adapter uses this new parser.

SDMX 3.0 JSON response shape (excerpt)::

    {
      "data": {
        "structures": [{
          "dimensions": {
            "series":       [ {id, values:[{id}]}, ... ],   # e.g. COUNTRY, INDICATOR
            "observation":  [ {id, values:[{value}]} ]      # usually TIME_PERIOD
          },
          "attributes": {
            "series":      [ {id, values:[{id}]}, ... ],
            "observation": [ {id, values:[{id}]}, ... ]
          }
        }],
        "dataSets": [{
          "series": {
            "0:0:0:0:0": {                     # colon-sep dim value indices
              "attributes": [0, None, 0, None], # index into series attr values
              "observations": {
                "0": ["-235563000000", 0, 0, None]   # [value, obs_attrs...]
              }
            }
          }
        }]
      }
    }

Two fiddly details worth noting here because they will bite future readers:
- Series dimension values live under ``values[i].id``; period values (on the
  observation dim) live under ``values[i].value``. Different keys for what
  looks like the same concept.
- Attribute values can be ``None`` (missing), an ``int`` (codelist index),
  or a raw string literal when the attribute has no codelist enumeration.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


_PERIOD_MONTH_RE = re.compile(r"^(\d{4})-M(\d{2})$")
_PERIOD_QUARTER_RE = re.compile(r"^(\d{4})-Q(\d)$")
_PERIOD_ANNUAL_RE = re.compile(r"^(\d{4})$")


def _parse_period(period: str) -> datetime.date:
    """Convert an SDMX TIME_PERIOD string to the first day of its period.

    Supports monthly (``YYYY-Mnn``), quarterly (``YYYY-Qn``), and annual
    (``YYYY``). Raises ValueError for anything else so the caller can
    skip that observation rather than silently emit a bogus date.
    """
    m = _PERIOD_MONTH_RE.match(period)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), 1)
    m = _PERIOD_QUARTER_RE.match(period)
    if m:
        year = int(m.group(1))
        quarter = int(m.group(2))
        return datetime.date(year, (quarter - 1) * 3 + 1, 1)
    m = _PERIOD_ANNUAL_RE.match(period)
    if m:
        return datetime.date(int(m.group(1)), 1, 1)
    raise ValueError(f"Unrecognized SDMX period format: {period!r}")


def _decode_codelist_value(value: Any, codes: list[str]) -> Any:
    """Resolve a codelist index to its code string; pass through raw values."""
    if value is None:
        return None
    if isinstance(value, int):
        if codes and 0 <= value < len(codes):
            return codes[value]
        return None
    return str(value)


def parse_sdmx3_json(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse an SDMX 3.0 JSON data response into a flat list of observations.

    Returns one record per non-null observation, with series dimension and
    attribute values decoded from their codelist indices. Suppressed values
    (``OBS_VALUE = None``) are filtered out entirely.

    Each record::

        {
            "date": datetime.date,      # first day of the period
            "value": float,
            "dims": {dim_id: code, ...},    # e.g. {"COUNTRY": "USA", "INDICATOR": "CAB", ...}
            "attrs": {attr_id: value, ...}, # merged series + observation attributes
        }

    Returns an empty list if the response has no data (no dataSets or no
    matching series) or is structurally malformed.
    """
    data = payload.get("data", {})
    datasets = data.get("dataSets", [])
    structures = data.get("structures", [])
    if not datasets or not structures:
        return []

    structure = structures[0]

    # ---- dimension metadata ----
    series_dim_meta = structure.get("dimensions", {}).get("series", [])
    dim_ids = [d.get("id") for d in series_dim_meta]
    dim_codes = [[v.get("id") for v in d.get("values", [])] for d in series_dim_meta]

    obs_dim_meta = structure.get("dimensions", {}).get("observation", [])
    if not obs_dim_meta:
        return []
    period_values = [v.get("value") for v in obs_dim_meta[0].get("values", [])]

    # ---- attribute metadata ----
    series_attr_meta = structure.get("attributes", {}).get("series", [])
    series_attr_ids = [a.get("id") for a in series_attr_meta]
    series_attr_codes = [[v.get("id") for v in a.get("values", [])] for a in series_attr_meta]

    obs_attr_meta = structure.get("attributes", {}).get("observation", [])
    obs_attr_ids = [a.get("id") for a in obs_attr_meta]
    obs_attr_codes = [[v.get("id") for v in a.get("values", [])] for a in obs_attr_meta]

    # ---- walk the series ----
    results: list[dict[str, Any]] = []
    for series_key, series_data in datasets[0].get("series", {}).items():
        dims: dict[str, str | None] = {}
        for i, idx_str in enumerate(series_key.split(":")):
            if i >= len(dim_ids):
                break
            try:
                idx = int(idx_str)
            except ValueError:
                dims[dim_ids[i]] = None
                continue
            codes = dim_codes[i]
            dims[dim_ids[i]] = codes[idx] if 0 <= idx < len(codes) else None

        series_attrs_raw = series_data.get("attributes") or []
        series_attrs: dict[str, Any] = {}
        for i, attr_id in enumerate(series_attr_ids):
            raw = series_attrs_raw[i] if i < len(series_attrs_raw) else None
            series_attrs[attr_id] = _decode_codelist_value(raw, series_attr_codes[i])

        for obs_key, obs_list in (series_data.get("observations") or {}).items():
            try:
                period_idx = int(obs_key)
            except ValueError:
                continue
            if not (0 <= period_idx < len(period_values)):
                continue
            period = period_values[period_idx]
            if period is None or not obs_list:
                continue

            raw_value = obs_list[0]
            if raw_value is None:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue

            obs_attrs: dict[str, Any] = {}
            for i, attr_id in enumerate(obs_attr_ids):
                raw = obs_list[i + 1] if (i + 1) < len(obs_list) else None
                obs_attrs[attr_id] = _decode_codelist_value(raw, obs_attr_codes[i])

            try:
                date = _parse_period(period)
            except ValueError:
                logger.debug("sdmx3.unparseable_period", period=period)
                continue

            results.append(
                {
                    "date": date,
                    "value": value,
                    "dims": dims,
                    "attrs": {**series_attrs, **obs_attrs},
                }
            )

    return results
