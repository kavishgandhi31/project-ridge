"""Tests for the BaseClient HTTP layer.

Uses ``httpx.MockTransport`` to route requests through a user-supplied
handler function instead of real network calls. Tests are hermetic and
fast — no sleeps beyond what the rate limiter requires, no Postgres,
no docker.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from ridge.adapters.base_client import BaseClient, CircuitOpenError


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    requests_per_minute: int = 600000,  # effectively disable rate limit in tests
    max_retries: int = 3,
    timeout_seconds: float = 5.0,
    circuit_breaker_threshold: int = 5,
) -> BaseClient:
    """Build a BaseClient whose transport is a mock routing via handler."""
    return BaseClient(
        source_id="test",
        base_url="http://mock",
        requests_per_minute=requests_per_minute,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        circuit_breaker_threshold=circuit_breaker_threshold,
        transport=httpx.MockTransport(handler),
    )


class TestGetJsonHappyPath:
    async def test_200_returns_parsed_json(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"hello": "world"})

        client = _client(handler)
        try:
            result = await client.get_json("http://mock/endpoint")
            assert result == {"hello": "world"}
        finally:
            await client.close()

    async def test_params_are_forwarded(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json={})

        client = _client(handler)
        try:
            await client.get_json("http://mock/endpoint", params={"a": "1", "b": "2"})
            assert captured == {"a": "1", "b": "2"}
        finally:
            await client.close()


class TestGetJsonFailFast4xx:
    async def test_404_raises_immediately_without_retry(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(404, json={"error": "not found"})

        client = _client(handler)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_json("http://mock/endpoint")
        finally:
            await client.close()
        # 4xx fails fast — no retries.
        assert call_count == 1

    async def test_401_raises_immediately(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        client = _client(handler)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_json("http://mock/endpoint")
        finally:
            await client.close()


class TestGetJsonRetries5xx:
    async def test_500_then_200_succeeds(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return httpx.Response(500, json={"error": "server"})
            return httpx.Response(200, json={"recovered": True})

        client = _client(handler, max_retries=3, requests_per_minute=600000)
        try:
            result = await client.get_json("http://mock/endpoint")
            assert result == {"recovered": True}
        finally:
            await client.close()
        assert call_count == 2

    async def test_persistent_500_raises_after_max_retries(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(500, json={"error": "always broken"})

        client = _client(handler, max_retries=3, requests_per_minute=600000)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_json("http://mock/endpoint")
        finally:
            await client.close()
        # All 3 retries should have been attempted.
        assert call_count == 3


class TestGetJson429RateLimited:
    async def test_429_then_200_with_retry_after(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return httpx.Response(
                    429,
                    json={"error": "rate limited"},
                    headers={"Retry-After": "0"},  # 0 = no real delay
                )
            return httpx.Response(200, json={"ok": True})

        client = _client(handler, max_retries=3, requests_per_minute=600000)
        try:
            result = await client.get_json("http://mock/endpoint")
            assert result == {"ok": True}
        finally:
            await client.close()
        assert call_count == 2


class TestCircuitBreaker:
    async def test_persistent_5xx_trips_breaker(self) -> None:
        """Repeated 503s exhaust retries and trip the breaker; next request fast-fails."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(503, json={"error": "always broken"})

        client = _client(
            handler,
            max_retries=3,
            circuit_breaker_threshold=3,
        )
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_json("http://mock/endpoint")
            # First request exhausted 3 retries, so the counter hit the threshold
            # and the breaker is open. The second call must not reach the handler.
            with pytest.raises(CircuitOpenError):
                await client.get_json("http://mock/endpoint")
        finally:
            await client.close()
        assert call_count == 3

    async def test_successful_response_resets_failure_counter(self) -> None:
        """A 200 between failures resets the counter so the breaker stays closed."""
        # If failures accumulated across the 200s, threshold=3 would trip after
        # request 2 (1 + 1 = 2 fails, plus a third 503 anywhere = 3). With the
        # reset-on-200 semantic the counter goes 1 -> 0 -> 1 -> 0 and never trips.
        responses = [503, 200, 503, 200]
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            status = responses[call_count]
            call_count += 1
            if status == 200:
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(503, json={"error": "burp"})

        client = _client(
            handler,
            max_retries=2,
            circuit_breaker_threshold=3,
        )
        try:
            assert await client.get_json("http://mock/endpoint") == {"ok": True}
            assert await client.get_json("http://mock/endpoint") == {"ok": True}
        finally:
            await client.close()
        assert call_count == 4


class TestContextManager:
    async def test_async_with_closes_session(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = BaseClient(
            source_id="test",
            base_url="http://mock",
            requests_per_minute=600000,
            transport=httpx.MockTransport(handler),
        )
        async with client:
            await client.get_json("http://mock/endpoint")
        # After exiting the context, the internal client should be None.
        assert client._client is None

    async def test_close_is_idempotent(self) -> None:
        client = BaseClient(source_id="test", base_url="http://mock")
        await client.close()
        await client.close()  # should not raise
