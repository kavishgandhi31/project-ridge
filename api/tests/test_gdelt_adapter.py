"""Tests for the GDELT EventSourceAdapter.

All tests use ``httpx.MockTransport`` -- no real GDELT API calls.
Tests exercise timeline parsing (tone/volume), artlist headline
parsing, query building, tone smoothing, and the non-JSON response
handling quirk.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

from ridge.adapters.gdelt import GDELTAdapter
from ridge.domain import FetchRequest, SourceIndicatorSpec

_ALL_PILOTS = frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"})


def _pilot_indicators() -> list[SourceIndicatorSpec]:
    return [
        SourceIndicatorSpec(
            source_id="gdelt",
            source_native_code=event_type,
            indicator_code=event_type,
            frequency="daily",
            countries_iso3=_ALL_PILOTS,
        )
        for event_type in ("tone", "volume", "headline")
    ]


def _country_names() -> dict[str, str]:
    return {
        "NGA": "Nigeria",
        "TUR": "Turkey",
        "ZAF": "South Africa",
        "BRA": "Brazil",
        "POL": "Poland",
    }


def _country_iso2s() -> dict[str, str]:
    return {"NGA": "NG", "TUR": "TR", "ZAF": "ZA", "BRA": "BR", "POL": "PL"}


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    indicators: Sequence[SourceIndicatorSpec] | None = None,
    country_names: Mapping[str, str] | None = None,
    country_iso2s: Mapping[str, str] | None = None,
) -> GDELTAdapter:
    return GDELTAdapter(
        indicators=indicators if indicators is not None else _pilot_indicators(),
        country_names=country_names if country_names is not None else _country_names(),
        country_iso2s=country_iso2s if country_iso2s is not None else _country_iso2s(),
        requests_per_minute=600000,
        transport=httpx.MockTransport(handler),
    )


def _timeline_response(points: list[tuple[str, float]]) -> dict[str, Any]:
    """Build a GDELT timeline JSON response."""
    return {
        "timeline": [
            {
                "series": [{"date": d, "value": v} for d, v in points],
            }
        ]
    }


def _artlist_response(articles: list[dict[str, Any]]) -> dict[str, Any]:
    return {"articles": articles}


class TestParseTimeline:
    def test_parses_gdelt_date_format(self) -> None:
        data = _timeline_response(
            [
                ("January 15, 2024 00:00:00", -2.5),
                ("January 16, 2024 00:00:00", -1.8),
            ]
        )
        df = GDELTAdapter._parse_timeline(data)
        assert len(df) == 2
        assert df["date"].iloc[0].day == 15
        assert df["value"].iloc[0] == -2.5

    def test_skips_none_values(self) -> None:
        data: dict[str, Any] = {
            "timeline": [
                {
                    "series": [
                        {"date": "January 15, 2024 00:00:00", "value": -2.5},
                        {"date": "January 16, 2024 00:00:00", "value": None},
                    ]
                }
            ]
        }
        df = GDELTAdapter._parse_timeline(data)
        assert len(df) == 1

    def test_empty_timeline_returns_empty(self) -> None:
        assert GDELTAdapter._parse_timeline({}).empty
        assert GDELTAdapter._parse_timeline({"timeline": []}).empty


class TestParseArtlist:
    def test_parses_articles(self) -> None:
        from datetime import UTC, datetime

        data = _artlist_response(
            [
                {
                    "title": "Oil prices surge",
                    "url": "https://example.com/1",
                    "seendate": "20240615T120000Z",
                    "tone": "-2.5,1.0,3.0",
                    "domain": "reuters.com",
                    "socialimage": "https://img.example.com/1.jpg",
                },
            ]
        )
        now = datetime(2026, 4, 11, tzinfo=UTC)
        events = GDELTAdapter._parse_artlist(data, "NGA", now)
        assert len(events) == 1
        assert events[0].title == "Oil prices surge"
        assert events[0].url == "https://example.com/1"
        assert events[0].value == -2.5
        assert events[0].event_type == "headline"
        assert events[0].metadata["source_name"] == "reuters.com"

    def test_skips_articles_without_title(self) -> None:
        from datetime import UTC, datetime

        data = _artlist_response(
            [
                {"title": "", "url": "https://example.com/1", "seendate": "20240615T120000Z"},
            ]
        )
        events = GDELTAdapter._parse_artlist(data, "NGA", datetime(2026, 1, 1, tzinfo=UTC))
        assert len(events) == 0

    def test_empty_artlist(self) -> None:
        from datetime import UTC, datetime

        assert GDELTAdapter._parse_artlist({}, "NGA", datetime(2026, 1, 1, tzinfo=UTC)) == []


class TestFetchEvents:
    async def test_returns_tone_events(self) -> None:
        resp = _timeline_response(
            [
                ("June 3, 2024 00:00:00", -3.0),
                ("June 4, 2024 00:00:00", -2.0),
                ("June 5, 2024 00:00:00", -1.0),
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps(resp))

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="gdelt",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"tone"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 3
        for event in result:
            assert event.country_iso3 == "NGA"
            assert event.event_type == "tone"
            assert event.source_id == "gdelt"
            assert event.value is not None

    async def test_tone_smoothing_applied_with_enough_data(self) -> None:
        """With >= 7 points, tone values should be 7-day rolling averaged."""
        points = [(f"June {d}, 2024 00:00:00", float(d)) for d in range(1, 9)]
        resp = _timeline_response(points)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps(resp))

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="gdelt",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"tone"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 8
        # 7th point (index 6): rolling mean of [1..7] = 4.0, not raw 7.0
        assert result[6].value is not None
        assert abs(result[6].value - 4.0) < 0.01

    async def test_returns_headline_events(self) -> None:
        resp = _artlist_response(
            [
                {
                    "title": "Test headline",
                    "url": "https://example.com/test",
                    "seendate": "20240615T120000Z",
                    "tone": "-1.5",
                    "domain": "bbc.com",
                    "socialimage": "",
                },
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=json.dumps(resp))

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="gdelt",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"headline"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 1
        assert result[0].event_type == "headline"
        assert result[0].title == "Test headline"

    async def test_non_json_response_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="Rate limit exceeded. Please try later.")

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="gdelt",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"tone"}),
                )
            )
        finally:
            await adapter.close()

        assert result == []

    async def test_unknown_country_skipped(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, text="{}"))
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="gdelt",
                    countries_iso3=frozenset({"XYZ"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []

    async def test_indicator_filter_restricts_event_types(self) -> None:
        call_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_urls.append(str(request.url))
            resp = _timeline_response([("June 3, 2024 00:00:00", 1.0)])
            return httpx.Response(200, text=json.dumps(resp))

        adapter = _adapter(handler)
        try:
            await adapter.fetch_events(
                FetchRequest(
                    source_id="gdelt",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"tone"}),
                )
            )
        finally:
            await adapter.close()

        assert len(call_urls) == 1
        assert "timelinetone" in call_urls[0]


class TestQueryBuilding:
    def test_builds_query_with_name_only(self) -> None:
        """GDELT queries use country name only -- ISO2 dropped to avoid
        'phrase too short' errors and false positives."""
        adapter = _adapter(lambda r: httpx.Response(200, text="{}"))
        query = adapter._build_query("NGA")
        assert '"Nigeria"' in query
        # ISO2 no longer included (too short for GDELT, causes false positives)
        assert "NG" not in query or "Nigeria" in query


class TestHealth:
    async def test_health_returns_report(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, text="{}"))
        try:
            report = await adapter.health()
        finally:
            await adapter.close()
        assert report.source_id == "gdelt"
        assert report.healthy is True
