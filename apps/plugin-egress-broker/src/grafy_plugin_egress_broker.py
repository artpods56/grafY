#!/usr/bin/env python3
"""First-party numeric-target HTTP/HTTPS and PostgreSQL egress broker."""

import argparse
import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from ipaddress import IPv4Address, IPv6Address, IPv4Network, ip_address
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import NoReturn, cast
from urllib.parse import urlsplit


_READY_PATH = Path("/tmp/grafy-egress-ready")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class BrokerConfigError(ValueError):
    pass


class BrokerRequestError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BrokerLimits:
    connection_limit: int
    max_header_bytes: int
    max_request_bytes: int
    max_response_bytes: int
    connect_timeout_seconds: int
    idle_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class BrokerDestination:
    protocol: str
    host: str
    port: int
    connect_addresses: tuple[IPv4Address | IPv6Address, ...]
    address_scope: str = "public"
    listen_port: int | None = None


@dataclass(frozen=True, slots=True)
class BrokerPolicy:
    policy_sha256: str
    sandbox_key_sha256: str
    http_port: int
    http_destinations: tuple[BrokerDestination, ...]
    postgresql_relays: tuple[BrokerDestination, ...]
    limits: BrokerLimits


def load_policy(path: Path) -> BrokerPolicy:
    return load_policy_bytes(path.read_bytes())


def load_policy_bytes(content: bytes) -> BrokerPolicy:
    if len(content) > 1_048_576:
        raise BrokerConfigError("Broker policy exceeds its byte limit")
    try:
        raw = cast(object, json.loads(content))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerConfigError("Broker policy is not valid JSON") from exc
    document = _mapping(raw, "policy")
    _exact_keys(
        document,
        {"config_version", "identity", "http_proxy", "postgresql_relays", "limits"},
        "policy",
    )
    if document["config_version"] != 2:
        raise BrokerConfigError("Broker policy config version is unsupported")

    identity = _mapping(document["identity"], "identity")
    _exact_keys(identity, {"mode", "sandbox_key_sha256"}, "identity")
    sandbox_key = identity["sandbox_key_sha256"]
    if (
        identity["mode"] != "dedicated-internal-network"
        or not isinstance(sandbox_key, str)
        or _DIGEST.fullmatch(sandbox_key) is None
    ):
        raise BrokerConfigError("Broker workload identity is invalid")

    http = _mapping(document["http_proxy"], "http_proxy")
    _exact_keys(
        http,
        {"listen_port", "destinations", "dns_resolution", "https_mode"},
        "http_proxy",
    )
    if (
        http["dns_resolution"] != "forbidden"
        or http["https_mode"] != "connect-tunnel"
    ):
        raise BrokerConfigError("Broker HTTP policy would widen network authority")
    http_port = _port(http["listen_port"], "HTTP listen port")
    http_values_raw = http["destinations"]
    if not isinstance(http_values_raw, list):
        raise BrokerConfigError("HTTP destinations must be a list")
    http_values = cast(list[object], http_values_raw)
    http_destinations = tuple(
        _destination(value, expected_protocols={"http", "https"}, relay=False)
        for value in http_values
    )

    postgresql_values_raw = document["postgresql_relays"]
    if not isinstance(postgresql_values_raw, list):
        raise BrokerConfigError("PostgreSQL relays must be a list")
    postgresql_values = cast(list[object], postgresql_values_raw)
    postgresql_relays = tuple(
        _destination(value, expected_protocols={"postgresql"}, relay=True)
        for value in postgresql_values
    )
    relay_ports = [relay.listen_port for relay in postgresql_relays]
    if len(relay_ports) != len(set(relay_ports)):
        raise BrokerConfigError("PostgreSQL relay listen ports must be unique")
    if any(relay.listen_port != relay.port for relay in postgresql_relays):
        raise BrokerConfigError(
            "PostgreSQL relay must preserve the declared port for TLS identity"
        )
    if http_destinations and any(
        relay.listen_port == http_port for relay in postgresql_relays
    ):
        raise BrokerConfigError("PostgreSQL relay port conflicts with HTTP proxy")

    limits_value = _mapping(document["limits"], "limits")
    _exact_keys(
        limits_value,
        {
            "connection_limit",
            "max_header_bytes",
            "max_request_bytes",
            "max_response_bytes",
            "connect_timeout_seconds",
            "idle_timeout_seconds",
        },
        "limits",
    )
    limits = BrokerLimits(
        connection_limit=_bounded_int(
            limits_value["connection_limit"], 1, 1_024, "connection limit"
        ),
        max_header_bytes=_bounded_int(
            limits_value["max_header_bytes"], 1_024, 1_048_576, "header limit"
        ),
        max_request_bytes=_bounded_int(
            limits_value["max_request_bytes"],
            1_024,
            1_073_741_824,
            "request limit",
        ),
        max_response_bytes=_bounded_int(
            limits_value["max_response_bytes"],
            1_024,
            1_073_741_824,
            "response limit",
        ),
        connect_timeout_seconds=_bounded_int(
            limits_value["connect_timeout_seconds"], 1, 60, "connect timeout"
        ),
        idle_timeout_seconds=_bounded_int(
            limits_value["idle_timeout_seconds"], 1, 900, "idle timeout"
        ),
    )
    if not http_destinations and not postgresql_relays:
        raise BrokerConfigError("Broker policy has no destinations")
    identities = [
        (destination.protocol, destination.host, destination.port)
        for destination in (*http_destinations, *postgresql_relays)
    ]
    if len(identities) != len(set(identities)):
        raise BrokerConfigError("Broker destinations must be unique")
    return BrokerPolicy(
        policy_sha256=sha256(content).hexdigest(),
        sandbox_key_sha256=sandbox_key,
        http_port=http_port,
        http_destinations=http_destinations,
        postgresql_relays=postgresql_relays,
        limits=limits,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise BrokerConfigError(f"Broker {name} must be an object")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise BrokerConfigError(f"Broker {name} must use string field names")
    return cast(Mapping[str, object], raw)


def _exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise BrokerConfigError(f"Broker {name} has unexpected or missing fields")


def _bounded_int(value: object, minimum: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BrokerConfigError(f"Broker {name} must be an integer")
    if not minimum <= value <= maximum:
        raise BrokerConfigError(f"Broker {name} is outside its allowed range")
    return value


def _port(value: object, name: str) -> int:
    return _bounded_int(value, 1, 65_535, name)


def _destination(
    value: object,
    *,
    expected_protocols: set[str],
    relay: bool,
) -> BrokerDestination:
    parsed = _mapping(value, "destination")
    expected = {
        "protocol",
        "host",
        "port",
        "address_scope",
        "connect_addresses",
    }
    if relay:
        expected.add("listen_port")
    _exact_keys(parsed, expected, "destination")
    protocol = parsed["protocol"]
    host = parsed["host"]
    address_scope = parsed["address_scope"]
    addresses_value_raw = parsed["connect_addresses"]
    if not isinstance(protocol, str) or protocol not in expected_protocols:
        raise BrokerConfigError("Broker destination protocol is invalid")
    if address_scope not in {"public", "curated-rfc1918"}:
        raise BrokerConfigError("Broker destination address scope is invalid")
    if relay and address_scope != "public":
        raise BrokerConfigError("Broker relay address scope must be public")
    if (
        not isinstance(host, str)
        or host == ""
        or host != host.rstrip(".").casefold()
        or "*" in host
        or any(_DNS_LABEL.fullmatch(label) is None for label in host.split("."))
    ):
        raise BrokerConfigError("Broker destination host is invalid")
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        raise BrokerConfigError("Broker destination host must be a DNS name")
    if not isinstance(addresses_value_raw, list) or not addresses_value_raw:
        raise BrokerConfigError("Broker destination has no numeric addresses")
    addresses_value = cast(list[object], addresses_value_raw)
    addresses: list[IPv4Address | IPv6Address] = []
    for address_value in addresses_value:
        if not isinstance(address_value, str):
            raise BrokerConfigError("Broker connect address must be numeric")
        try:
            address = ip_address(address_value)
        except ValueError as exc:
            raise BrokerConfigError("Broker connect address must be numeric") from exc
        if not _address_in_scope(address, cast(str, address_scope)):
            raise BrokerConfigError(
                f"Broker connect address is outside its {address_scope} scope"
            )
        addresses.append(address)
    if len(addresses) != len(set(addresses)):
        raise BrokerConfigError("Broker connect addresses must be unique")
    return BrokerDestination(
        protocol=protocol,
        host=host,
        port=_port(parsed["port"], "destination port"),
        address_scope=cast(str, address_scope),
        connect_addresses=tuple(addresses),
        listen_port=(
            _port(parsed["listen_port"], "relay listen port") if relay else None
        ),
    )


_RFC1918_NETWORKS = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)


def _address_in_scope(
    address: IPv4Address | IPv6Address,
    scope: str,
) -> bool:
    public = (
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )
    if public:
        return True
    return scope == "curated-rfc1918" and isinstance(
        address, IPv4Address
    ) and any(address in network for network in _RFC1918_NETWORKS)


async def _open_numeric_connection(
    destination: BrokerDestination,
    timeout: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    last_error: OSError | None = None
    for address in destination.connect_addresses:
        family = socket.AF_INET if address.version == 4 else socket.AF_INET6
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(
                    str(address),
                    destination.port,
                    family=family,
                    flags=socket.AI_NUMERICHOST,
                ),
                timeout=timeout,
            )
        except OSError as exc:
            last_error = exc
    raise OSError("No authorized numeric connect target was reachable") from last_error


def _destination_for_http(
    policy: BrokerPolicy,
    *,
    protocol: str,
    host: str,
    port: int,
) -> BrokerDestination:
    normalized = host.rstrip(".").casefold()
    for destination in policy.http_destinations:
        if (
            destination.protocol == protocol
            and destination.host == normalized
            and destination.port == port
        ):
            return destination
    raise BrokerRequestError("Destination is not allowed")


async def _read_headers(
    reader: asyncio.StreamReader,
    policy: BrokerPolicy,
) -> tuple[str, list[tuple[str, str]]]:
    try:
        content = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"),
            timeout=policy.limits.idle_timeout_seconds,
        )
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
        raise BrokerRequestError("Invalid proxy request headers") from exc
    if len(content) > policy.limits.max_header_bytes:
        raise BrokerRequestError("Proxy request headers exceed their limit")
    try:
        lines = content[:-4].decode("iso-8859-1").split("\r\n")
    except UnicodeDecodeError as exc:
        raise BrokerRequestError("Invalid proxy request headers") from exc
    if not lines or len(lines[0].split(" ")) != 3:
        raise BrokerRequestError("Invalid proxy request line")
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        name, separator, raw_value = line.partition(":")
        if not separator or name.strip() != name or name == "":
            raise BrokerRequestError("Invalid proxy request header")
        headers.append((name, raw_value.strip()))
    return lines[0], headers


async def _http_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    policy: BrokerPolicy,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    tunnel_established = False
    try:
        request_line, headers = await _read_headers(reader, policy)
        method, target, version = request_line.split(" ")
        if version not in {"HTTP/1.0", "HTTP/1.1"}:
            raise BrokerRequestError("Unsupported HTTP version")
        if method == "CONNECT":
            host, separator, port_value = target.rpartition(":")
            if not separator:
                raise BrokerRequestError("CONNECT requires an exact authority")
            try:
                port = int(port_value)
            except ValueError as exc:
                raise BrokerRequestError("CONNECT port is invalid") from exc
            destination = _destination_for_http(
                policy,
                protocol="https",
                host=host,
                port=port,
            )
            upstream_reader, upstream_writer = await _open_numeric_connection(
                destination,
                policy.limits.connect_timeout_seconds,
            )
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            tunnel_established = True
            await _relay_bidirectional(
                reader,
                writer,
                upstream_reader,
                upstream_writer,
                client_byte_limit=policy.limits.max_request_bytes,
                upstream_byte_limit=policy.limits.max_response_bytes,
                idle_timeout=policy.limits.idle_timeout_seconds,
            )
            return

        parsed = urlsplit(target)
        if (
            parsed.scheme != "http"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise BrokerRequestError("HTTP proxy target must be an absolute HTTP URL")
        try:
            port = parsed.port or 80
        except ValueError as exc:
            raise BrokerRequestError("HTTP proxy target port is invalid") from exc
        destination = _destination_for_http(
            policy,
            protocol="http",
            host=parsed.hostname,
            port=port,
        )
        content_lengths = [
            value for name, value in headers if name.casefold() == "content-length"
        ]
        if len(content_lengths) > 1:
            raise BrokerRequestError("Multiple Content-Length headers are forbidden")
        if any(name.casefold() == "transfer-encoding" for name, _ in headers):
            raise BrokerRequestError("Transfer-Encoding is unsupported")
        try:
            content_length = int(content_lengths[0]) if content_lengths else 0
        except ValueError as exc:
            raise BrokerRequestError("Content-Length is invalid") from exc
        if not 0 <= content_length <= policy.limits.max_request_bytes:
            raise BrokerRequestError("HTTP request body exceeds its limit")
        body = await asyncio.wait_for(
            reader.readexactly(content_length),
            timeout=policy.limits.idle_timeout_seconds,
        )
        origin_target = parsed.path or "/"
        if parsed.query:
            origin_target = f"{origin_target}?{parsed.query}"
        forwarded_headers = [
            (name, value)
            for name, value in headers
            if name.casefold()
            not in {"connection", "host", "proxy-authorization", "proxy-connection"}
        ]
        authority = destination.host
        if destination.port != 80:
            authority = f"{authority}:{destination.port}"
        forwarded = [
            f"{method} {origin_target} {version}",
            f"Host: {authority}",
            *(f"{name}: {value}" for name, value in forwarded_headers),
            "Connection: close",
            "",
            "",
        ]
        upstream_reader, upstream_writer = await _open_numeric_connection(
            destination,
            policy.limits.connect_timeout_seconds,
        )
        # No request-side half-close: many origins (e.g. Cloudflare) treat an
        # early FIN as an aborted request and close without responding.
        upstream_writer.write("\r\n".join(forwarded).encode("iso-8859-1"))
        upstream_writer.write(body)
        await upstream_writer.drain()
        await _copy_stream(
            upstream_reader,
            writer,
            byte_limit=policy.limits.max_response_bytes,
            idle_timeout=policy.limits.idle_timeout_seconds,
        )
    except BrokerRequestError:
        writer.write(
            b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
        )
        await writer.drain()
    except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError):
        if not tunnel_established:
            writer.write(
                b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n"
                b"Content-Length: 0\r\n\r\n"
            )
            await writer.drain()
    finally:
        if upstream_writer is not None:
            upstream_writer.close()
            try:
                await upstream_writer.wait_closed()
            except OSError:
                pass
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def _postgresql_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    policy: BrokerPolicy,
    destination: BrokerDestination,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        upstream_reader, upstream_writer = await _open_numeric_connection(
            destination,
            policy.limits.connect_timeout_seconds,
        )
        await _relay_bidirectional(
            reader,
            writer,
            upstream_reader,
            upstream_writer,
            client_byte_limit=policy.limits.max_request_bytes,
            upstream_byte_limit=policy.limits.max_response_bytes,
            idle_timeout=policy.limits.idle_timeout_seconds,
        )
    except (OSError, asyncio.TimeoutError):
        pass
    finally:
        if upstream_writer is not None:
            upstream_writer.close()
            try:
                await upstream_writer.wait_closed()
            except OSError:
                pass
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def _copy_stream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    byte_limit: int,
    idle_timeout: int,
) -> None:
    byte_count = 0
    while True:
        chunk = await asyncio.wait_for(reader.read(64 * 1_024), timeout=idle_timeout)
        if not chunk:
            if writer.can_write_eof():
                writer.write_eof()
            return
        byte_count += len(chunk)
        if byte_count > byte_limit:
            raise OSError("Broker relay byte limit exceeded")
        writer.write(chunk)
        await writer.drain()


async def _relay_bidirectional(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
    *,
    client_byte_limit: int,
    upstream_byte_limit: int,
    idle_timeout: int,
) -> None:
    tasks = {
        asyncio.create_task(_copy_stream(
            client_reader,
            upstream_writer,
            byte_limit=client_byte_limit,
            idle_timeout=idle_timeout,
        )),
        asyncio.create_task(_copy_stream(
            upstream_reader,
            client_writer,
            byte_limit=upstream_byte_limit,
            idle_timeout=idle_timeout,
        )),
    }
    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_EXCEPTION,
        )
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    failure = next(
        (
            task.exception()
            for task in done
            if not task.cancelled() and task.exception() is not None
        ),
        None,
    )
    if failure is None:
        return
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    raise failure


def _bounded_handler(
    semaphore: asyncio.Semaphore,
    handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
    async def run(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if semaphore.locked():
            writer.close()
            await writer.wait_closed()
            return
        async with semaphore:
            await handler(reader, writer)

    return run


async def serve(policy: BrokerPolicy) -> None:
    semaphore = asyncio.Semaphore(policy.limits.connection_limit)
    servers: list[asyncio.AbstractServer] = []
    if policy.http_destinations:
        servers.append(
            await asyncio.start_server(
                _bounded_handler(
                    semaphore,
                    lambda reader, writer: _http_connection(
                        reader, writer, policy
                    ),
                ),
                "0.0.0.0",
                policy.http_port,
                limit=policy.limits.max_header_bytes,
            )
        )
    for destination in policy.postgresql_relays:
        assert destination.listen_port is not None
        servers.append(
            await asyncio.start_server(
                _bounded_handler(
                    semaphore,
                    lambda reader, writer, target=destination: (
                        _postgresql_connection(reader, writer, policy, target)
                    ),
                ),
                "0.0.0.0",
                destination.listen_port,
            )
        )
    _READY_PATH.write_text(policy.policy_sha256 + "\n", encoding="ascii")
    try:
        async with _server_context(servers):
            await asyncio.gather(*(server.serve_forever() for server in servers))
    finally:
        _READY_PATH.unlink(missing_ok=True)


class _server_context:
    def __init__(self, servers: list[asyncio.AbstractServer]) -> None:
        self._servers = servers

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        for server in self._servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in self._servers))


def ready(expected_policy_sha256: str, timeout_seconds: int) -> None:
    if _DIGEST.fullmatch(expected_policy_sha256) is None:
        raise BrokerConfigError("Expected policy digest is invalid")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            actual = _READY_PATH.read_text(encoding="ascii").strip()
        except OSError:
            actual = ""
        if actual == expected_policy_sha256:
            return
        if actual and actual != expected_policy_sha256:
            raise BrokerConfigError("Broker is running a different policy")
        if time.monotonic() >= deadline:
            raise BrokerConfigError("Broker is not ready")
        time.sleep(0.05)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grafy-plugin-egress-broker")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_command = commands.add_parser("serve")
    source = serve_command.add_mutually_exclusive_group(required=True)
    source.add_argument("--policy", type=Path)
    source.add_argument("--policy-env")
    ready_command = commands.add_parser("ready")
    ready_command.add_argument("--policy-sha256", required=True)
    ready_command.add_argument("--timeout-seconds", type=int, default=5)
    return parser


def main() -> NoReturn:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "serve":
            if arguments.policy is not None:
                policy = load_policy(arguments.policy)
            else:
                encoded = os.environ.get(arguments.policy_env, "")
                try:
                    content = base64.b64decode(encoded, validate=True)
                except ValueError as exc:
                    raise BrokerConfigError(
                        "Broker policy environment is not valid base64"
                    ) from exc
                policy = load_policy_bytes(content)
            asyncio.run(serve(policy))
        else:
            ready(arguments.policy_sha256, arguments.timeout_seconds)
    except (BrokerConfigError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    raise SystemExit(0)


if __name__ == "__main__":
    main()
