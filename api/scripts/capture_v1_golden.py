#!/usr/bin/env python3
"""Capture v1 scoring output as a golden test fixture.

Runs v1's Scorer on its current cached data at ~/Documents/macro-tool
and dumps dimension scores + composites for all countries to JSON.

Usage:
    python scripts/capture_v1_golden.py

Output:
    tests/fixtures/golden_v1_capture.json

This script depends on v1's code and data being available. It is NOT
run in CI — it generates the fixture file that the nightly golden
test reads.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Add v1 to path
V1_ROOT = Path.home() / "Documents" / "macro-tool"
sys.path.insert(0, str(V1_ROOT))

OUTPUT = Path(__file__).parent.parent / "tests" / "fixtures" / "golden_v1_capture.json"


def main() -> None:
    try:
        from src.data.data_loader import load_all_data
        from src.processing.scorer import Scorer
        from src.utils.config_loader import load_settings, load_sources
    except ImportError as e:
        print(f"Cannot import v1 modules: {e}")
        print(f"Make sure v1 is at {V1_ROOT}")
        sys.exit(1)

    print("Loading v1 settings and sources...")
    settings = load_settings()
    sources = load_sources()

    print("Loading v1 data...")
    all_data = load_all_data(settings, sources)

    print(f"Scoring {len(all_data)} countries...")
    scorer = Scorer(settings, sources)
    results = scorer.score_all_countries(all_data)

    # Convert to serializable format
    output = {
        "_meta": {
            "description": "v1 scoring output captured for golden test comparison",
            "captured_at": datetime.now().isoformat(),
            "n_countries": len(results),
            "v1_path": str(V1_ROOT),
        },
        "countries": {},
    }

    for iso3, result in sorted(results.items()):
        output["countries"][iso3] = {
            "dimensions": {
                dim: round(score, 6) if score is not None else None
                for dim, score in result["dimensions"].items()
            },
            "composite": result["composite"],
            "news_heat": result.get("news_heat"),
        }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w") as f:
        json.dump(output, f, indent=2)

    scored = sum(1 for r in results.values() if r["composite"] is not None)
    print(f"Captured {len(results)} countries ({scored} with composites)")
    print(f"Written to {OUTPUT}")


if __name__ == "__main__":
    main()
