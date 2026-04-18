"""Expand yfinance source_indicators for all 183 countries.

Reads v1's countries.yaml for FX pairs and equity index tickers,
then replaces the per-country yfinance entries in source_indicators.yaml
while preserving all other sources and the yfinance global entries
(commodity futures, S&P 500, EM ETFs).

Usage:
    cd hornet && .venv/bin/python scripts/expand_yfinance_indicators.py
"""

from __future__ import annotations

from typing import Any

import yaml

V1_PATH = "../v1-reference/config/countries.yaml"
SI_PATH = "src/hornet/seeds/data/source_indicators.yaml"

# Indicator codes that are global yfinance entries (not per-country)
GLOBAL_YF_CODES = {
    "GOLD_FUTURES",
    "SILVER_FUTURES",
    "OIL_WTI_FUTURES",
    "OIL_BRENT_FUTURES",
    "NATGAS_FUTURES",
    "COPPER_FUTURES",
    "WHEAT_FUTURES",
    "CORN_FUTURES",
    "SOYBEAN_FUTURES",
    "SP500",
    "EM_EQUITY_ETF",
    "EM_BOND_ETF",
}


def main() -> None:
    # Read v1 countries
    with open(V1_PATH) as f:
        v1_data = yaml.safe_load(f)

    # Read current source_indicators as raw text and parse
    with open(SI_PATH) as f:
        si_text = f.read()
    si_data = yaml.safe_load(si_text)

    # Separate entries: keep non-yfinance + yfinance global, remove yfinance per-country
    kept: list[dict[str, Any]] = []
    removed = 0
    for entry in si_data["source_indicators"]:
        if entry["source_id"] != "yfinance" or entry["indicator_code"] in GLOBAL_YF_CODES:
            kept.append(entry)
        else:
            removed += 1

    print(f"Removed {removed} old yfinance per-country entries")

    # Generate new per-country entries from v1.
    # Group by (source_native_code, indicator_code) to handle shared-currency
    # tickers (e.g. EURUSD=X used by 19 Eurozone countries, XOFUSD=X by 8
    # West African CFA countries). The PK is (source_id, source_native_code)
    # so duplicates cause INSERT conflicts.
    countries = v1_data["countries"]

    # Phase 1: collect all tickers and group countries per ticker
    fx_groups: dict[str, list[str]] = {}  # ticker -> [iso3, ...]
    fx_names: dict[str, str] = {}  # ticker -> first country name
    eq_groups: dict[str, list[str]] = {}
    eq_names: dict[str, str] = {}

    for c in sorted(countries, key=lambda x: x["iso3"]):
        if not c.get("active") or c.get("monitored_only"):
            continue
        iso3 = c["iso3"]
        if iso3 == "USA":
            continue

        fx = c.get("fx_pair")
        if fx:
            fx_groups.setdefault(fx, []).append(iso3)
            if fx not in fx_names:
                fx_names[fx] = c["name"]

        eq = c.get("indices", {}).get("equity")
        if eq:
            eq_groups.setdefault(eq, []).append(iso3)
            if eq not in eq_names:
                eq_names[eq] = c["name"]

    # Phase 2: generate entries with multi-country lists where needed
    new_entries: list[dict[str, Any]] = []

    for ticker, iso3s in sorted(fx_groups.items()):
        name = fx_names[ticker]
        if len(iso3s) > 1:
            display_name = f"Shared FX ({len(iso3s)} countries) per USD"
        else:
            display_name = f"{name} FX per USD"
        new_entries.append(
            {
                "source_id": "yfinance",
                "source_native_code": ticker,
                "indicator_code": "FX_USD",
                "frequency": "daily",
                "countries_iso3": sorted(iso3s),
                "name": display_name,
                "unit": "exchange_rate",
                "dimension": "risk_sentiment",
                "concept": "fx_momentum",
            }
        )

    for ticker, iso3s in sorted(eq_groups.items()):
        name = eq_names[ticker]
        if len(iso3s) > 1:
            display_name = f"Shared equity index ({len(iso3s)} countries)"
        else:
            display_name = f"{name} equity index"
        new_entries.append(
            {
                "source_id": "yfinance",
                "source_native_code": ticker,
                "indicator_code": "EQUITY_INDEX",
                "frequency": "daily",
                "countries_iso3": sorted(iso3s),
                "name": display_name,
                "unit": "index_level",
                "dimension": "risk_sentiment",
                "concept": "equity_momentum",
            }
        )

    print(f"Generated {len(new_entries)} new yfinance per-country entries")

    # Insert new entries after the last global yfinance entry
    # Find the position of the last yfinance global entry
    last_global_idx = -1
    for i, entry in enumerate(kept):
        if entry["source_id"] == "yfinance" and entry["indicator_code"] in GLOBAL_YF_CODES:
            last_global_idx = i

    if last_global_idx >= 0:
        # Insert after the last global yfinance entry
        final = kept[: last_global_idx + 1] + new_entries + kept[last_global_idx + 1 :]
    else:
        # No global entries found, just append
        final = kept + new_entries

    si_data["source_indicators"] = final

    # Write back preserving the header comments
    # Extract header (lines starting with #)
    header_lines = []
    for line in si_text.split("\n"):
        if line.startswith("#") or line.strip() == "":
            header_lines.append(line)
        else:
            break

    header = "\n".join(header_lines) + "\n"

    with open(SI_PATH, "w") as f:
        f.write(header)
        yaml.dump(si_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Verify
    with open(SI_PATH) as f:
        verify = yaml.safe_load(f)
    total = len(verify["source_indicators"])
    yf = sum(1 for e in verify["source_indicators"] if e["source_id"] == "yfinance")
    others = total - yf
    print(f"Final: {total} total ({yf} yfinance, {others} other sources)")


if __name__ == "__main__":
    main()
