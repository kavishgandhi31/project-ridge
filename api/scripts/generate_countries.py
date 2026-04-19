"""Generate v2 countries.yaml from v1 reference data.

Reads v1's config/countries.yaml and produces a v2-compatible
countries.yaml with the fields the Hornet v2 CountrySpec needs,
plus metadata for source coverage filtering.

Usage:
    cd api && .venv/bin/python scripts/generate_countries.py
"""

from __future__ import annotations

import yaml

# v1-reference symlink removed; seed data already captured in seeds/data/countries.yaml
V1_PATH = "../v1-reference/config/countries.yaml"  # historical — v1 data already imported
V2_PATH = "src/hornet/seeds/data/countries.yaml"

# Sources and their approximate country coverage.
# Used to set per-country source coverage flags.
# BIS covers ~48 countries, OECD ~44, IMF IFS ~60.
BIS_COVERED = {
    "ARG",
    "AUS",
    "AUT",
    "BEL",
    "BRA",
    "CAN",
    "CHE",
    "CHL",
    "CHN",
    "COL",
    "CZE",
    "DEU",
    "DNK",
    "ESP",
    "FIN",
    "FRA",
    "GBR",
    "GRC",
    "HKG",
    "HUN",
    "IDN",
    "IND",
    "IRL",
    "ISR",
    "ITA",
    "JPN",
    "KOR",
    "MEX",
    "MYS",
    "NLD",
    "NOR",
    "NZL",
    "PER",
    "PHL",
    "POL",
    "PRT",
    "ROU",
    "RUS",
    "SAU",
    "SGP",
    "SWE",
    "THA",
    "TUR",
    "TWN",
    "USA",
    "ZAF",
}

OECD_COVERED = {
    "AUS",
    "AUT",
    "BEL",
    "BRA",
    "CAN",
    "CHE",
    "CHL",
    "CHN",
    "COL",
    "CRI",
    "CZE",
    "DEU",
    "DNK",
    "ESP",
    "EST",
    "FIN",
    "FRA",
    "GBR",
    "GRC",
    "HUN",
    "IDN",
    "IND",
    "IRL",
    "ISL",
    "ISR",
    "ITA",
    "JPN",
    "KOR",
    "LTU",
    "LUX",
    "LVA",
    "MEX",
    "NLD",
    "NOR",
    "NZL",
    "POL",
    "PRT",
    "SVK",
    "SVN",
    "SWE",
    "TUR",
    "USA",
    "ZAF",
}


def main() -> None:
    with open(V1_PATH) as f:
        v1_data = yaml.safe_load(f)

    v1_countries = v1_data["countries"]
    v2_countries = []

    for c in v1_countries:
        iso3 = c["iso3"]
        iso2 = c["iso2"]
        name = c["name"]
        region = c.get("region")
        market_type = c.get("market_type")
        msci_status = c.get("msci_status")
        active = c.get("active", True)
        monitored_only = c.get("monitored_only", False)
        fx_pair = c.get("fx_pair")
        equity_index = c.get("indices", {}).get("equity")
        income_group = None  # v1 doesn't have this, WorldBank will fill it

        # Determine enabled status for v2:
        # Active and not monitored_only = enabled
        # DM countries marked inactive in v1 = enabled (we want DM data)
        # Monitored-only = enabled but flagged
        enabled = True

        entry: dict[str, object] = {
            "iso3": iso3,
            "iso2": iso2,
            "name": name,
            "region": region,
            "income_group": income_group,
            "enabled": enabled,
        }

        # v2-specific metadata (stored in notes as structured YAML)
        notes_parts = []
        if market_type:
            notes_parts.append(f"market_type={market_type}")
        if msci_status:
            notes_parts.append(f"msci={msci_status}")
        if monitored_only:
            notes_parts.append("monitored_only")
            coverage_reason = c.get("coverage_reason", "")
            if coverage_reason:
                notes_parts.append(f"reason={coverage_reason}")
        if not active:
            notes_parts.append("v1_inactive")
        if fx_pair:
            notes_parts.append(f"fx={fx_pair}")
        if equity_index:
            notes_parts.append(f"equity={equity_index}")

        # Source coverage flags
        covers = []
        if iso3 in BIS_COVERED:
            covers.append("bis")
        if iso3 in OECD_COVERED:
            covers.append("oecd")
        if covers:
            notes_parts.append(f"sources={'+'.join(covers)}")

        entry["notes"] = "; ".join(notes_parts) if notes_parts else None

        v2_countries.append(entry)

    # Sort by ISO3 for stable output
    v2_countries.sort(key=lambda c: str(c["iso3"]))

    output = {"countries": v2_countries}

    header = (
        "# Hornet v2 country registry -- 183 countries.\n"
        "#\n"
        "# Generated from v1-reference/config/countries.yaml by\n"
        "# scripts/generate_countries.py. Metadata in 'notes' field:\n"
        "#   market_type=em/fm/ef/dm/standalone\n"
        "#   msci=emerging/frontier/developed\n"
        "#   monitored_only -- sanctioned/conflict, tracked for contagion\n"
        "#   fx=TICKER -- yfinance FX pair\n"
        "#   equity=TICKER -- yfinance equity index\n"
        "#   sources=bis+oecd -- which specialized sources cover this country\n"
        "#\n"
        "# To regenerate: python scripts/generate_countries.py\n"
        "\n"
    )

    with open(V2_PATH, "w") as f:
        f.write(header)
        yaml.dump(output, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"Generated {len(v2_countries)} countries -> {V2_PATH}")

    # Summary
    from collections import Counter

    types = Counter()
    for c in v2_countries:
        notes = c.get("notes", "") or ""
        for part in notes.split("; "):
            if part.startswith("market_type="):
                types[part.split("=")[1]] += 1
    print(f"By market type: {dict(types)}")
    monitored = sum(1 for c in v2_countries if "monitored_only" in str(c.get("notes", "")))
    print(f"Monitored-only: {monitored}")


if __name__ == "__main__":
    main()
