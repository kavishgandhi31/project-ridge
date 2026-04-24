"""Tests for the ingest runner.

Integration-style — these tests write real rows to the docker Postgres
via the ingest pipeline, then clean up afterward via the
``clean_fake_observations`` fixture. A stub adapter stands in for a
real source so the tests are deterministic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from ridge.adapters import HealthReport
from ridge.db.models import ObservationRow
from ridge.db.session import session_scope
from ridge.domain import FetchRequest, Observation, SourceManifest
from ridge.ingest.runner import run_ingest


class _FakeAdapter:
    """Minimal SourceAdapter implementation that returns a fixed list.

    Tags its source_id as 'fake' so the clean_fake_observations
    fixture isolates it from any real-source tests.
    """

    source_id = "fake"

    def __init__(self, observations: list[Observation]) -> None:
        self._observations = observations

    async def discover(self) -> SourceManifest:
        return SourceManifest(
            source_id=self.source_id,
            indicators=(),
            discovered_at=datetime(2026, 4, 11, tzinfo=UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        return self._observations

    async def health(self) -> HealthReport:
        return HealthReport(source_id=self.source_id, healthy=True)


def _obs(
    indicator_code: str,
    obs_date: date,
    value: float,
    vintage: datetime | None = None,
) -> Observation:
    """Build a test Observation with sensible defaults."""
    return Observation(
        country_iso3="NGA",
        indicator_code=indicator_code,
        source_id="fake",
        date=obs_date,
        value=value,
        frequency="monthly",
        vintage=vintage or datetime(2026, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 4, 11, tzinfo=UTC),
    )


@pytest.mark.usefixtures("clean_fake_observations")
class TestRunIngest:
    async def test_empty_fetch_writes_zero(self) -> None:
        adapter = _FakeAdapter([])
        result = await run_ingest(adapter, FetchRequest(source_id="fake"))
        assert result.observations_fetched == 0
        assert result.observations_written == 0

    async def test_single_observation_is_persisted(self) -> None:
        adapter = _FakeAdapter([_obs("TEST_CPI", date(2026, 1, 1), 18.5)])
        result = await run_ingest(adapter, FetchRequest(source_id="fake"))

        assert result.observations_fetched == 1
        assert result.observations_written == 1

        # Confirm the row actually reached the hypertable.
        async with session_scope() as session:
            stored = (
                (
                    await session.execute(
                        select(ObservationRow).where(
                            ObservationRow.source_id == "fake",
                            ObservationRow.indicator_code == "TEST_CPI",
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(stored) == 1
        assert stored[0].value == 18.5

    async def test_rerun_is_idempotent(self) -> None:
        """Running the same ingest twice should not duplicate rows."""
        adapter = _FakeAdapter([_obs("TEST_IDEM", date(2026, 2, 1), 4.2)])

        first = await run_ingest(adapter, FetchRequest(source_id="fake"))
        second = await run_ingest(adapter, FetchRequest(source_id="fake"))

        assert first.observations_written == 1
        # Second run: same PK, ON CONFLICT DO NOTHING skips it.
        assert second.observations_written == 0

    async def test_new_vintage_is_inserted_not_skipped(self) -> None:
        """A later vintage for the same (country, indicator, date) is a new row."""
        early = _obs(
            "TEST_REV",
            date(2026, 3, 1),
            10.0,
            vintage=datetime(2026, 3, 15, tzinfo=UTC),
        )
        late = _obs(
            "TEST_REV",
            date(2026, 3, 1),
            10.5,  # revised value
            vintage=datetime(2026, 4, 15, tzinfo=UTC),
        )

        await run_ingest(_FakeAdapter([early]), FetchRequest(source_id="fake"))
        result = await run_ingest(_FakeAdapter([late]), FetchRequest(source_id="fake"))

        # Both rows should exist — the later vintage is treated as
        # a revision, not a conflict.
        assert result.observations_written == 1

        async with session_scope() as session:
            stored = (
                (
                    await session.execute(
                        select(ObservationRow).where(
                            ObservationRow.source_id == "fake",
                            ObservationRow.indicator_code == "TEST_REV",
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(stored) == 2
        values = sorted(row.value for row in stored)
        assert values == [10.0, 10.5]
