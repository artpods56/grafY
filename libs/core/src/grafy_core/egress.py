"""Egress authority for destinations that node configuration names.

A node's configuration is author input, and it names a destination: a PostgreSQL
host, an OpenAI-compatible base URL, a WFS endpoint. The Plugin sandbox decided
what those destinations could reach with a Docker network policy and an egress
broker; once the families run in-process (ADR 0017) the API dials them itself, so
the decision lives here. Its job is narrow and absolute: nothing an author can
name from a graph may reach an address the deployment keeps to itself, which is
what keeps the internal PostgreSQL, MinIO and Keycloak out of reach of node
configuration.

Two things belong to this module and nothing else does. The policy primitives —
the operator's grants and the resolve-and-decide step — are framework-free so
every caller shares them. Client wiring belongs with the client: an OpenAI or
TypeSafe SDK builds its own requests and can only be pinned from below, while WFS
and WMS build their own URLs and pin them directly.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, cast

import httpx
from pydantic import AnyHttpUrl

TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE: Final = "GRAFY_EGRESS_TRUSTED_DESTINATIONS"
DNS_TIMEOUT_SECONDS: Final = 3.0

_ALLOWED_SCHEMES: Final = frozenset({"http", "https"})


class EgressRejectedError(RuntimeError):
    """A destination named in node configuration may not be dialed."""


@dataclass(frozen=True, slots=True)
class _Grant:
    host: str | None
    port: int | None
    network: ipaddress.IPv4Network | ipaddress.IPv6Network | None


# One ``getaddrinfo`` answer, in the shape typeshed gives it: family, socket type,
# protocol, canonical name, and a socket address that carries the scope id on IPv6.
_AddressRecord = tuple[
    socket.AddressFamily,
    socket.SocketKind,
    int,
    str,
    tuple[str, int] | tuple[str, int, int, int],
]


def _normalized_host(value: str) -> str:
    host = value.strip().rstrip(".").lower()
    # `AnyHttpUrl.host` keeps the brackets around an IPv6 literal, and a bracketed
    # address parses as nothing at all to `ip_address`, which would let a loopback
    # literal through the configuration check as if it were a name.
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def _split_host_port(entry: str) -> tuple[str, str | None]:
    """Split ``host``, ``host:port`` and ``[v6]:port`` into host and port text."""

    value = entry.strip()
    if value.startswith("["):
        host, separator, tail = value[1:].partition("]")
        if not separator:
            raise ValueError(f"trusted destination {entry!r} has an unclosed bracket")
        if not tail:
            return host, None
        if not tail.startswith(":"):
            raise ValueError(
                f"trusted destination {entry!r} must separate its port with ':'"
            )
        return host, tail[1:]
    host, separator, port = value.rpartition(":")
    if not separator or ":" in host:
        return value, None
    return host, port


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """Operator grant for destinations that are not public addresses.

    A grant names either one host with an optional port, or one address network.
    Only an operator writes them, and a host grant is trusted by name, so the
    addresses it resolves to are not required to be global.
    """

    grants: tuple[_Grant, ...] = ()

    @classmethod
    def from_destinations(cls, entries: Iterable[str]) -> "EgressPolicy":
        grants: list[_Grant] = []
        for entry in entries:
            text = entry.strip()
            if not text:
                continue
            host_text, port_text = _split_host_port(text)
            host = _normalized_host(host_text)
            if not host:
                raise ValueError(f"trusted destination {text!r} has no host")
            port: int | None = None
            if port_text is not None:
                if not port_text.isdigit():
                    raise ValueError(
                        f"trusted destination {text!r} has a non-numeric port"
                    )
                port = int(port_text)
                if not 1 <= port <= 65535:
                    raise ValueError(f"trusted destination {text!r} has port {port}")
            try:
                network = ipaddress.ip_network(host, strict=False)
            except ValueError:
                grants.append(_Grant(host=host, port=port, network=None))
                continue
            if network.prefixlen == network.max_prefixlen:
                grants.append(
                    _Grant(host=str(network.network_address), port=port, network=None)
                )
            else:
                grants.append(_Grant(host=None, port=port, network=network))
        return cls(grants=tuple(grants))

    @classmethod
    def from_environment(cls) -> "EgressPolicy":
        """Read the operator grants from ``GRAFY_EGRESS_TRUSTED_DESTINATIONS``.

        The value is a JSON list of destinations, which is the grammar every other
        ``GRAFY_*`` sequence uses, so the same variable text configures the
        ``EgressConfig`` section and this policy.
        """

        raw = os.environ.get(TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE, "").strip()
        if not raw:
            return cls()
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise ValueError(
                f"{TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE} must be a JSON list "
                f"of destinations: {exc}"
            ) from None
        if not isinstance(decoded, list) or not all(
            isinstance(entry, str) for entry in cast("list[object]", decoded)
        ):
            raise ValueError(
                f"{TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE} must be a JSON list "
                "of destination strings"
            )
        return cls.from_destinations(cast(list[str], decoded))

    def trusts_host(self, host: str, port: int) -> bool:
        normalized = _normalized_host(host)
        return any(
            grant.host is not None
            and grant.host == normalized
            and (grant.port is None or grant.port == port)
            for grant in self.grants
        )

    def trusts_address(self, address: str) -> bool:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        return any(
            grant.network is not None
            and parsed.version == grant.network.version
            and parsed in grant.network
            for grant in self.grants
        )


def default_egress_policy() -> EgressPolicy:
    """The deployment policy named by the environment.

    Families build their HTTP clients deep inside provider SDKs, where no composed
    settings object has reached them, so this is read from the environment rather
    than passed down.
    """

    return EgressPolicy.from_environment()


def validated_public_destination(
    value: AnyHttpUrl,
    *,
    service_name: str,
) -> AnyHttpUrl:
    """Reject a service endpoint that is not a nameable public HTTP(S) origin.

    The structural rules belong here so saving the configuration fails instead of
    the first execution: no credentials, no query (request parameters are derived
    from typed configuration), and no literal address that is not global. A name
    is not decided here because its answer is DNS, which is
    :func:`resolved_dial_addresses` at dial time.
    """

    if value.username is not None or value.password is not None:
        raise ValueError(f"{service_name} URL must not contain embedded credentials")
    if value.query is not None:
        raise ValueError(
            f"{service_name} URL must be a query-free service endpoint; request "
            "parameters are derived from typed configuration"
        )
    host = value.host
    if host is None:
        raise ValueError(f"{service_name} URL must include a host")
    normalized_host = _normalized_host(host)
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ValueError(f"{service_name} URL must not target localhost")
    try:
        literal_address = ipaddress.ip_address(normalized_host)
    except ValueError:
        return value
    if not literal_address.is_global:
        raise ValueError(
            f"{service_name} URL must not target a private, loopback, link-local, "
            "reserved, multicast, or unspecified address"
        )
    return value


def dial_port(url: AnyHttpUrl) -> int:
    """The port a request to ``url`` is actually dialed on."""

    if url.port is not None:
        return url.port
    return 443 if url.scheme == "https" else 80


async def _lookup(
    host: str,
    port: int,
    timeout_seconds: float,
) -> list[_AddressRecord]:
    """Resolve one name off the event loop, bounded by ``timeout_seconds``.

    The loop's own resolver would apply its default port and socket type, and the
    decision is per answer, so the record shape is taken whole.
    """

    return await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
        timeout=timeout_seconds,
    )


async def resolved_dial_addresses(
    host: str,
    port: int,
    *,
    policy: EgressPolicy | None = None,
    timeout_seconds: float = DNS_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """The addresses a request to ``host`` may be dialed on, in order.

    Every answer must be a global address unless an operator grant covers the
    destination. A name that resolves to both a public and an internal address is
    rejected rather than narrowed to the public one, because a record set that
    mixes them is how a resolver gets the platform to dial the internal one next
    time.
    """

    effective_policy = default_egress_policy() if policy is None else policy
    normalized_host = _normalized_host(host)
    if not normalized_host:
        raise EgressRejectedError("destination has no host")

    try:
        answers = await _lookup(normalized_host, port, timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise EgressRejectedError(
            f"host {normalized_host!r} did not resolve within {timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        raise EgressRejectedError(
            f"host {normalized_host!r} did not resolve: {exc}"
        ) from exc

    addresses: list[str] = []
    for answer in answers:
        address = str(ipaddress.ip_address(answer[4][0].split("%", maxsplit=1)[0]))
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise EgressRejectedError(f"host {normalized_host!r} resolved to no address")

    if effective_policy.trusts_host(normalized_host, port):
        return tuple(addresses)

    for address in addresses:
        if ipaddress.ip_address(address).is_global or effective_policy.trusts_address(
            address
        ):
            continue
        raise EgressRejectedError(
            f"host {normalized_host!r} resolved to non-public address {address}"
        )
    return tuple(addresses)


class PinnedPublicAddressTransport(httpx.AsyncBaseTransport):
    """Dial the validated address while the request keeps the configured name.

    A provider SDK builds its own requests, so the pin has to go underneath it:
    the URL host becomes one of the validated answers, the ``Host`` header keeps
    the name the service expects, and the TLS server name keeps the name the
    certificate was issued for. Dialing the literal address with a default context
    would verify the certificate against an IP address instead.
    """

    def __init__(
        self,
        *,
        policy: EgressPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = DNS_TIMEOUT_SECONDS,
    ) -> None:
        self._policy = policy
        self._timeout_seconds = timeout_seconds
        self._transport = (
            transport if transport is not None else httpx.AsyncHTTPTransport()
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raw_host = request.url.raw_host
        host = _normalized_host(raw_host.decode("ascii"))
        if not host:
            raise EgressRejectedError(f"request to {request.url} has no host")
        if request.url.scheme not in _ALLOWED_SCHEMES:
            raise EgressRejectedError(
                f"request to {host!r} uses unsupported scheme {request.url.scheme!r}"
            )
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        addresses = await resolved_dial_addresses(
            host,
            port,
            policy=self._policy
            if self._policy is not None
            else default_egress_policy(),
            timeout_seconds=self._timeout_seconds,
        )
        configured_netloc = (
            host
            if port == (443 if request.url.scheme == "https" else 80)
            else f"{host}:{port}"
        )
        for index, address in enumerate(addresses):
            request.url = request.url.copy_with(host=address)
            request.extensions = {**request.extensions, "sni_hostname": host}
            request.headers["host"] = configured_netloc
            try:
                return await self._transport.handle_async_request(request)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if index == len(addresses) - 1:
                    raise
        raise AssertionError("resolved address list was empty")

    async def aclose(self) -> None:
        await self._transport.aclose()


__all__ = [
    "DNS_TIMEOUT_SECONDS",
    "TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE",
    "EgressPolicy",
    "EgressRejectedError",
    "PinnedPublicAddressTransport",
    "dial_port",
    "resolved_dial_addresses",
    "validated_public_destination",
]
