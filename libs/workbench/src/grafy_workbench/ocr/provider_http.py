"""One pooled, egress-pinned HTTP client per provider, shared by the OCR families.

A TIFF page scan asks CRAFT for hundreds of 1,000 by 1,000 pixel windows and asks
the Cyrillic recognizer to transcribe the crops they produced. A client per window
paid a fresh TLS handshake for each one and left the scan's own fan-out as the only
throttle, so windows queued at the provider instead of locally: what began as a
slow response became a timeout, and one timed-out window fails the whole scan.

The pool owns both jobs. Its connection limit is the concurrency the provider is
allowed to see, so the scan may fan out as wide as it likes and the wait happens
here, where it is one number with one meaning; and a window reuses a connection
another window opened.

Clients are keyed by event loop because an httpx connection belongs to the loop that
opened it. The API runs one loop for its life and closes these in its cleanup; a
test loop that dies takes its client with it.
"""

from asyncio import AbstractEventLoop, get_running_loop, sleep
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass
from random import uniform
from typing import Any, Final
from weakref import WeakKeyDictionary

import httpx
from pydantic import SecretStr

from grafy_core.egress import EgressRejectedError, PinnedPublicAddressTransport
from grafy_core.node_context import UserFacingNodeError

# What one provider dials at a time, across every node in every run on this loop.
# Measured on the scoped LiteLLM route with the same 1,000 by 1,000 window: one
# request answers in about 5 seconds, four in about 8, sixteen in 24 to 38 seconds
# with one HTTP 500 among them. The ceiling is the provider's, not the scan's.
MAX_CONNECTIONS_PER_PROVIDER: Final = 4
_CONNECT_TIMEOUT_SECONDS: Final = 5.0
# A scan's workers time out together, at the same ceiling. Without the spread they
# would return together and queue up the same way all over again.
_MAX_BACKOFF_SECONDS: Final = 2.0
_JITTER_SECONDS: Final = 0.25
_RETRYABLE_STATUS: Final = frozenset({429, 500, 502, 503, 504})

_pooled: WeakKeyDictionary[AbstractEventLoop, dict[str, httpx.AsyncClient]] = (
    WeakKeyDictionary()
)
_served: WeakKeyDictionary[AbstractEventLoop, httpx.AsyncClient] = WeakKeyDictionary()


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """One provider call, the number of tries it is allowed, and its own limits."""

    service: str
    url: str
    payload: Mapping[str, Any]
    api_key: SecretStr
    attempts: int
    timeout_seconds: float
    max_response_bytes: int
    slot: Callable[[], AbstractAsyncContextManager[Any]] | None = None


@contextmanager
def serve_client(client: httpx.AsyncClient) -> Iterator[None]:
    """Answer every provider request on this loop with ``client``.

    The suite's stand-in provider is a ``MockTransport``; the pool would pin a real
    address and dial it.
    """

    _served[get_running_loop()] = client
    try:
        yield
    finally:
        _served.pop(get_running_loop(), None)


def provider_client(url: str) -> httpx.AsyncClient:
    """The client this loop uses for ``url``'s provider, created on first use."""

    loop = get_running_loop()
    served = _served.get(loop)
    if served is not None:
        return served
    by_provider = _pooled.setdefault(loop, {})
    key = _provider_key(url)
    client = by_provider.get(key)
    if client is None:
        client = httpx.AsyncClient(
            transport=PinnedPublicAddressTransport(),
            limits=httpx.Limits(
                max_connections=MAX_CONNECTIONS_PER_PROVIDER,
                max_keepalive_connections=MAX_CONNECTIONS_PER_PROVIDER,
            ),
            timeout=httpx.Timeout(_CONNECT_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
        )
        by_provider[key] = client
    return client


async def aclose_provider_clients() -> None:
    """Close this loop's pooled clients. The API does this once, at shutdown."""

    for client in _pooled.pop(get_running_loop(), {}).values():
        await client.aclose()


async def post_json(request: ProviderRequest) -> bytes:
    """POST a JSON body and return the response bytes.

    Both OCR providers failed the same way for the same reason, so both retry here:
    a provider that answers 500 is worth another try and so is one that answers
    late, and the difference between them is only whether a status code arrived.
    """

    client = provider_client(request.url)
    headers = {"Authorization": f"Bearer {request.api_key.get_secret_value()}"}
    timeout = httpx.Timeout(request.timeout_seconds, connect=_CONNECT_TIMEOUT_SECONDS)
    for attempt in range(request.attempts):
        if attempt:
            await sleep(_backoff_seconds(attempt))
        try:
            async with (
                _gate(request.slot),
                client.stream(
                    "POST",
                    request.url,
                    headers=headers,
                    json=dict(request.payload),
                    timeout=timeout,
                ) as response,
            ):
                if response.status_code == 200:
                    return await _read_limited(request, response)
                if response.status_code not in _RETRYABLE_STATUS or (
                    attempt + 1 >= request.attempts
                ):
                    raise UserFacingNodeError(
                        f"{request.service} returned HTTP {response.status_code}"
                    )
        except EgressRejectedError as exc:
            raise UserFacingNodeError(
                f"{request.service} may not be dialed by this deployment"
            ) from exc
        except httpx.RequestError as exc:
            if attempt + 1 >= request.attempts:
                raise UserFacingNodeError(
                    f"Could not reach {request.service} through LiteLLM"
                ) from exc
    raise AssertionError(f"{request.service} request attempts exhausted")


async def _read_limited(request: ProviderRequest, response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > request.max_response_bytes:
            raise UserFacingNodeError(
                f"{request.service} response exceeds the size limit"
            )
    return bytes(body)


@asynccontextmanager
async def _gate(
    slot: Callable[[], AbstractAsyncContextManager[Any]] | None,
) -> AsyncIterator[None]:
    if slot is None:
        yield
        return
    async with slot():
        yield


def _backoff_seconds(attempt: int) -> float:
    """How long to wait before retry number ``attempt``, counting from one."""

    return min(_MAX_BACKOFF_SECONDS, 0.25 * (2 ** (attempt - 1))) + uniform(
        0.0, _JITTER_SECONDS
    )


def _provider_key(url: str) -> str:
    """The origin ``url`` belongs to: connections are never shared across one."""

    parsed = httpx.URL(url)
    port = parsed.port
    if port is None:
        return f"{parsed.scheme}://{parsed.host}"
    return f"{parsed.scheme}://{parsed.host}:{port}"
