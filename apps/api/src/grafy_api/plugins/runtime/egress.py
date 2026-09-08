"""Fail-closed deployment policy for isolated Plugin egress destinations."""

import asyncio
from collections.abc import Mapping
from hashlib import sha256
import json
import re
import socket
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address, IPv4Network, ip_address
from urllib.parse import urlsplit


_PINNED_IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
PLUGIN_EGRESS_BROKER_CONFIG_VERSION = 2
PLUGIN_EGRESS_BROKER_CONFIG_VERSION_LABEL = (
    "io.grafy.plugin.egress-broker.policy-config-version"
)
PLUGIN_HTTP_PROXY_PORT = 3128
PLUGIN_EGRESS_CONNECTION_LIMIT = 128
PLUGIN_EGRESS_MAX_HEADER_BYTES = 64 * 1_024
PLUGIN_EGRESS_MAX_REQUEST_BYTES = 64 * 1_024 * 1_024
PLUGIN_EGRESS_MAX_RESPONSE_BYTES = 128 * 1_024 * 1_024
PLUGIN_EGRESS_CONNECT_TIMEOUT_SECONDS = 10
PLUGIN_EGRESS_IDLE_TIMEOUT_SECONDS = 60


class PluginEgressProtocol(StrEnum):
    HTTP = "http"
    HTTPS = "https"
    POSTGRESQL = "postgresql"


class PluginEgressAddressScope(StrEnum):
    """Numeric address classes one already-authorized destination may use."""

    PUBLIC = "public"
    CURATED_RFC1918 = "curated-rfc1918"


@dataclass(frozen=True, slots=True)
class PluginEgressLimits:
    """Resource limits one broker plan enforces; the broker revalidates them."""

    connection_limit: int = PLUGIN_EGRESS_CONNECTION_LIMIT
    max_header_bytes: int = PLUGIN_EGRESS_MAX_HEADER_BYTES
    max_request_bytes: int = PLUGIN_EGRESS_MAX_REQUEST_BYTES
    max_response_bytes: int = PLUGIN_EGRESS_MAX_RESPONSE_BYTES
    connect_timeout_seconds: int = PLUGIN_EGRESS_CONNECT_TIMEOUT_SECONDS
    idle_timeout_seconds: int = PLUGIN_EGRESS_IDLE_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True, order=True)
class PluginEgressDestination:
    """One exact deployment-authorized protocol, DNS name, and port."""

    protocol: PluginEgressProtocol
    host: str
    port: int

    def __post_init__(self) -> None:
        normalized_host = self.host.rstrip(".").casefold()
        if (
            normalized_host == ""
            or len(normalized_host) > 253
            or normalized_host == "localhost"
            or normalized_host.endswith(".localhost")
            or "*" in normalized_host
            or any(
                _DNS_LABEL.fullmatch(label) is None
                for label in normalized_host.split(".")
            )
        ):
            raise ValueError("Plugin egress host must be one exact DNS name")
        try:
            literal = ip_address(normalized_host.removeprefix("[").removesuffix("]"))
        except ValueError:
            literal = None
        if literal is not None:
            raise ValueError("Plugin egress destinations must use an exact DNS name")
        if not 1 <= self.port <= 65_535:
            raise ValueError("Plugin egress destination port must be between 1 and 65535")
        object.__setattr__(self, "host", normalized_host)

    @classmethod
    def parse(cls, value: str) -> "PluginEgressDestination":
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Plugin egress destination has an invalid port") from exc
        if (
            parsed.scheme not in {protocol.value for protocol in PluginEgressProtocol}
            or parsed.hostname is None
            or port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Plugin egress destination must be an exact protocol://host:port"
            )
        return cls(
            protocol=PluginEgressProtocol(parsed.scheme),
            host=parsed.hostname,
            port=port,
        )

    @property
    def authority(self) -> str:
        return f"{self.host}:{self.port}"

    @classmethod
    def from_config_url(cls, value: str) -> "PluginEgressDestination":
        """Normalize one validated node-config value into an exact origin.

        Paths, queries, and fragments are network authority-free and are
        discarded; userinfo, IP literals, wildcards, and localhost names are
        rejected. The result always carries an explicit effective port.
        """

        if not isinstance(value, str) or value != value.strip():
            raise ValueError("HTTP egress destination must be a string URL")
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in {"http", "https"}:
            raise ValueError("HTTP egress destination must be an absolute HTTP URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("HTTP egress destination must not embed credentials")
        hostname = parsed.hostname
        if hostname is None:
            raise ValueError("HTTP egress destination must include a host")
        normalized_host = hostname.rstrip(".").casefold()
        if normalized_host == "" or len(normalized_host) > 253:
            raise ValueError("HTTP egress destination host must be a DNS name")
        if (
            normalized_host == "localhost"
            or normalized_host.endswith(".localhost")
            or "*" in normalized_host
            or any(
                _DNS_LABEL.fullmatch(label) is None
                for label in normalized_host.split(".")
            )
        ):
            raise ValueError(
                "HTTP egress destination must use an exact public DNS name"
            )
        try:
            literal = ip_address(
                normalized_host.removeprefix("[").removesuffix("]")
            )
        except ValueError:
            literal = None
        if literal is not None:
            raise ValueError(
                "HTTP egress destination must use an exact DNS name"
            )
        protocol = PluginEgressProtocol(parsed.scheme.casefold())
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("HTTP egress destination has an invalid port") from exc
        if port is None:
            port = 443 if protocol is PluginEgressProtocol.HTTPS else 80
        return cls(protocol=protocol, host=normalized_host, port=port)


@dataclass(frozen=True, slots=True)
class PluginEgressBrokerPolicy:
    """A pinned owned broker plus its exact deployment destination allowlist."""

    broker_image: str | None = None
    destinations: tuple[PluginEgressDestination, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(sorted(set(self.destinations)))
        if len(normalized) != len(self.destinations):
            raise ValueError("Plugin egress destinations must be unique")
        if len(normalized) > 128:
            raise ValueError("Plugin egress supports at most 128 destinations")
        if self.broker_image is not None and _PINNED_IMAGE.fullmatch(self.broker_image) is None:
            raise ValueError("Plugin egress broker image must be pinned by sha256 digest")
        object.__setattr__(self, "destinations", normalized)

    @property
    def available(self) -> bool:
        return self.broker_image is not None and bool(self.destinations)

    def destinations_for(
        self,
        protocol: PluginEgressProtocol,
    ) -> tuple[PluginEgressDestination, ...]:
        return tuple(
            destination
            for destination in self.destinations
            if destination.protocol is protocol
        )

    async def resolve_for_capabilities(
        self,
        *,
        sandbox_key_sha256: str,
        http_enabled: bool,
        postgresql_enabled: bool,
        postgresql_destination: PluginEgressDestination | None = None,
    ) -> "PluginEgressBrokerPlan":
        if not self.available or self.broker_image is None:
            raise RuntimeError("Plugin egress broker policy is unavailable")
        if re.fullmatch(r"[0-9a-f]{64}", sandbox_key_sha256) is None:
            raise ValueError("Plugin sandbox key digest must be sha256")
        selected = tuple(
            destination
            for destination in self.destinations
            if (
                http_enabled
                and destination.protocol
                in {PluginEgressProtocol.HTTP, PluginEgressProtocol.HTTPS}
            )
            or (
                postgresql_enabled
                and destination.protocol is PluginEgressProtocol.POSTGRESQL
                and destination == postgresql_destination
            )
        )
        if postgresql_enabled and (
            postgresql_destination is None
            or postgresql_destination not in self.destinations
        ):
            raise PermissionError(
                "PostgreSQL destination is not in the deployment egress allowlist"
            )
        if not selected:
            raise RuntimeError(
                "Plugin egress broker has no destination for required capabilities"
            )
        resolved = await asyncio.wait_for(
            asyncio.gather(
                *(resolve_public_destination(destination) for destination in selected)
            ),
            timeout=10,
        )
        return PluginEgressBrokerPlan.from_resolved(
            broker_image=self.broker_image,
            sandbox_key_sha256=sandbox_key_sha256,
            destinations=tuple(resolved),
        )


@dataclass(frozen=True, slots=True)
class ResolvedPluginEgressDestination:
    destination: PluginEgressDestination
    addresses: tuple[IPv4Address | IPv6Address, ...]
    address_scope: PluginEgressAddressScope = PluginEgressAddressScope.PUBLIC


@dataclass(frozen=True, slots=True)
class PluginPostgresqlRelay:
    """One raw TCP listener bound to one already-resolved PostgreSQL target."""

    destination: PluginEgressDestination
    listen_port: int


@dataclass(frozen=True, slots=True)
class PluginEgressBrokerPlan:
    """Non-secret, immutable config for one sandbox's pinned broker sidecar.

    The broker contract must never perform DNS. It accepts HTTP requests only
    for the exact scheme/host/port entries below and connects one numeric
    address from ``connect_addresses``. HTTPS is tunneled end-to-end only after
    an exact CONNECT authority match. PostgreSQL listeners are raw TCP relays,
    not CONNECT endpoints.
    """

    broker_image: str
    sandbox_key_sha256: str
    destinations: tuple[ResolvedPluginEgressDestination, ...]
    postgresql_relays: tuple[PluginPostgresqlRelay, ...]
    limits: PluginEgressLimits = PluginEgressLimits()

    @classmethod
    def from_resolved(
        cls,
        *,
        broker_image: str,
        sandbox_key_sha256: str,
        destinations: tuple[ResolvedPluginEgressDestination, ...],
        limits: PluginEgressLimits | None = None,
    ) -> "PluginEgressBrokerPlan":
        postgresql_destinations = tuple(
            resolved.destination
            for resolved in destinations
            if resolved.destination.protocol is PluginEgressProtocol.POSTGRESQL
        )
        if postgresql_destinations and any(
            resolved.destination.protocol
            in {PluginEgressProtocol.HTTP, PluginEgressProtocol.HTTPS}
            for resolved in destinations
        ) and any(
            destination.port == PLUGIN_HTTP_PROXY_PORT
            for destination in postgresql_destinations
        ):
            raise ValueError("PostgreSQL relay port conflicts with the HTTP proxy")
        return cls(
            broker_image=broker_image,
            sandbox_key_sha256=sandbox_key_sha256,
            destinations=destinations,
            postgresql_relays=tuple(
                PluginPostgresqlRelay(
                    destination=destination,
                    listen_port=destination.port,
                )
                for destination in postgresql_destinations
            ),
            limits=limits or PluginEgressLimits(),
        )

    @property
    def http_proxy_enabled(self) -> bool:
        return any(
            resolved.destination.protocol
            in {PluginEgressProtocol.HTTP, PluginEgressProtocol.HTTPS}
            for resolved in self.destinations
        )

    @property
    def policy_sha256(self) -> str:
        return sha256(self.canonical_json_bytes()).hexdigest()

    def postgresql_relay_for(
        self,
        *,
        host: object,
        port: object,
    ) -> PluginPostgresqlRelay:
        if (
            not isinstance(host, str)
            or not isinstance(port, int)
            or isinstance(port, bool)
        ):
            raise PermissionError(
                "PostgreSQL egress requires exact string host and integer port config"
            )
        requested = PluginEgressDestination(
            protocol=PluginEgressProtocol.POSTGRESQL,
            host=host,
            port=port,
        )
        for relay in self.postgresql_relays:
            if relay.destination == requested:
                return relay
        raise PermissionError(
            "PostgreSQL destination is not in the deployment egress allowlist"
        )

    def canonical_json_bytes(self) -> bytes:
        http_destinations: list[Mapping[str, object]] = []
        postgresql_relays: list[Mapping[str, object]] = []
        relay_ports = {
            relay.destination: relay.listen_port for relay in self.postgresql_relays
        }
        for resolved in self.destinations:
            destination = resolved.destination
            serialized: dict[str, object] = {
                "protocol": destination.protocol.value,
                "host": destination.host,
                "port": destination.port,
                "address_scope": resolved.address_scope.value,
                "connect_addresses": [
                    str(address) for address in resolved.addresses
                ],
            }
            if destination.protocol is PluginEgressProtocol.POSTGRESQL:
                serialized["listen_port"] = relay_ports[destination]
                postgresql_relays.append(serialized)
            else:
                http_destinations.append(serialized)
        document = {
            "config_version": PLUGIN_EGRESS_BROKER_CONFIG_VERSION,
            "identity": {
                "mode": "dedicated-internal-network",
                "sandbox_key_sha256": self.sandbox_key_sha256,
            },
            "http_proxy": {
                "listen_port": PLUGIN_HTTP_PROXY_PORT,
                "destinations": http_destinations,
                "dns_resolution": "forbidden",
                "https_mode": "connect-tunnel",
            },
            "postgresql_relays": postgresql_relays,
            "limits": {
                "connection_limit": self.limits.connection_limit,
                "max_header_bytes": self.limits.max_header_bytes,
                "max_request_bytes": self.limits.max_request_bytes,
                "max_response_bytes": self.limits.max_response_bytes,
                "connect_timeout_seconds": self.limits.connect_timeout_seconds,
                "idle_timeout_seconds": self.limits.idle_timeout_seconds,
            },
        }
        return (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")


async def resolve_public_destination(
    destination: PluginEgressDestination,
) -> ResolvedPluginEgressDestination:
    return await resolve_plugin_egress_destination(
        destination,
        address_scope=PluginEgressAddressScope.PUBLIC,
    )


async def resolve_plugin_egress_destination(
    destination: PluginEgressDestination,
    *,
    address_scope: PluginEgressAddressScope,
) -> ResolvedPluginEgressDestination:
    """Resolve once, reject every unsafe answer, and return numeric addresses.

    A broker must connect one returned numeric address directly. Resolving the
    hostname again at connect time would reintroduce DNS-rebinding authority.
    """

    loop = asyncio.get_running_loop()
    answers = await loop.getaddrinfo(
        destination.host,
        destination.port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    addresses = tuple(
        sorted(
            {ip_address(answer[4][0]) for answer in answers},
            key=lambda address: (address.version, address.packed),
        )
    )
    if not addresses:
        raise OSError("Plugin egress destination returned no DNS addresses")
    allowed = _is_public_address
    if address_scope is PluginEgressAddressScope.CURATED_RFC1918:
        allowed = _is_public_or_rfc1918_address
    if any(not allowed(address) for address in addresses):
        raise PermissionError(
            "Plugin egress DNS returned an address outside its explicit "
            f"{address_scope.value} scope"
        )
    return ResolvedPluginEgressDestination(
        destination=destination,
        addresses=addresses,
        address_scope=address_scope,
    )


def _is_public_address(address: IPv4Address | IPv6Address) -> bool:
    return (
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


_RFC1918_NETWORKS = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)


def _is_public_or_rfc1918_address(address: IPv4Address | IPv6Address) -> bool:
    return _is_public_address(address) or (
        isinstance(address, IPv4Address)
        and any(address in network for network in _RFC1918_NETWORKS)
    )


__all__ = [
    "PLUGIN_EGRESS_BROKER_CONFIG_VERSION",
    "PLUGIN_EGRESS_BROKER_CONFIG_VERSION_LABEL",
    "PLUGIN_HTTP_PROXY_PORT",
    "PluginEgressAddressScope",
    "PluginEgressBrokerPolicy",
    "PluginEgressBrokerPlan",
    "PluginEgressDestination",
    "PluginEgressLimits",
    "PluginEgressProtocol",
    "PluginPostgresqlRelay",
    "ResolvedPluginEgressDestination",
    "resolve_public_destination",
    "resolve_plugin_egress_destination",
]
