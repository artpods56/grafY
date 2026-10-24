"""Egress fixtures: a destination an operator trusts, and one they do not.

`grafy_core.egress` decides from the address a name resolves to, so a test that
dials a real listener uses one on loopback together with the grant that names it.
Every grant here is built for one test and handed to the caller under test; nothing
widens a default, and `no_grants()` is what a deployment with an unset
`GRAFY_EGRESS_TRUSTED_DESTINATIONS` actually runs with.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import socket
from typing import AsyncIterator

import httpx2
import pytest

from grafy_core.egress import (
    TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE,
    EgressPolicy,
    EgressRejectedError,
)

# A public address, so a name resolved in a test passes the guard on its own
# merits and never depends on this machine's resolver.
PUBLIC_ADDRESS = "93.184.216.34"


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    """One request a `LoopbackHttpListener` was dialed on."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass(slots=True)
class LoopbackHttpListener:
    """A real HTTP listener on loopback, for a test that must be dialed."""

    status: int = 200
    body: bytes = b"{}"
    content_type: str = "application/json"
    extra_headers: tuple[tuple[str, str], ...] = ()
    requests: list[RecordedRequest] = field(default_factory=list)
    _server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        server = self._server
        if server is None or not server.sockets:
            raise AssertionError("listener is not started")
        address = server.sockets[0].getsockname()
        return int(address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._serve,
            "127.0.0.1",
            0,
        )

    async def aclose(self) -> None:
        server = self._server
        if server is not None:
            server.close()
            await server.wait_closed()
            self._server = None

    async def _serve(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        request_line = (await reader.readline()).decode("latin-1").split()
        method = request_line[0] if request_line else ""
        target = request_line[1] if len(request_line) > 1 else ""
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if not line or line in {b"\r\n", b"\n"}:
                break
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        declared_length = headers.get("content-length")
        body = (
            await reader.readexactly(int(declared_length))
            if declared_length is not None and declared_length.isdigit()
            else b""
        )
        self.requests.append(
            RecordedRequest(
                method=method,
                path=target,
                headers=headers,
                body=body,
            )
        )
        response = [
            f"HTTP/1.1 {self.status} {'OK' if self.status < 400 else 'Error'}",
            f"content-type: {self.content_type}",
            f"content-length: {len(self.body)}",
            *(f"{name}: {value}" for name, value in self.extra_headers),
            "",
            "",
        ]
        writer.write("\r\n".join(response).encode("latin-1") + self.body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()


@asynccontextmanager
async def loopback_http_listener(
    *,
    status: int = 200,
    body: bytes = b"{}",
    content_type: str = "application/json",
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> AsyncIterator[LoopbackHttpListener]:
    listener = LoopbackHttpListener(
        status=status,
        body=body,
        content_type=content_type,
        extra_headers=extra_headers,
    )
    await listener.start()
    try:
        yield listener
    finally:
        await listener.aclose()


def trusted_loopback_destination() -> EgressPolicy:
    """The grant an operator writes for a service they keep on loopback."""

    return EgressPolicy.from_destinations(["127.0.0.1"])


def trusted_loopback_network() -> EgressPolicy:
    """The grant for a destination whose *name* resolves to loopback.

    `trusted_loopback_destination()` grants one address by name, which is what a
    literal `http://127.0.0.1:port` endpoint is dialed with. Spatial node
    configuration rejects a loopback literal in the first place, so a service
    reached through a name needs the network form of the same operator grant.
    """

    return EgressPolicy.from_destinations(["127.0.0.0/8"])


def no_grants() -> EgressPolicy:
    """What a deployment with no `GRAFY_EGRESS_TRUSTED_DESTINATIONS` dials with."""

    return EgressPolicy()


def answer_httpx2_dials(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[httpx2.Request], httpx2.Response],
) -> None:
    """Answer an `httpx2` dial in-process with the egress guard left in the path.

    Used by the provider SDKs that build their own requests on `httpx2`: their
    client keeps its real transport, so the pin the family installs still decides,
    and only the socket underneath it is answered here. The configured name
    resolves to one public address, so it passes on its own merits and the test
    never reaches the network.
    """

    async def handle_async_request(
        _transport: httpx2.AsyncHTTPTransport,
        request: httpx2.Request,
    ) -> httpx2.Response:
        return respond(request)

    monkeypatch.setattr(
        httpx2.AsyncHTTPTransport,
        "handle_async_request",
        handle_async_request,
    )
    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_host)


def resolve_public_host(
    host: str,
    port: int,
    *_args: object,
    **_kwargs: object,
) -> list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]]:
    """A `socket.getaddrinfo` stand-in answering one name with one public address."""

    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (PUBLIC_ADDRESS, port),
        )
    ]


def resolve_loopback_host(
    host: str,
    port: int,
    *_args: object,
    **_kwargs: object,
) -> list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]]:
    """A `socket.getaddrinfo` stand-in answering one name with loopback."""

    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("127.0.0.1", port),
        )
    ]


def first_egress_rejection(exc: BaseException) -> EgressRejectedError | None:
    """The egress rejection inside ``exc``'s cause chain, if it was refused.

    Provider SDKs wrap a transport failure in their own error type before the
    plugin wraps it again, so a test asserts on the rejection itself rather than
    on the class the caller happened to see.
    """

    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, EgressRejectedError):
            return current
        current = current.__cause__
    return None


__all__ = [
    "PUBLIC_ADDRESS",
    "LoopbackHttpListener",
    "answer_httpx2_dials",
    "RecordedRequest",
    "TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE",
    "first_egress_rejection",
    "loopback_http_listener",
    "no_grants",
    "resolve_loopback_host",
    "resolve_public_host",
    "trusted_loopback_destination",
    "trusted_loopback_network",
]
