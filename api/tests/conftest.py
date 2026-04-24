"""Shared pytest fixtures for the Ridge test suite."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from ridge.db.models import ObservationRow
from ridge.db.session import session_scope

PILOT_COUNTRIES: frozenset[str] = frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"})
"""Fixed pilot country set for Phase 1.

Five countries chosen to exercise diverse macro regimes:

- NGA (Nigeria) — EM, oil exporter, user's primary coverage
- TUR (Turkey) — high inflation edge case, stress-tests scoring
- ZAF (South Africa) — stagflation, deep market data, user's region
- BRA (Brazil) — large EM with rich data across all dimensions
- POL (Poland) — EE coverage, closer to DM, contrast to the above

Phase 1 adapter and golden tests pin to exactly this set. Later
phases will expand as needed.
"""


@pytest.fixture
def pilot_countries() -> frozenset[str]:
    """Access the pilot country set via pytest fixture."""
    return PILOT_COUNTRIES


@pytest.fixture
async def clean_fake_observations() -> AsyncIterator[None]:
    """Wipe ``source_id='fake'`` rows before and after each test.

    Tests that use the in-memory fake adapter write rows tagged with
    ``source_id='fake'``. This fixture keeps those rows isolated from
    tests that touch real sources, and ensures a test can re-run
    cleanly without carrying state from the previous run. No real
    adapter will ever use 'fake' as its source id, so this cleanup
    is safe from collateral damage on production data.
    """

    async def _wipe() -> None:
        async with session_scope() as session:
            await session.execute(delete(ObservationRow).where(ObservationRow.source_id == "fake"))

    await _wipe()
    yield
    await _wipe()
