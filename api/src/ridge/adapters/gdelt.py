"""GDELT data source adapter -- ports v1's GDELTClient to Ridge.

Fetches news sentiment (tone), article volume, and headlines from the
GDELT DOC 2.0 API and maps them to EventRecord objects. Parsing quirks
ported verbatim from v1's ``src/ingestion/gdelt_client.py``.

Quirks:

* **Country name queries.** GDELT searches by text, not ISO codes.
  Queries are built as ``"Nigeria" OR "NG"`` using the country name
  and ISO2 from the country registry.
* **Rate limit: 10 req/min.** GDELT enforces ~1 request per 5 seconds.
* **Non-JSON rate-limit responses.** GDELT returns plain text (not
  JSON) when rate-limiting, even with HTTP 200. Responses are fetched
  as text and checked for JSON before parsing.
* **Timeline date format.** Points arrive as ``"January 15, 2024
  00:00:00"`` (English month name), parsed with ``format="mixed"``.
* **Tone smoothing.** 7-day rolling average on tone values to reduce
  daily noise, matching v1's approach.
* **Artlist headline parsing.** ``seendate`` uses ``"%Y%m%dT%H%M%SZ"``
  format. Tone field is a CSV string; first element is the main score.

Three event_type values produced:
- ``"tone"`` -- daily average sentiment (value = tone score)
- ``"volume"`` -- daily article count (value = count)
- ``"headline"`` -- per-article metadata (title, url, metadata bag)
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import httpx
import pandas as pd
import structlog

from ridge.adapters.base import HealthReport
from ridge.adapters.base_client import BaseClient
from ridge.domain.event import EventRecord
from ridge.domain.source import FetchRequest, SourceIndicatorSpec

logger = structlog.get_logger(__name__)


GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2"
DEFAULT_TIMESPAN = "90d"
TONE_SMOOTHING_WINDOW = 7


class GDELTAdapter(BaseClient):
    """Fetches GDELT tone, volume, and headlines as EventRecords.

    Satisfies the ``EventSourceAdapter`` protocol. Inherits HTTP
    session, rate limiting, and retries from ``BaseClient``.

    Constructor takes:
    - ``indicators`` -- registry entries where ``indicator_code`` is
      the event_type (tone, volume, headline).
    - ``country_names`` -- ISO3 -> English name map for query building.
    - ``country_iso2s`` -- ISO3 -> ISO2 map for query building.
    """

    source_id: str = "gdelt"

    def __init__(
        self,
        indicators: Sequence[SourceIndicatorSpec],
        country_names: Mapping[str, str],
        country_iso2s: Mapping[str, str],
        requests_per_minute: int = 10,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            source_id=self.source_id,
            base_url=GDELT_BASE_URL,
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
        self._country_iso2s = dict(country_iso2s)

    @classmethod
    def _validate_indicators(
        cls,
        indicators: Iterable[SourceIndicatorSpec],
    ) -> list[SourceIndicatorSpec]:
        kept: list[SourceIndicatorSpec] = []
        for spec in indicators:
            if spec.source_id != cls.source_id:
                logger.warning(
                    "gdelt.indicator.wrong_source",
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
        """Fetch tone, volume, and/or headline EventRecords."""
        ingested_at = datetime.datetime.now(datetime.UTC)
        countries = request.countries_iso3 or frozenset(self._by_country.keys())

        results: list[EventRecord] = []
        for iso3 in countries:
            specs = self._by_country.get(iso3)
            if specs is None:
                continue

            for spec in specs:
                if request.indicator_codes and spec.indicator_code not in request.indicator_codes:
                    continue

                event_type = spec.indicator_code
                if event_type in ("tone", "volume"):
                    events = await self._fetch_timeline(iso3, event_type, ingested_at)
                elif event_type == "headline":
                    events = await self._fetch_headlines(iso3, ingested_at)
                else:
                    continue

                results.extend(events)

        return results

    async def health(self) -> HealthReport:
        return HealthReport(source_id=self.source_id, healthy=True)

    def _build_query(self, iso3: str) -> str:
        """Build a GDELT search query using country name.

        Uses the full country name only. ISO2 codes are NOT included
        because GDELT rejects phrases shorter than 3 characters
        ("The specified phrase is too short"), and 2-letter codes
        produce false positives (e.g. "TR" matches "trade", "transport").
        """
        name = self._country_names.get(iso3, iso3)
        query = f'"{name}"'
        return query

    async def _get_gdelt_json(self, url: str, params: dict[str, str]) -> Any:
        """Fetch GDELT as text, then parse JSON manually.

        GDELT returns plain text when rate-limiting even with HTTP 200.
        Checking for "{" before json.loads avoids parse errors on those
        responses.
        """
        text = await self.get_text(url, params=params)
        if not text or not text.strip().startswith("{"):
            raise ValueError(f"Non-JSON response: {text[:120]}")
        return json.loads(text)

    # ------------------------------------------------------------------
    # Tone / Volume timelines
    # ------------------------------------------------------------------

    async def _fetch_timeline(
        self,
        iso3: str,
        event_type: str,
        ingested_at: datetime.datetime,
    ) -> list[EventRecord]:
        """Fetch a tone or volume timeline and convert to EventRecords."""
        mode = "timelinetone" if event_type == "tone" else "timelinevolinfo"
        query = self._build_query(iso3)
        url = f"{GDELT_BASE_URL}/doc/doc"
        params = {
            "query": query,
            "mode": mode,
            "timespan": DEFAULT_TIMESPAN,
            "format": "json",
        }

        try:
            data = await self._get_gdelt_json(url, params)
        except Exception as exc:
            logger.debug("gdelt.timeline.failed", iso3=iso3, event_type=event_type, error=str(exc))
            return []

        df = self._parse_timeline(data)
        if df.empty:
            return []

        if event_type == "tone" and len(df) >= TONE_SMOOTHING_WINDOW:
            df["value"] = df["value"].rolling(window=TONE_SMOOTHING_WINDOW, min_periods=1).mean()

        events: list[EventRecord] = []
        for _, row in df.iterrows():
            obs_date = row["date"]
            if isinstance(obs_date, pd.Timestamp):
                obs_date = obs_date.date()
            events.append(
                EventRecord(
                    country_iso3=iso3,
                    source_id=self.source_id,
                    event_type=event_type,
                    date=obs_date,
                    dedup_key=f"gdelt:{event_type}:{iso3}:{obs_date}",
                    value=float(row["value"]),
                    ingested_at=ingested_at,
                )
            )
        return events

    @staticmethod
    def _parse_timeline(data: Any) -> pd.DataFrame:
        """Parse GDELT timeline JSON into DataFrame(date, value).

        GDELT returns: {"timeline": [{"series": [...], "data": "label"}]}
        Each series point: {"date": "January 15, 2024 00:00:00", "value": 3.5}
        """
        if not data:
            return pd.DataFrame(columns=["date", "value"])

        timeline = data.get("timeline", [])
        if not timeline:
            return pd.DataFrame(columns=["date", "value"])

        first = timeline[0] if isinstance(timeline, list) else timeline
        series = first.get("data", first.get("series", []))

        if not series:
            return pd.DataFrame(columns=["date", "value"])

        rows: list[dict[str, Any]] = []
        for point in series:
            date_str = point.get("date", "")
            value = point.get("value")
            if not date_str or value is None:
                continue
            try:
                rows.append({"date": date_str, "value": float(value)})
            except (ValueError, TypeError):
                continue

        if not rows:
            return pd.DataFrame(columns=["date", "value"])

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=False)
        df = df.dropna(subset=["date"])
        return df.sort_values("date").reset_index(drop=True)

    # ------------------------------------------------------------------
    # Headlines (artlist mode)
    # ------------------------------------------------------------------

    async def _fetch_headlines(
        self,
        iso3: str,
        ingested_at: datetime.datetime,
        max_articles: int = 25,
    ) -> list[EventRecord]:
        """Fetch article headlines via GDELT artlist mode."""
        query = self._build_query(iso3)
        url = f"{GDELT_BASE_URL}/doc/doc"
        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": str(max_articles),
            "format": "json",
            "timespan": "7d",
            "sort": "hybridrel",
        }

        try:
            data = await self._get_gdelt_json(url, params)
        except Exception as exc:
            logger.debug("gdelt.headlines.failed", iso3=iso3, error=str(exc))
            return []

        return self._parse_artlist(data, iso3, ingested_at)

    @staticmethod
    def _parse_artlist(
        data: Any,
        iso3: str,
        ingested_at: datetime.datetime,
    ) -> list[EventRecord]:
        """Parse GDELT artlist JSON into EventRecord list.

        Ported from v1: seendate format "%Y%m%dT%H%M%SZ", tone is a
        CSV string where first element is the main tone score.
        """
        if not data:
            return []

        articles = data.get("articles", [])
        if not articles:
            return []

        events: list[EventRecord] = []
        for article in articles:
            title = article.get("title", "").strip()
            url_str = article.get("url", "").strip()
            if not title or not url_str:
                continue

            seen = article.get("seendate", "")
            try:
                date_val = pd.to_datetime(seen, format="%Y%m%dT%H%M%SZ", utc=True)
                obs_date = date_val.date()
            except Exception:
                continue

            tone_raw = article.get("tone", 0)
            try:
                tone_val = float(str(tone_raw).split(",")[0])
            except (ValueError, TypeError):
                tone_val = 0.0

            url_hash = hashlib.md5(url_str.encode()).hexdigest()[:16]

            events.append(
                EventRecord(
                    country_iso3=iso3,
                    source_id="gdelt",
                    event_type="headline",
                    date=obs_date,
                    dedup_key=f"gdelt:headline:{url_hash}",
                    value=tone_val,
                    title=title,
                    url=url_str,
                    metadata={
                        "source_name": article.get("domain", article.get("source", "")),
                        "image_url": article.get("socialimage", ""),
                    },
                    ingested_at=ingested_at,
                )
            )

        return events
