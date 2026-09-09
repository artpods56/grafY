import asyncio
from ipaddress import IPv4Address, ip_address
from pathlib import Path
import socket
import subprocess
import sys
from typing import cast

import pytest

from grafy_api.plugins.runtime.egress import (
    PLUGIN_EGRESS_BROKER_CONFIG_VERSION,
    PLUGIN_EGRESS_BROKER_CONFIG_VERSION_LABEL,
    PluginEgressAddressScope,
    PluginEgressBrokerPlan,
    PluginEgressDestination,
    ResolvedPluginEgressDestination,
)
import grafy_plugin_egress_broker as plugin_egress_broker
from grafy_plugin_egress_broker import (
    BrokerConfigError,
    BrokerDestination,
    BrokerPolicy,
    _http_connection,  # pyright: ignore[reportPrivateUsage]
    _postgresql_connection,  # pyright: ignore[reportPrivateUsage]
    load_policy,
)


_BROKER_IMAGE = "registry.example/grafy-egress@sha256:" + "a" * 64


def test_broker_image_declares_the_host_policy_contract() -> None:
    repository = Path(__file__).resolve().parents[3]
    dockerfile = (
        repository / "infra/docker/plugin-egress-broker.Dockerfile"
    ).read_text(encoding="utf-8")

    assert (
        f"LABEL {PLUGIN_EGRESS_BROKER_CONFIG_VERSION_LABEL}="
        f'"{PLUGIN_EGRESS_BROKER_CONFIG_VERSION}"'
    ) in dockerfile


def _write_policy(
    path: Path,
    *destinations: tuple[str, str],
) -> BrokerPolicy:
    resolved = tuple(
        ResolvedPluginEgressDestination(
            PluginEgressDestination.parse(value),
            (ip_address(address),),
        )
        for value, address in destinations
    )
    plan = PluginEgressBrokerPlan.from_resolved(
        broker_image=_BROKER_IMAGE,
        sandbox_key_sha256="b" * 64,
        destinations=resolved,
    )
    path.write_bytes(plan.canonical_json_bytes())
    return load_policy(path)


def test_broker_loads_only_exact_public_numeric_policy(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy = _write_policy(
        policy_path,
        ("http://api.example.com:80", "93.184.216.34"),
        ("https://secure.example.com:443", "8.8.8.8"),
        ("postgresql://database.example.com:5432", "1.1.1.1"),
    )

    assert policy.sandbox_key_sha256 == "b" * 64
    assert policy.postgresql_relays[0].listen_port == 5432
    assert policy.limits.connection_limit == 128
    assert (
        policy.policy_sha256
        == PluginEgressBrokerPlan.from_resolved(
            broker_image=_BROKER_IMAGE,
            sandbox_key_sha256="b" * 64,
            destinations=tuple(
                ResolvedPluginEgressDestination(
                    PluginEgressDestination.parse(value),
                    (ip_address(address),),
                )
                for value, address in (
                    ("http://api.example.com:80", "93.184.216.34"),
                    ("https://secure.example.com:443", "8.8.8.8"),
                    ("postgresql://database.example.com:5432", "1.1.1.1"),
                )
            ),
        ).policy_sha256
    )

    content = policy_path.read_text(encoding="utf-8")
    policy_path.write_text(
        content.replace('"config_version":2', '"config_version":1'),
        encoding="utf-8",
    )
    with pytest.raises(BrokerConfigError, match="version is unsupported"):
        load_policy(policy_path)


def test_broker_rejects_private_or_hostname_connect_targets(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    _write_policy(
        policy_path,
        ("https://secure.example.com:443", "8.8.8.8"),
    )
    content = policy_path.read_text(encoding="utf-8")

    policy_path.write_text(content.replace("8.8.8.8", "127.0.0.1"), encoding="utf-8")
    with pytest.raises(BrokerConfigError, match="outside its public scope"):
        load_policy(policy_path)

    policy_path.write_text(
        content.replace("8.8.8.8", "attacker.example.com"),
        encoding="utf-8",
    )
    with pytest.raises(BrokerConfigError, match="must be numeric"):
        load_policy(policy_path)


def test_broker_accepts_rfc1918_only_with_explicit_curated_scope(
    tmp_path: Path,
) -> None:
    destination = PluginEgressDestination.parse("https://openai-e2e:8443")
    plan = PluginEgressBrokerPlan.from_resolved(
        broker_image=_BROKER_IMAGE,
        sandbox_key_sha256="b" * 64,
        destinations=(
            ResolvedPluginEgressDestination(
                destination,
                (ip_address("172.18.0.5"),),
                PluginEgressAddressScope.CURATED_RFC1918,
            ),
        ),
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(plan.canonical_json_bytes())

    policy = load_policy(policy_path)

    assert policy.http_destinations[0].connect_addresses == (ip_address("172.18.0.5"),)
    assert policy.http_destinations[0].address_scope == "curated-rfc1918"

    content = policy_path.read_text(encoding="utf-8")
    policy_path.write_text(
        content.replace("curated-rfc1918", "public"),
        encoding="utf-8",
    )
    with pytest.raises(BrokerConfigError, match="outside its public scope"):
        load_policy(policy_path)


@pytest.mark.asyncio
async def test_http_proxy_rewrites_host_and_strips_proxy_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _write_policy(
        tmp_path / "policy.json",
        ("http://api.example.com:80", "93.184.216.34"),
    )
    observed = b""

    async def upstream(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        nonlocal observed
        # The broker no longer half-closes the request side (origins treat
        # an early FIN as an aborted request), so read this bodyless request
        # through its HTTP header terminator instead of waiting for EOF.
        observed = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"),
            timeout=5,
        )
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = cast(tuple[str, int], upstream_server.sockets[0].getsockname())[1]

    async def open_local(
        destination: BrokerDestination,
        timeout: int,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        del destination, timeout
        return await asyncio.open_connection("127.0.0.1", upstream_port)

    monkeypatch.setattr(plugin_egress_broker, "_open_numeric_connection", open_local)
    proxy_server = await asyncio.start_server(
        lambda reader, writer: _http_connection(reader, writer, policy),
        "127.0.0.1",
        0,
    )
    proxy_port = cast(tuple[str, int], proxy_server.sockets[0].getsockname())[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(
            b"GET http://api.example.com:80/v1/items?q=1 HTTP/1.1\r\n"
            b"Host: attacker.example\r\n"
            b"Proxy-Authorization: Basic sensitive\r\n\r\n"
        )
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
    finally:
        proxy_server.close()
        upstream_server.close()
        await proxy_server.wait_closed()
        await upstream_server.wait_closed()

    assert response.endswith(b"ok")
    assert observed.startswith(b"GET /v1/items?q=1 HTTP/1.1\r\n")
    assert b"Host: api.example.com\r\n" in observed
    assert b"attacker.example" not in observed
    assert b"sensitive" not in observed


@pytest.mark.asyncio
async def test_https_connect_is_end_to_end_to_the_authorized_numeric_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _write_policy(
        tmp_path / "policy.json",
        ("https://secure.example.com:443", "8.8.8.8"),
    )

    async def echo(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        writer.write(await reader.readexactly(4))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream_server = await asyncio.start_server(echo, "127.0.0.1", 0)
    upstream_port = cast(tuple[str, int], upstream_server.sockets[0].getsockname())[1]

    async def open_local(
        destination: BrokerDestination,
        timeout: int,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        assert destination.host == "secure.example.com"
        assert tuple(str(address) for address in destination.connect_addresses) == (
            "8.8.8.8",
        )
        del timeout
        return await asyncio.open_connection("127.0.0.1", upstream_port)

    monkeypatch.setattr(plugin_egress_broker, "_open_numeric_connection", open_local)
    proxy_server = await asyncio.start_server(
        lambda reader, writer: _http_connection(reader, writer, policy),
        "127.0.0.1",
        0,
    )
    proxy_port = cast(tuple[str, int], proxy_server.sockets[0].getsockname())[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(
            b"CONNECT secure.example.com:443 HTTP/1.1\r\n"
            b"Host: secure.example.com:443\r\n\r\n"
        )
        await writer.drain()
        response_headers = await reader.readuntil(b"\r\n\r\n")
        writer.write(b"ping")
        await writer.drain()
        echoed = await reader.readexactly(4)
        writer.close()
        await writer.wait_closed()
    finally:
        proxy_server.close()
        upstream_server.close()
        await proxy_server.wait_closed()
        await upstream_server.wait_closed()

    assert response_headers.startswith(b"HTTP/1.1 200")
    assert echoed == b"ping"


@pytest.mark.asyncio
async def test_postgresql_is_a_destination_specific_raw_tcp_relay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _write_policy(
        tmp_path / "policy.json",
        ("postgresql://database.example.com:5432", "1.1.1.1"),
    )
    destination = policy.postgresql_relays[0]

    async def echo(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        writer.write(await reader.readexactly(8))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream_server = await asyncio.start_server(echo, "127.0.0.1", 0)
    upstream_port = cast(tuple[str, int], upstream_server.sockets[0].getsockname())[1]

    async def open_local(
        selected: BrokerDestination,
        timeout: int,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        assert selected == destination
        del timeout
        return await asyncio.open_connection("127.0.0.1", upstream_port)

    monkeypatch.setattr(plugin_egress_broker, "_open_numeric_connection", open_local)
    relay_server = await asyncio.start_server(
        lambda reader, writer: _postgresql_connection(
            reader, writer, policy, destination
        ),
        "127.0.0.1",
        0,
    )
    relay_port = cast(tuple[str, int], relay_server.sockets[0].getsockname())[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
        ssl_request = b"\x00\x00\x00\x08\x04\xd2\x16\x2f"
        writer.write(ssl_request)
        await writer.drain()
        echoed = await reader.readexactly(8)
        writer.close()
        await writer.wait_closed()
    finally:
        relay_server.close()
        upstream_server.close()
        await relay_server.wait_closed()
        await upstream_server.wait_closed()

    assert destination.listen_port == destination.port == 5432
    assert echoed == ssl_request


@pytest.mark.asyncio
async def test_numeric_connector_forbids_dns_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def open_connection(
        host: str,
        port: int,
        **kwargs: object,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        observed.update(host=host, port=port, **kwargs)
        raise OSError("test stop")

    def forbidden_dns(*_args: object, **_kwargs: object) -> object:
        pytest.fail("numeric broker connection must not invoke DNS")

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_dns)
    destination = BrokerDestination(
        protocol="https",
        host="secure.example.com",
        port=443,
        connect_addresses=(cast(IPv4Address, ip_address("8.8.8.8")),),
    )

    with pytest.raises(OSError, match="No authorized numeric"):
        await plugin_egress_broker._open_numeric_connection(  # pyright: ignore[reportPrivateUsage]
            destination,
            1,
        )

    assert observed == {
        "host": "8.8.8.8",
        "port": 443,
        "family": socket.AF_INET,
        "flags": socket.AI_NUMERICHOST,
    }


@pytest.mark.parametrize(
    ("arguments", "environment", "returncode", "message"),
    [
        (["--help"], {}, 0, "serve,ready"),
        (
            ["serve", "--policy-env", "BROKER_TEST_POLICY"],
            {"BROKER_TEST_POLICY": "!"},
            1,
            "not valid base64",
        ),
        (
            ["ready", "--policy-sha256", "invalid"],
            {},
            1,
            "Expected policy digest is invalid",
        ),
    ],
)
def test_broker_commands_run_without_site_packages(
    arguments: list[str],
    environment: dict[str, str],
    returncode: int,
    message: str,
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(Path(plugin_egress_broker.__file__).resolve()),
            *arguments,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == returncode
    assert message in result.stdout + result.stderr
