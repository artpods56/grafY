from ipaddress import ip_address
import json
import socket

import pytest

from grafy_api.plugins.runtime.egress import (
    PluginEgressAddressScope,
    PluginEgressBrokerPolicy,
    PluginEgressBrokerPlan,
    PluginEgressDestination,
    PluginEgressProtocol,
    ResolvedPluginEgressDestination,
    resolve_public_destination,
    resolve_plugin_egress_destination,
)
from grafy_api.plugins.runtime.admission import (
    PluginNetworkEgressPolicy,
    PluginPostgresqlEgressPolicy,
)


def test_egress_destination_is_exact_and_broker_image_is_digest_pinned() -> None:
    destination = PluginEgressDestination.parse("https://API.Example.com:443")
    policy = PluginEgressBrokerPolicy(
        broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
        destinations=(destination,),
    )

    assert destination == PluginEgressDestination(
        protocol=PluginEgressProtocol.HTTPS,
        host="api.example.com",
        port=443,
    )
    assert policy.available is True
    assert PluginNetworkEgressPolicy(broker=policy).available is False
    assert PluginPostgresqlEgressPolicy(broker=policy).available is False


def test_http_egress_admission_requires_the_real_pinned_proxy_adapter() -> None:
    destination = PluginEgressDestination.parse("https://api.example.com:443")
    unavailable = PluginNetworkEgressPolicy(proxy_adapter_available=True)
    available = PluginNetworkEgressPolicy(
        proxy_adapter_available=True,
        broker=PluginEgressBrokerPolicy(
            broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
            destinations=(destination,),
        ),
    )

    assert unavailable.available is False
    assert available.available is True


@pytest.mark.parametrize(
    "value",
    [
        "https://localhost:443",
        "https://127.0.0.1:443",
        "https://169.254.169.254:443",
        "https://10.0.0.1:443",
        "https://*.example.com:443",
        "https://example.com:443/path",
        "https://user:password@example.com:443",
    ],
)
def test_egress_destination_rejects_ambient_or_widened_authority(value: str) -> None:
    with pytest.raises(ValueError):
        PluginEgressDestination.parse(value)


def test_egress_broker_cannot_be_enabled_with_mutable_image() -> None:
    destination = PluginEgressDestination.parse("https://api.example.com:443")

    with pytest.raises(ValueError, match="pinned by sha256"):
        PluginEgressBrokerPolicy(
            broker_image="registry.example/grafy-egress:latest",
            destinations=(destination,),
        )


@pytest.mark.asyncio
async def test_dns_rebinding_fails_closed_when_any_answer_is_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = PluginEgressDestination.parse("https://api.example.com:443")

    def mixed_answers(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed_answers)

    with pytest.raises(PermissionError, match="explicit public scope"):
        await resolve_public_destination(destination)


@pytest.mark.asyncio
async def test_dns_resolution_returns_only_numeric_public_connect_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = PluginEgressDestination.parse("https://api.example.com:443")

    def public_answer(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", public_answer)

    resolved = await resolve_public_destination(destination)

    assert tuple(str(address) for address in resolved.addresses) == (
        "93.184.216.34",
    )


@pytest.mark.asyncio
async def test_exact_curated_destination_may_resolve_to_rfc1918(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = PluginEgressDestination.parse("https://openai-e2e:8443")

    def private_answer(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.18.0.5", 8443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", private_answer)

    resolved = await resolve_plugin_egress_destination(
        destination,
        address_scope=PluginEgressAddressScope.CURATED_RFC1918,
    )

    assert resolved.address_scope is PluginEgressAddressScope.CURATED_RFC1918
    assert tuple(str(address) for address in resolved.addresses) == ("172.18.0.5",)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "169.254.1.1",
        "224.0.0.1",
        "0.0.0.0",
        "100.64.0.1",
        "::1",
        "fd00::1",
    ],
)
@pytest.mark.asyncio
async def test_curated_rfc1918_scope_rejects_other_non_public_addresses(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    destination = PluginEgressDestination.parse("https://openai-e2e:8443")

    def unsafe_answer(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, 8443))]

    monkeypatch.setattr(socket, "getaddrinfo", unsafe_answer)

    with pytest.raises(PermissionError, match="curated-rfc1918 scope"):
        await resolve_plugin_egress_destination(
            destination,
            address_scope=PluginEgressAddressScope.CURATED_RFC1918,
        )


def test_broker_plan_is_non_secret_numeric_and_separated_by_sandbox_key() -> None:
    http = PluginEgressDestination.parse("https://api.example.com:443")
    postgresql = PluginEgressDestination.parse(
        "postgresql://database.example.com:5432"
    )
    resolved = (
        ResolvedPluginEgressDestination(http, (ip_address("93.184.216.34"),)),
        ResolvedPluginEgressDestination(postgresql, (ip_address("8.8.8.8"),)),
    )
    first = PluginEgressBrokerPlan.from_resolved(
        broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
        sandbox_key_sha256="b" * 64,
        destinations=resolved,
    )
    second = PluginEgressBrokerPlan.from_resolved(
        broker_image=first.broker_image,
        sandbox_key_sha256="c" * 64,
        destinations=resolved,
    )

    document = json.loads(first.canonical_json_bytes())

    assert document["config_version"] == 2
    assert document["identity"] == {
        "mode": "dedicated-internal-network",
        "sandbox_key_sha256": "b" * 64,
    }
    assert document["http_proxy"] == {
        "listen_port": 3128,
        "destinations": [
                {
                    "protocol": "https",
                    "host": "api.example.com",
                    "port": 443,
                    "address_scope": "public",
                    "connect_addresses": ["93.184.216.34"],
            }
        ],
        "dns_resolution": "forbidden",
        "https_mode": "connect-tunnel",
    }
    assert document["postgresql_relays"] == [
        {
            "protocol": "postgresql",
            "host": "database.example.com",
            "port": 5432,
            "address_scope": "public",
            "connect_addresses": ["8.8.8.8"],
            "listen_port": 5432,
        }
    ]
    assert "password" not in first.canonical_json_bytes().decode("utf-8")
    assert first.policy_sha256 != second.policy_sha256


def test_postgresql_relay_requires_the_exact_declared_destination() -> None:
    destination = PluginEgressDestination.parse(
        "postgresql://database.example.com:5432"
    )
    plan = PluginEgressBrokerPlan.from_resolved(
        broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
        sandbox_key_sha256="b" * 64,
        destinations=(
            ResolvedPluginEgressDestination(
                destination,
                (ip_address("8.8.8.8"),),
            ),
        ),
    )

    assert plan.postgresql_relay_for(
        host="database.example.com",
        port=5432,
    ).listen_port == 5432
    with pytest.raises(PermissionError, match="not in the deployment"):
        plan.postgresql_relay_for(host="other.example.com", port=5432)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "https://API.Example.com/v1?token=secret#frag",
            ("https", "api.example.com", 443),
        ),
        ("http://Backup.EXAMPLE.com./", ("http", "backup.example.com", 80)),
        ("https://xn--nxasmq6b.example:8443", ("https", "xn--nxasmq6b.example", 8443)),
        ("https://provider.example:443", ("https", "provider.example", 443)),
    ],
)
def test_config_url_normalization_discards_authority_free_parts(
    value: str,
    expected: tuple[str, str, int],
) -> None:
    destination = PluginEgressDestination.from_config_url(value)

    assert (
        destination.protocol.value,
        destination.host,
        destination.port,
    ) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://user:pass@example.com:443",
        "https://127.0.0.1:443",
        "https://2001:db8::1:443",
        "https://localhost:443",
        "https://api.localhost:443",
        "https://*.example.com:443",
        "ftp://example.com:21",
        "example.com:443",
        "https://:443",
        "https://example.com:0",
        "https://example.com:65536",
        "https://-bad.example.com:443",
        " https://example.com:443",
        "",
    ],
)
def test_config_url_rejects_values_that_widen_or_evade_authority(value: str) -> None:
    with pytest.raises(ValueError):
        PluginEgressDestination.from_config_url(value)
