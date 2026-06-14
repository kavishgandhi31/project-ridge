"""Tests for the EventRecord domain type and ORM model.

Unit tests (no DB) for domain/ORM roundtrip, plus integration tests
for the event_record hypertable and event ingest runner.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, select

from ridge.db.models.event_record import EventRecordRow
from ridge.db.session import session_scope
from ridge.domain.event import EventRecord
from ridge.ingest.runner import run_event_ingest

_NOW = datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC)


def _tone_event(iso3: str = "NGA", d: date = date(2024, 6, 15), value: float = -2.5) -> EventRecord:
    return EventRecord(
        country_iso3=iso3,
        source_id="gdelt",
        event_type="tone",
        date=d,
        dedup_key=f"gdelt:tone:{iso3}:{d}",
        value=value,
        ingested_at=_NOW,
    )


def _headline_event(
    iso3: str = "NGA",
    title: str = "Oil prices surge",
    url: str = "https://example.com/1",
) -> EventRecord:
    return EventRecord(
        country_iso3=iso3,
        source_id="gdelt",
        event_type="headline",
        date=date(2024, 6, 15),
        dedup_key=f"gdelt:headline:{hash(url)}",
        title=title,
        url=url,
        metadata={"source_name": "reuters.com", "tone": -1.5},
        ingested_at=_NOW,
    )


class TestEventRecordDomain:
    def test_constructs_tone_event(self) -> None:
        event = _tone_event()
        assert event.country_iso3 == "NGA"
        assert event.event_type == "tone"
        assert event.value == -2.5
        assert event.title is None
        assert event.url is None
        assert event.metadata == {}

    def test_constructs_headline_event(self) -> None:
        event = _headline_event()
        assert event.event_type == "headline"
        assert event.title == "Oil prices surge"
        assert event.url == "https://example.com/1"
        assert event.metadata["source_name"] == "reuters.com"

    def test_country_iso3_uppercased(self) -> None:
        event = _tone_event(iso3="nga")
        assert event.country_iso3 == "NGA"

    def test_frozen(self) -> None:
        event = _tone_event()
        with pytest.raises(ValueError):
            event.value = 0.0  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError):
            EventRecord(
                country_iso3="NGA",
                source_id="gdelt",
                event_type="tone",
                date=date(2024, 6, 15),
                dedup_key="test",
                ingested_at=_NOW,
                unknown_field="bad",  # type: ignore[call-arg]
            )


class TestEventRecordRowRoundtrip:
    def test_from_domain_preserves_fields(self) -> None:
        event = _headline_event()
        row = EventRecordRow.from_domain(event)

        assert row.country_iso3 == "NGA"
        assert row.source_id == "gdelt"
        assert row.event_type == "headline"
        assert row.title == "Oil prices surge"
        assert row.url == "https://example.com/1"
        assert row.metadata_["source_name"] == "reuters.com"

    def test_roundtrip(self) -> None:
        original = _tone_event()
        row = EventRecordRow.from_domain(original)
        roundtripped = row.to_domain()

        assert roundtripped.country_iso3 == original.country_iso3
        assert roundtripped.source_id == original.source_id
        assert roundtripped.event_type == original.event_type
        assert roundtripped.date == original.date
        assert roundtripped.dedup_key == original.dedup_key
        assert roundtripped.value == original.value
        assert roundtripped.metadata == original.metadata


async def _clean_events() -> None:
    async with session_scope() as session:
        await session.execute(delete(EventRecordRow).where(EventRecordRow.source_id == "gdelt"))


class TestEventIngest:
    async def test_inserts_events(self) -> None:
        await _clean_events()
        events = [
            _tone_event(iso3="NGA", d=date(2024, 6, 15), value=-2.5),
            _tone_event(iso3="TUR", d=date(2024, 6, 15), value=-1.0),
        ]

        result = await run_event_ingest("gdelt", events)

        assert result.events_received == 2
        assert result.events_written == 2

        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(EventRecordRow).where(EventRecordRow.source_id == "gdelt")
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 2

    async def test_rerun_is_idempotent(self) -> None:
        await _clean_events()
        events = [_tone_event()]

        first = await run_event_ingest("gdelt", events)
        second = await run_event_ingest("gdelt", events)

        assert first.events_written == 1
        assert second.events_written == 0

    async def test_empty_list_is_noop(self) -> None:
        result = await run_event_ingest("gdelt", [])
        assert result.events_received == 0
        assert result.events_written == 0

    async def test_headline_with_metadata_persists(self) -> None:
        await _clean_events()
        events = [_headline_event()]

        await run_event_ingest("gdelt", events)

        async with session_scope() as session:
            row = (
                await session.execute(
                    select(EventRecordRow).where(
                        EventRecordRow.source_id == "gdelt",
                        EventRecordRow.event_type == "headline",
                    )
                )
            ).scalar_one()
        assert row.title == "Oil prices surge"
        assert row.metadata_["source_name"] == "reuters.com"
        assert row.metadata_["tone"] == -1.5
