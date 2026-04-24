"""Tests for the GoogleNews EventSourceAdapter.

All tests use ``httpx.MockTransport`` -- no real Google News calls.
Tests exercise RSS XML parsing, source name extraction quirks,
country/indicator filtering, and non-XML response handling.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import httpx

from ridge.adapters.googlenews import GoogleNewsAdapter
from ridge.domain import FetchRequest, SourceIndicatorSpec

_ALL_PILOTS = frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"})


def _pilot_indicators() -> list[SourceIndicatorSpec]:
    return [
        SourceIndicatorSpec(
            source_id="googlenews",
            source_native_code="headline",
            indicator_code="headline",
            frequency="daily",
            countries_iso3=_ALL_PILOTS,
        ),
    ]


def _country_names() -> dict[str, str]:
    return {
        "NGA": "Nigeria",
        "TUR": "Turkey",
        "ZAF": "South Africa",
        "BRA": "Brazil",
        "POL": "Poland",
    }


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    indicators: Sequence[SourceIndicatorSpec] | None = None,
    country_names: Mapping[str, str] | None = None,
) -> GoogleNewsAdapter:
    return GoogleNewsAdapter(
        indicators=indicators if indicators is not None else _pilot_indicators(),
        country_names=country_names if country_names is not None else _country_names(),
        requests_per_minute=600000,
        transport=httpx.MockTransport(handler),
    )


_VALID_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Oil prices surge amid supply concerns - Reuters</title>
      <link>https://news.google.com/rss/articles/test1</link>
      <pubDate>Sat, 15 Jun 2024 12:00:00 GMT</pubDate>
      <source url="https://reuters.com">Reuters</source>
    </item>
    <item>
      <title>Central bank holds rates steady - Bloomberg</title>
      <link>https://news.google.com/rss/articles/test2</link>
      <pubDate>Fri, 14 Jun 2024 09:00:00 GMT</pubDate>
    </item>
    <item>
      <title></title>
      <link>https://news.google.com/rss/articles/test3</link>
      <pubDate>Thu, 13 Jun 2024 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class TestParseRss:
    def test_parses_valid_rss(self) -> None:
        articles = GoogleNewsAdapter._parse_rss(_VALID_RSS)
        # 3rd item has empty title, should be skipped
        assert len(articles) == 2

    def test_extracts_source_from_tag(self) -> None:
        articles = GoogleNewsAdapter._parse_rss(_VALID_RSS)
        assert articles[0]["source"] == "Reuters"

    def test_extracts_source_from_title_suffix(self) -> None:
        articles = GoogleNewsAdapter._parse_rss(_VALID_RSS)
        # 2nd item has no <source> tag, falls back to "- Bloomberg" split
        assert articles[1]["source"] == "Bloomberg"
        assert articles[1]["title"] == "Central bank holds rates steady"

    def test_parses_pubdate(self) -> None:
        articles = GoogleNewsAdapter._parse_rss(_VALID_RSS)
        assert articles[0]["date"].day == 15
        assert articles[0]["date"].month == 6

    def test_invalid_xml_returns_empty(self) -> None:
        assert GoogleNewsAdapter._parse_rss("not xml at all") == []

    def test_missing_channel_returns_empty(self) -> None:
        xml = '<?xml version="1.0"?><rss><nochannel/></rss>'
        assert GoogleNewsAdapter._parse_rss(xml) == []


class TestFetchEvents:
    async def test_returns_headline_events(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_VALID_RSS)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="googlenews",
                    countries_iso3=frozenset({"NGA"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 2
        for event in result:
            assert event.country_iso3 == "NGA"
            assert event.source_id == "googlenews"
            assert event.event_type == "headline"
            assert event.title is not None
            assert event.url is not None

    async def test_non_xml_response_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>Error page</html>")

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="googlenews",
                    countries_iso3=frozenset({"NGA"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []

    async def test_unknown_country_skipped(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, text=_VALID_RSS))
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="googlenews",
                    countries_iso3=frozenset({"XYZ"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []

    async def test_country_without_name_skipped(self) -> None:
        """If country has a registry entry but no name in the map, skip it."""
        indicators = [
            SourceIndicatorSpec(
                source_id="googlenews",
                source_native_code="headline",
                indicator_code="headline",
                frequency="daily",
                countries_iso3=frozenset({"NGA"}),
            )
        ]
        adapter = _adapter(
            lambda r: httpx.Response(200, text=_VALID_RSS),
            indicators=indicators,
            country_names={},  # no NGA name
        )
        try:
            result = await adapter.fetch_events(FetchRequest(source_id="googlenews"))
        finally:
            await adapter.close()
        assert result == []

    async def test_max_articles_respected(self) -> None:
        adapter = GoogleNewsAdapter(
            indicators=_pilot_indicators(),
            country_names=_country_names(),
            max_articles=1,
            requests_per_minute=600000,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text=_VALID_RSS)),
        )
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="googlenews",
                    countries_iso3=frozenset({"NGA"}),
                )
            )
        finally:
            await adapter.close()
        assert len(result) == 1

    async def test_dedup_keys_use_url_hash(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_VALID_RSS)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch_events(
                FetchRequest(
                    source_id="googlenews",
                    countries_iso3=frozenset({"NGA"}),
                )
            )
        finally:
            await adapter.close()

        assert all(event.dedup_key.startswith("googlenews:headline:") for event in result)
        assert len({e.dedup_key for e in result}) == len(result)


class TestHealth:
    async def test_health_returns_report(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, text=""))
        try:
            report = await adapter.health()
        finally:
            await adapter.close()
        assert report.source_id == "googlenews"
        assert report.healthy is True
