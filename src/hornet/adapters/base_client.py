"""Shared HTTP machinery for SourceAdapter implementations.

Ports v1's ``src/ingestion/base_client.py`` to httpx. Provides a
reusable base class that handles:

- httpx.AsyncClient session with lazy init and context manager cleanup
- Rate limiting via minimum spacing between requests
- Exponential-backoff retry (1s → 2s → 4s, max 3 attempts by default)
- 429 Retry-After header respect
- Fail-fast on 4xx (except 429); retry on 5xx and network errors

Intentionally **does not** include v1's circuit breaker, on-disk state
persistence, or source-health recording. Those belong in Phase 4 with
the rest of the monitoring layer. Keeping this class minimal makes
the adapters (FRED, WorldBank, etc.) trivially testable with a mocked
httpx transport.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any, Self

import httpx


class BaseClient:
    """Async HTTP base class for data source adapters.

    Subclasses typically override nothing from this class — they use
    ``self.get_json(url, params)`` to fetch data and then parse the
    response in their own methods. Every subclass inherits rate
    limiting, retries, and session management for free.

    Usage::

        class FredAdapter(BaseClient):
            source_id = "fred"

            def __init__(self) -> None:
                super().__init__(
                    source_id="fred",
                    base_url="https://api.stlouisfed.org/fred",
                    requests_per_minute=60,
                    timeout_seconds=30,
                )

            async def fetch_series(self, series_id: str) -> dict[str, Any]:
                return await self.get_json(
                    f"{self.base_url}/series/observations",
                    params={"series_id": series_id, "api_key": ..., "file_type": "json"},
                )

    The class supports the async context manager protocol so you can
    use ``async with BaseClient(...) as client:`` to guarantee session
    cleanup. For long-lived clients, call ``await client.close()``
    manually at shutdown.
    """

    def __init__(
        self,
        source_id: str,
        base_url: str,
        requests_per_minute: int = 60,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize a BaseClient.

        Args:
            source_id: Short identifier matching the SourceAdapter
                protocol (e.g. "fred", "worldbank"). Used in logs and
                for monitoring layer tagging.
            base_url: Root URL for the source API.
            requests_per_minute: Rate limit cap. Default 60 — matches
                v1's conservative default for FRED. WorldBank and
                OECD use lower values; override per-adapter.
            timeout_seconds: httpx request timeout. Default 30 seconds,
                which is fine for most sources; WorldBank overrides
                to 60 because its API is slow.
            max_retries: Maximum retry attempts on 5xx / timeouts /
                network errors. Default 3.
            transport: Optional httpx transport override. Tests inject
                ``httpx.MockTransport`` here to avoid real network
                calls. Production code should leave this as ``None``.
        """
        self.source_id = source_id
        self.base_url = base_url
        self._min_interval_seconds = 60.0 / requests_per_minute
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._last_request_monotonic: float = 0.0

    async def __aenter__(self) -> Self:
        self._ensure_client()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying httpx client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        """Lazily construct the httpx client on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            )
        return self._client

    async def _rate_limit(self) -> None:
        """Block until the minimum spacing since the last request has elapsed.

        Uses ``time.monotonic()`` rather than wall-clock time so the
        limiter is immune to clock skew or NTP adjustments. ``monotonic``
        is guaranteed to never go backwards.
        """
        now = time.monotonic()
        elapsed = now - self._last_request_monotonic
        if elapsed < self._min_interval_seconds:
            await asyncio.sleep(self._min_interval_seconds - elapsed)
        self._last_request_monotonic = time.monotonic()

    async def _request(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Perform a GET request with rate limiting and retries.

        Returns the raw ``httpx.Response`` on success (status 200).
        Raises the original httpx exception on 4xx (non-429) responses
        or after ``max_retries`` exhausted retries on 5xx / network errors.

        Retry policy:

        * **200**: return response immediately.
        * **429**: respect ``Retry-After`` header if present, else
          exponential backoff. Retry up to ``max_retries``.
        * **5xx**: exponential backoff, retry up to ``max_retries``.
          Final attempt's exception is raised.
        * **4xx (non-429)**: fail fast, no retries -- these are usually
          permanent (bad auth, bad URL, invalid query).
        * **Network error / timeout**: exponential backoff, retry.

        Exponential backoff sequence: 1s, 2s, 4s, 8s, ...
        (``2 ** attempt`` seconds where attempt starts at 0).
        """
        client = self._ensure_client()

        last_exception: Exception | None = None

        for attempt in range(self._max_retries):
            await self._rate_limit()

            try:
                response = await client.get(url, params=params)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                if attempt == self._max_retries - 1:
                    raise
                await asyncio.sleep(2**attempt)
                continue

            if response.status_code == 200:
                return response

            if response.status_code == 429:
                if attempt == self._max_retries - 1:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2**attempt
                await asyncio.sleep(delay)
                continue

            if 500 <= response.status_code < 600:
                if attempt == self._max_retries - 1:
                    response.raise_for_status()
                await asyncio.sleep(2**attempt)
                continue

            response.raise_for_status()

        if last_exception is not None:
            raise last_exception
        raise RuntimeError(
            f"BaseClient({self.source_id}): exhausted {self._max_retries} "
            f"retries for {url} without a definitive response"
        )

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET request returning parsed JSON. See ``_request`` for retry policy."""
        response = await self._request(url, params=params)
        return response.json()

    async def get_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """GET request returning response body as text. See ``_request`` for retry policy.

        Used by adapters that receive CSV or XML instead of JSON
        (e.g., BIS returns SDMX-CSV).
        """
        response = await self._request(url, params=params)
        return response.text
