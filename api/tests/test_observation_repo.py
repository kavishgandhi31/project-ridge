"""Tests for the observation repository functions.

These close a zero-coverage gap. The load-bearing test is
``test_returns_only_latest_vintage`` -- it would catch any regression
in the DISTINCT ON dedupe rewrite.
"""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from ridge.db.models.observation import ObservationRow
from ridge.db.models.source_indicator import SourceIndicatorRow
from ridge.db.repos.observation import (
    list_all_observations_for_quality,
    list_observations_for_scoring,
)
from ridge.db.session import session_scope

_TEST_COUNTRY = "ZZZ"
_TEST_SOURCE = "fake-obs-test"
_TEST_INDICATOR = "TEST_DEDUP"
_GLOBAL_TEST_SOURCE = "fake-global-test"
_GLOBAL_TEST_INDICATOR = "TEST_GLOBAL"
_NOW = datetime.datetime(2026, 5, 25, tzinfo=datetime.UTC)


@pytest.fixture
async def observation_repo_setup() -> AsyncIterator[None]:
    """Seed two test source_indicators (one country-specific scored,
    one global) and wipe test observations before/after each test.
    """

    async def _wipe() -> None:
        async with session_scope() as session:
            await session.execute(
                delete(ObservationRow).where(
                    ObservationRow.source_id.in_([_TEST_SOURCE, _GLOBAL_TEST_SOURCE])
                )
            )
            await session.execute(
                delete(SourceIndicatorRow).where(
                    SourceIndicatorRow.source_id.in_([_TEST_SOURCE, _GLOBAL_TEST_SOURCE])
                )
            )

    await _wipe()
    async with session_scope() as session:
        session.add_all(
            [
                SourceIndicatorRow(
                    source_id=_TEST_SOURCE,
                    source_native_code="TEST",
                    indicator_code=_TEST_INDICATOR,
                    frequency="daily",
                    countries_iso3=[_TEST_COUNTRY],
                    dimension="growth_momentum",
                    concept="test",
                    global_signal=False,
                    enabled=True,
                    created_at=_NOW,
                    updated_at=_NOW,
                ),
                SourceIndicatorRow(
                    source_id=_GLOBAL_TEST_SOURCE,
                    source_native_code="TEST_GLOBAL",
                    indicator_code=_GLOBAL_TEST_INDICATOR,
                    frequency="daily",
                    countries_iso3=["USA"],
                    dimension="risk_sentiment",
                    concept="test_global",
                    global_signal=True,
                    enabled=True,
                    created_at=_NOW,
                    updated_at=_NOW,
                ),
            ]
        )
    yield
    await _wipe()


def _make_obs(
    *,
    date: datetime.date,
    value: float,
    vintage: datetime.datetime,
    country: str = _TEST_COUNTRY,
    source: str = _TEST_SOURCE,
    indicator: str = _TEST_INDICATOR,
) -> ObservationRow:
    return ObservationRow(
        country_iso3=country,
        indicator_code=indicator,
        source_id=source,
        date=date,
        value=value,
        frequency="daily",
        vintage=vintage,
        ingested_at=vintage,
        quality_flags=[],
    )


async def _insert(rows: list[ObservationRow]) -> None:
    async with session_scope() as session:
        session.add_all(rows)


class TestListObservationsForScoring:
    async def test_returns_only_latest_vintage(self, observation_repo_setup: None) -> None:
        """Two vintages of the same (country, indicator, source, date):
        only the latest comes back. This is the regression test the
        codebase was missing.
        """
        d = datetime.date(2026, 3, 1)
        await _insert(
            [
                _make_obs(date=d, value=10.0, vintage=_NOW),
                _make_obs(date=d, value=20.0, vintage=_NOW + datetime.timedelta(days=1)),
            ]
        )

        async with session_scope() as session:
            obs = await list_observations_for_scoring(session, country_iso3=_TEST_COUNTRY)

        relevant = [o for o in obs if o.source_id == _TEST_SOURCE]
        assert len(relevant) == 1
        assert relevant[0].value == 20.0

    async def test_global_signal_observations_included(self, observation_repo_setup: None) -> None:
        """A global_signal observation stored under USA appears when
        scoring a different country.
        """
        await _insert(
            [
                _make_obs(
                    country="USA",
                    source=_GLOBAL_TEST_SOURCE,
                    indicator=_GLOBAL_TEST_INDICATOR,
                    date=datetime.date(2026, 3, 1),
                    value=4.5,
                    vintage=_NOW,
                )
            ]
        )

        async with session_scope() as session:
            obs = await list_observations_for_scoring(session, country_iso3=_TEST_COUNTRY)

        global_obs = [o for o in obs if o.source_id == _GLOBAL_TEST_SOURCE]
        assert len(global_obs) == 1
        assert global_obs[0].country_iso3 == "USA"
        assert global_obs[0].value == 4.5

    async def test_start_date_filter(self, observation_repo_setup: None) -> None:
        await _insert(
            [
                _make_obs(date=datetime.date(2025, 1, 1), value=1.0, vintage=_NOW),
                _make_obs(date=datetime.date(2026, 1, 1), value=2.0, vintage=_NOW),
            ]
        )

        async with session_scope() as session:
            obs = await list_observations_for_scoring(
                session,
                country_iso3=_TEST_COUNTRY,
                start_date=datetime.date(2026, 1, 1),
            )

        relevant = [o for o in obs if o.source_id == _TEST_SOURCE]
        assert len(relevant) == 1
        assert relevant[0].value == 2.0


class TestListAllObservationsForQuality:
    async def test_returns_only_latest_vintage(self, observation_repo_setup: None) -> None:
        d = datetime.date(2026, 3, 1)
        await _insert(
            [
                _make_obs(date=d, value=10.0, vintage=_NOW),
                _make_obs(date=d, value=20.0, vintage=_NOW + datetime.timedelta(days=1)),
            ]
        )

        async with session_scope() as session:
            obs = await list_all_observations_for_quality(session)

        relevant = [o for o in obs if o.source_id == _TEST_SOURCE]
        assert len(relevant) == 1
        assert relevant[0].value == 20.0
