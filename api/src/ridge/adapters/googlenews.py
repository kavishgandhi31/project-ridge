"""Google News RSS adapter -- ports v1's GoogleNewsClient to Ridge.

Fetches headlines from Google News RSS feeds and maps them to
EventRecord objects. Google News is a supplementary headline source
that complements GDELT: no rate-limit pain, broader coverage, but
no per-article tone scores.

Quirks ported verbatim from v1's ``src/ingestion/googlenews_client.py``:

* **RSS/XML format.** Google News returns RSS XML, not JSON. Parsed
  via ``xml.etree.ElementTree``.
* **Country name queries.** Searches by ``"{country_name}" economy OR
  politics`` for macro-focused results.
* **Source name extraction.** Either from ``<source>`` RSS tag, or
  by splitting the title on `` - `` (Google News appends
  `` - Source Name`` to titles).
* **pubDate format.** RFC 2822 style (``"Sat, 15 Jan 2024 12:00:00 GMT"``),
  parsed via ``pd.to_datetime(utc=True)``.
* **Non-XML responses.** Checks for ``<?xml`` prefix before parsing
  to handle error pages gracefully.

Only produces ``"headline"`` event_type. No tone/volume timelines
(use GDELT for those).
"""

from __future__ import annotations

import datetime
import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from xml.etree import ElementTree

import httpx
import pandas as pd
import structlog

from ridge.adapters.base import HealthReport
from ridge.adapters.base_client import BaseClient
from ridge.domain.event import EventRecord
from ridge.domain.source import FetchRequest, SourceIndicatorSpec

logger = structlog.get_logger(__name__)


GNEWS_RSS_BASE = "https://news.google.com/rss/search"


class GoogleNewsAdapter(BaseClient):
    """Fetches Google News headlines as EventRecords.

    Satisfies the ``EventSourceAdapter`` protocol. Inherits HTTP
    session, rate limiting, and retries from ``BaseClient``.

    Google News RSS is free, no API key, generous rate limits (~30
    req/min). Much faster than GDELT for broad headline coverage.
    """

    source_id: str = "googlenews"

    def __init__(
        self,
        indicators: Sequence[SourceIndicatorSpec],
        country_names: Mapping[str, str],
        max_articles: int = 15,
        requests_per_minute: int = 30,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id=self.source_id,
            base_url=GNEWS_RSS_BASE,
            requests_per_minute=requests_per_minute,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )
        self._indicators: tuple[SourceIndicatorSpec, ...] = tuple(
            self._validate_indicators(indicators)
        )
        self._by_country: Mapping[str, tuple[SourceIndicatorSpec, ...]] = self._group_by_country(
            self._indicators
        )
        self._country_names = dict(country_names)
        self._max_articles = max_articles

    @classmethod
    def _validate_indicators(
        cls,
        indicators: Iterable[SourceIndicatorSpec],
    ) -> list[SourceIndicatorSpec]:
        kept: list[SourceIndicatorSpec] = []
        for spec in indicators:
            if spec.source_id != cls.source_id:
                logger.warning(
                    "googlenews.indicator.wrong_source",
                    source_id=spec.source_id,
                )
                continue
            kept.append(spec)
        return kept

    @staticmethod
    def _group_by_country(
        indicators: Sequence[SourceIndicatorSpec],
    ) -> dict[str, tuple[SourceIndicatorSpec, ...]]:
        by_country: dict[str, list[SourceIndicatorSpec]] = defaultdict(list)
        for spec in indicators:
            for iso3 in spec.countries_iso3:
                by_country[iso3].append(spec)
        return {iso3: tuple(specs) for iso3, specs in by_country.items()}

    async def fetch_events(self, request: FetchRequest) -> list[EventRecord]:
        """Fetch headline EventRecords for the requested countries."""
        ingested_at = datetime.datetime.now(datetime.UTC)
        countries = request.countries_iso3 or frozenset(self._by_country.keys())

        results: list[EventRecord] = []
        for iso3 in countries:
            if iso3 not in self._by_country:
                continue

            name = self._country_names.get(iso3)
            if not name:
                logger.debug("googlenews.fetch.no_country_name", iso3=iso3)
                continue

            headlines = await self._fetch_headlines(iso3, name, ingested_at)
            results.extend(headlines)

        return results

    async def health(self) -> HealthReport:
        return HealthReport(source_id=self.source_id, healthy=True)

    async def _fetch_headlines(
        self,
        iso3: str,
        country_name: str,
        ingested_at: datetime.datetime,
    ) -> list[EventRecord]:
        """Fetch Google News RSS for one country and parse to EventRecords."""
        query = f'"{country_name}" economy OR politics'
        params = {"q": query, "hl": "en", "gl": "US", "ceid": "US:en"}

        try:
            text = await self.get_text(GNEWS_RSS_BASE, params=params)
        except Exception as exc:
            logger.debug("googlenews.fetch.failed", iso3=iso3, error=str(exc))
            return []

        if not text or not text.strip().startswith("<?xml"):
            return []

        articles = self._parse_rss(text)
        articles = articles[: self._max_articles]

        events: list[EventRecord] = []
        for article in articles:
            url_str = article.get("url", "")
            if not url_str:
                continue

            obs_date = article.get("date")
            if obs_date is None:
                continue
            if hasattr(obs_date, "date"):
                obs_date = obs_date.date()

            url_hash = hashlib.md5(url_str.encode()).hexdigest()[:16]

            events.append(
                EventRecord(
                    country_iso3=iso3,
                    source_id=self.source_id,
                    event_type="headline",
                    date=obs_date,
                    dedup_key=f"googlenews:headline:{url_hash}",
                    title=article.get("title"),
                    url=url_str,
                    metadata={
                        "source_name": article.get("source", ""),
                    },
                    ingested_at=ingested_at,
                )
            )

        return events

    @staticmethod
    def _parse_rss(xml_text: str) -> list[dict[str, Any]]:
        """Parse Google News RSS XML into a list of article dicts.

        Returns list of {"title": str, "url": str, "source": str,
        "date": datetime | None}.

        Ported from v1: source name is extracted from <source> tag or
        by splitting title on " - " suffix.
        """
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return []

        channel = root.find("channel")
        if channel is None:
            return []

        articles: list[dict[str, Any]] = []
        for item in channel.findall("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            source_el = item.find("source")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = link_el.text.strip() if link_el is not None and link_el.text else ""

            if not title or not link:
                continue

            if source_el is not None and source_el.text:
                source_name = source_el.text.strip()
            elif " - " in title:
                source_name = title.rsplit(" - ", 1)[-1]
                title = title.rsplit(" - ", 1)[0]
            else:
                source_name = ""

            pub_str = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
            try:
                date_val = pd.to_datetime(pub_str, utc=True)
            except Exception:
                date_val = None

            articles.append(
                {
                    "title": title,
                    "url": link,
                    "source": source_name,
                    "date": date_val,
                }
            )

        return articles
