"""Idempotent seed loaders for the DB-backed registries.

Two seed files under ``src/hornet/seeds/data/``:

* ``countries.yaml`` populates the ``country`` table.
* ``source_indicators.yaml`` populates the ``source_indicator`` table.

Both loaders do UPSERT (``INSERT ... ON CONFLICT DO UPDATE``) so they
can be re-run at any time — editing the YAML and calling
``seed_all()`` again is the supported workflow for adding a country
or a new source-indicator mapping. No migration required.

Tests call ``seed_all()`` to prepare a fresh DB. Production operators
will call it via a ``hornet seeds`` CLI command (Phase 2 CLI work).
"""

from hornet.seeds.loader import (
    load_countries_from_yaml,
    load_source_indicators_from_yaml,
    seed_all,
    seed_countries,
    seed_source_indicators,
)

__all__ = [
    "load_countries_from_yaml",
    "load_source_indicators_from_yaml",
    "seed_all",
    "seed_countries",
    "seed_source_indicators",
]
