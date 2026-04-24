"""YAML seed loaders and idempotent DB upserts for the registry tables.

Two discrete responsibilities, kept separate because tests want them
separate:

1. ``load_*_from_yaml`` — pure functions that parse YAML files into
   typed ``CountrySpec`` / ``SourceIndicatorSpec`` domain objects.
   Zero database dependency. Testable without any infrastructure.

2. ``seed_*`` — async functions that take a session and a list of
   domain specs and perform an ``INSERT ... ON CONFLICT DO UPDATE``
   against the relevant table. Idempotent: re-running a seed with
   unchanged YAML is a no-op (well, it re-writes every row, but the
   net state is identical). Editing the YAML and re-running applies
   the diff.

The split is deliberate: tests for the YAML parser can run without a
DB; tests for the upsert logic can run without touching YAML.
"""

from __future__ import annotations

import datetime
from importlib import resources
from pathlib import Path
from typing import Any, cast

import structlog
import yaml
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ridge.alerts.config import AlertConfig
from ridge.db.models.country import CountryRow
from ridge.db.models.source_indicator import SourceIndicatorRow
from ridge.db.session import session_scope
from ridge.domain.scoring import ScoringConfig
from ridge.domain.source import CountrySpec, SourceIndicatorSpec
from ridge.llm.config import LLMConfig
from ridge.quality.config import QualityConfig

logger = structlog.get_logger(__name__)


_SEED_PACKAGE = "ridge.seeds.data"
_COUNTRIES_FILENAME = "countries.yaml"
_SOURCE_INDICATORS_FILENAME = "source_indicators.yaml"
_SCORING_CONFIG_FILENAME = "scoring_config.yaml"
_QUALITY_CONFIG_FILENAME = "quality_config.yaml"
_ALERT_CONFIG_FILENAME = "alert_config.yaml"
_LLM_CONFIG_FILENAME = "llm_config.yaml"


def _read_seed_file(filename: str) -> str:
    """Read a YAML seed file from the packaged ``ridge.seeds.data`` resources.

    Uses ``importlib.resources`` so seed files are found both in an
    editable install and in a built wheel — no filesystem assumptions.
    """
    ref = resources.files(_SEED_PACKAGE) / filename
    try:
        return ref.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Seed file {filename!r} not found in package {_SEED_PACKAGE!r}. "
            f"Is the ridge package installed correctly? "
            f"Expected at: {ref}"
        ) from None


def load_countries_from_yaml(yaml_text: str | None = None) -> list[CountrySpec]:
    """Parse countries.yaml into a list of ``CountrySpec``.

    When ``yaml_text`` is None the packaged default is loaded; tests
    pass an explicit string to exercise edge cases without touching
    the packaged file.
    """
    text = yaml_text if yaml_text is not None else _read_seed_file(_COUNTRIES_FILENAME)
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("countries.yaml must deserialize to a mapping at the top level")

    entries = raw.get("countries")
    if not isinstance(entries, list):
        raise ValueError("countries.yaml must have a top-level 'countries' list")

    specs: list[CountrySpec] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"each country entry must be a mapping, got: {entry!r}")
        specs.append(CountrySpec(**cast(dict[str, Any], entry)))
    return specs


def load_source_indicators_from_yaml(yaml_text: str | None = None) -> list[SourceIndicatorSpec]:
    """Parse source_indicators.yaml into a list of ``SourceIndicatorSpec``.

    Converts ``countries_iso3`` from YAML list to the frozenset the
    domain type expects. All other fields pass straight through to the
    Pydantic constructor which enforces the schema.
    """
    text = yaml_text if yaml_text is not None else _read_seed_file(_SOURCE_INDICATORS_FILENAME)
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("source_indicators.yaml must deserialize to a mapping at the top level")

    entries = raw.get("source_indicators")
    if not isinstance(entries, list):
        raise ValueError("source_indicators.yaml must have a top-level 'source_indicators' list")

    specs: list[SourceIndicatorSpec] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"each source_indicator entry must be a mapping, got: {entry!r}")
        entry_dict = cast(dict[str, Any], dict(entry))
        # YAML gives us a plain list; the Pydantic model wants frozenset.
        # Pydantic validates frequency against the Frequency Literal type
        # on construction — no need to pre-validate here.
        countries = entry_dict.get("countries_iso3", [])
        entry_dict["countries_iso3"] = frozenset(countries)
        specs.append(SourceIndicatorSpec(**entry_dict))
    return specs


def load_scoring_config_from_yaml(yaml_text: str | None = None) -> ScoringConfig:
    """Parse scoring_config.yaml into a ``ScoringConfig``.

    When ``yaml_text`` is None the packaged default is loaded; tests
    pass an explicit string to exercise edge cases without touching
    the packaged file.
    """
    text = yaml_text if yaml_text is not None else _read_seed_file(_SCORING_CONFIG_FILENAME)
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("scoring_config.yaml must deserialize to a mapping at the top level")

    config_data = raw.get("scoring_config")
    if not isinstance(config_data, dict):
        raise ValueError("scoring_config.yaml must have a top-level 'scoring_config' mapping")

    return ScoringConfig(**cast(dict[str, Any], config_data))


def load_alert_config_from_yaml(yaml_text: str | None = None) -> AlertConfig:
    """Parse alert_config.yaml into an ``AlertConfig``.

    When ``yaml_text`` is None the packaged default is loaded; tests
    pass an explicit string to exercise edge cases without touching
    the packaged file.
    """
    text = yaml_text if yaml_text is not None else _read_seed_file(_ALERT_CONFIG_FILENAME)
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("alert_config.yaml must deserialize to a mapping at the top level")

    config_data = raw.get("alert_config")
    if not isinstance(config_data, dict):
        raise ValueError("alert_config.yaml must have a top-level 'alert_config' mapping")

    return AlertConfig(**cast(dict[str, Any], config_data))


def load_quality_config_from_yaml(yaml_text: str | None = None) -> QualityConfig:
    """Parse quality_config.yaml into a ``QualityConfig``.

    When ``yaml_text`` is None the packaged default is loaded; tests
    pass an explicit string to exercise edge cases without touching
    the packaged file.
    """
    text = yaml_text if yaml_text is not None else _read_seed_file(_QUALITY_CONFIG_FILENAME)
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("quality_config.yaml must deserialize to a mapping at the top level")

    config_data = raw.get("quality_config")
    if not isinstance(config_data, dict):
        raise ValueError("quality_config.yaml must have a top-level 'quality_config' mapping")

    return QualityConfig(**cast(dict[str, Any], config_data))


def load_llm_config_from_yaml(yaml_text: str | None = None) -> LLMConfig:
    """Parse llm_config.yaml into an ``LLMConfig``.

    When ``yaml_text`` is None the packaged default is loaded; tests
    pass an explicit string to exercise edge cases without touching
    the packaged file.

    Unlike other configs, LLMConfig has no top-level wrapper key --
    the YAML root IS the config. This matches the structure of
    llm_config.yaml where provider settings sit at the root level.
    """
    text = yaml_text if yaml_text is not None else _read_seed_file(_LLM_CONFIG_FILENAME)
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("llm_config.yaml must deserialize to a mapping at the top level")

    return LLMConfig(**cast(dict[str, Any], raw))


async def seed_countries(
    session: AsyncSession,
    specs: list[CountrySpec],
    *,
    now: datetime.datetime | None = None,
) -> int:
    """Upsert ``specs`` into the ``country`` table. Returns row count.

    Idempotent: the ON CONFLICT branch updates every non-PK column
    (including ``updated_at``) so re-running with unchanged YAML is
    effectively a no-op for data, and re-running with edited YAML
    applies the diff.

    ``now`` is injectable so tests can pin a deterministic timestamp.
    Defaults to ``datetime.now(UTC)``.
    """
    if not specs:
        return 0

    timestamp = now if now is not None else datetime.datetime.now(datetime.UTC)
    values = [
        {
            "iso3": spec.iso3,
            "iso2": spec.iso2,
            "name": spec.name,
            "region": spec.region,
            "income_group": spec.income_group,
            "enabled": spec.enabled,
            "notes": spec.notes,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        for spec in specs
    ]

    stmt = pg_insert(CountryRow).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["iso3"],
        set_={
            "iso2": stmt.excluded.iso2,
            "name": stmt.excluded.name,
            "region": stmt.excluded.region,
            "income_group": stmt.excluded.income_group,
            "enabled": stmt.excluded.enabled,
            "notes": stmt.excluded.notes,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)
    logger.info("seeds.countries.upserted", count=len(specs))
    return len(specs)


async def seed_source_indicators(
    session: AsyncSession,
    specs: list[SourceIndicatorSpec],
    *,
    now: datetime.datetime | None = None,
) -> int:
    """Upsert ``specs`` into the ``source_indicator`` table. Returns row count.

    Same idempotent pattern as ``seed_countries``: ON CONFLICT updates
    every non-PK column. Composite PK is (source_id, source_native_code).
    """
    if not specs:
        return 0

    timestamp = now if now is not None else datetime.datetime.now(datetime.UTC)
    values = [
        {
            "source_id": spec.source_id,
            "source_native_code": spec.source_native_code,
            "indicator_code": spec.indicator_code,
            "frequency": spec.frequency,
            "countries_iso3": sorted(spec.countries_iso3),
            "name": spec.name,
            "unit": spec.unit,
            "enabled": spec.enabled,
            "dimension": spec.dimension,
            "concept": spec.concept,
            "global_signal": spec.global_signal,
            "notes": spec.notes,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        for spec in specs
    ]

    stmt = pg_insert(SourceIndicatorRow).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source_id", "source_native_code"],
        set_={
            "indicator_code": stmt.excluded.indicator_code,
            "frequency": stmt.excluded.frequency,
            "countries_iso3": stmt.excluded.countries_iso3,
            "name": stmt.excluded.name,
            "unit": stmt.excluded.unit,
            "enabled": stmt.excluded.enabled,
            "dimension": stmt.excluded.dimension,
            "concept": stmt.excluded.concept,
            "global_signal": stmt.excluded.global_signal,
            "notes": stmt.excluded.notes,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)
    logger.info("seeds.source_indicators.upserted", count=len(specs))
    return len(specs)


async def seed_all(
    *,
    session: AsyncSession | None = None,
    countries_yaml: str | Path | None = None,
    source_indicators_yaml: str | Path | None = None,
    now: datetime.datetime | None = None,
) -> tuple[int, int]:
    """Load the default seed files and upsert both registries.

    Call this from a CLI, from tests, or from a FastAPI startup hook.
    When ``session`` is None a fresh ``session_scope`` is opened and
    committed internally — appropriate for CLI / script use. When a
    session is supplied the caller owns the transaction — appropriate
    for tests that already have a session they want to reuse.

    Optional ``countries_yaml`` / ``source_indicators_yaml`` arguments
    take either a filesystem path (str or Path) to a YAML file, or
    leave as None to load the packaged default under
    ``ridge.seeds.data``. Tests pass a Path to exercise edge cases
    without editing the packaged files.

    Returns ``(n_countries, n_source_indicators)``.
    """

    def _resolve(
        arg: str | Path | None,
        filename: str,
    ) -> str:
        if arg is None:
            return _read_seed_file(filename)
        return Path(arg).read_text(encoding="utf-8")

    country_specs = load_countries_from_yaml(_resolve(countries_yaml, _COUNTRIES_FILENAME))
    source_indicator_specs = load_source_indicators_from_yaml(
        _resolve(source_indicators_yaml, _SOURCE_INDICATORS_FILENAME)
    )

    async def _run(sess: AsyncSession) -> tuple[int, int]:
        n_countries = await seed_countries(sess, country_specs, now=now)
        n_source_indicators = await seed_source_indicators(sess, source_indicator_specs, now=now)
        return n_countries, n_source_indicators

    if session is not None:
        return await _run(session)

    async with session_scope() as sess:
        return await _run(sess)
