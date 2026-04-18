"""Tests for the SDMX 3.0 JSON parser.

Fixtures under ``tests/fixtures/imf_sdmx3/`` are real captured responses
from ``api.imf.org/external/sdmx/3.0``, one per dataflow shape we rely on.
Regenerate them with the capture script in ``hornet/scripts`` if IMF's
response schema changes.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from hornet.adapters.sdmx3 import (
    _parse_period,
    parse_sdmx3_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "imf_sdmx3"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


# -----------------------------
# Period parsing
# -----------------------------


def test_parse_period_monthly() -> None:
    assert _parse_period("2024-M03") == datetime.date(2024, 3, 1)
    assert _parse_period("1955-M01") == datetime.date(1955, 1, 1)


def test_parse_period_quarterly() -> None:
    assert _parse_period("2024-Q1") == datetime.date(2024, 1, 1)
    assert _parse_period("2024-Q4") == datetime.date(2024, 10, 1)


def test_parse_period_annual() -> None:
    assert _parse_period("2024") == datetime.date(2024, 1, 1)


def test_parse_period_rejects_unknown_format() -> None:
    import pytest

    with pytest.raises(ValueError):
        _parse_period("2024-03")  # missing the M prefix
    with pytest.raises(ValueError):
        _parse_period("garbage")


# -----------------------------
# Fixture-driven: CPI (5-dim monthly)
# -----------------------------


def test_cpi_usa_monthly_returns_12_observations() -> None:
    records = parse_sdmx3_json(_load("cpi_usa_monthly.json"))
    assert len(records) == 12
    for r in records:
        assert isinstance(r["date"], datetime.date)
        assert isinstance(r["value"], float)
        assert r["value"] > 0
        assert r["dims"] == {
            "COUNTRY": "USA",
            "INDEX_TYPE": "CPI",
            "COICOP_1999": "_T",
            "TYPE_OF_TRANSFORMATION": "IX",
            "FREQUENCY": "M",
        }


def test_cpi_usa_monthly_dates_are_strictly_increasing() -> None:
    # IMF monthly series can have gaps (e.g. one month missing if not yet
    # published), so don't assert monthly-delta -- just ordering + first-of-month.
    records = parse_sdmx3_json(_load("cpi_usa_monthly.json"))
    dates = [r["date"] for r in records]
    assert dates == sorted(set(dates))  # strictly increasing, no dups
    assert all(d.day == 1 for d in dates)


# -----------------------------
# Fixture-driven: BOP (5-dim quarterly)
# -----------------------------


def test_bop_current_account_parses_quarterly_flows() -> None:
    records = parse_sdmx3_json(_load("bop_usa_current_account.json"))
    assert len(records) >= 1
    # USA current account is structurally negative -- sanity check
    assert all(r["value"] < 0 for r in records)
    # Quarterly dates: only Jan/Apr/Jul/Oct first
    for r in records:
        assert r["date"].day == 1
        assert r["date"].month in (1, 4, 7, 10)
    # Dims include BOP-specific ones
    sample = records[0]["dims"]
    assert sample["INDICATOR"] == "CAB"
    assert sample["BOP_ACCOUNTING_ENTRY"] == "NETCD_T"
    assert sample["UNIT"] == "USD"
    assert sample["FREQUENCY"] == "Q"


# -----------------------------
# Fixture-driven: ER (4-dim)
# -----------------------------


def test_er_pol_fx_rate_has_sane_plausible_values() -> None:
    records = parse_sdmx3_json(_load("er_pol_fx_rate.json"))
    assert len(records) >= 1
    for r in records:
        # PLN per USD lives roughly in the 3-5 range for the last decade
        assert 2.5 < r["value"] < 6.0
        assert r["dims"]["COUNTRY"] == "POL"
        assert r["dims"]["INDICATOR"] == "XDC_USD"


# -----------------------------
# Fixture-driven: IRFCL (4-dim with SECTOR)
# -----------------------------


def test_irfcl_pol_reserves_monthly_levels() -> None:
    records = parse_sdmx3_json(_load("irfcl_pol_reserves.json"))
    assert len(records) >= 1
    for r in records:
        assert r["value"] > 0  # reserves are a non-negative stock
        assert r["dims"]["COUNTRY"] == "POL"
        assert r["dims"]["SECTOR"] == "S1XS1311"


# -----------------------------
# Fixture-driven: MFS_IR (3-dim lending rate)
# -----------------------------


def test_mfs_ir_lending_rate_is_percent_per_annum() -> None:
    records = parse_sdmx3_json(_load("mfs_ir_zaf_lending.json"))
    assert len(records) >= 1
    for r in records:
        # Lending rate as percent -- should be single digits to low teens for ZAF
        assert 0 < r["value"] < 30
        assert r["dims"]["COUNTRY"] == "ZAF"


# -----------------------------
# Edge cases
# -----------------------------


def test_empty_payload_returns_empty_list() -> None:
    assert parse_sdmx3_json({}) == []
    assert parse_sdmx3_json({"data": {}}) == []
    assert parse_sdmx3_json({"data": {"dataSets": [], "structures": []}}) == []


def test_missing_observation_values_are_filtered() -> None:
    payload = _load("cpi_usa_monthly.json")
    # Inject a null value into the first series' observations
    first_series = next(iter(payload["data"]["dataSets"][0]["series"].values()))
    obs = first_series["observations"]
    # Pick some existing obs and blank its value out
    some_key = next(iter(obs))
    obs[some_key][0] = None

    records = parse_sdmx3_json(payload)
    # Should have one less record than the full fixture
    assert len(records) == 11


def test_no_structures_returns_empty() -> None:
    assert parse_sdmx3_json({"data": {"dataSets": [{}]}}) == []
