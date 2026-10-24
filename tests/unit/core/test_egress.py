import socket
from typing import Any

import httpx
import pytest
from pydantic import AnyHttpUrl, TypeAdapter

from grafy_core import egress as egress_module
from grafy_core.egress import (
    TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE,
    EgressPolicy,
    EgressRejectedError,
    PinnedPublicAddressTransport,
    dial_port,
    resolved_dial_addresses,
    validated_public_destination,
)

URL = TypeAdapter(AnyHttpUrl)


def public(name: str = "service.example.com") -> AnyHttpUrl:
    return URL.validate_python(f"https://{name}/ows")


def patch_answers(
    monkeypatch: pytest.MonkeyPatch,
    answers: list[str],
) -> list[tuple[str, int]]:
    asked: list[tuple[str, int]] = []

    async def fake_lookup(host: str, port: int, timeout_seconds: float) -> list[Any]:
        asked.append((host, port))
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in answers
        ]

    monkeypatch.setattr(egress_module, "_lookup", fake_lookup)
    return asked


def test_policy_parses_every_destination_shape() -> None:
    policy = EgressPolicy.from_destinations(
        [
            "db.internal",
            "API.Example.COM.:443",
            "[fd00::12]:8443",
            "10.0.0.0/8",
            "192.168.4.9",
            "",
        ]
    )

    assert policy.trusts_host("db.internal", 5432)
    assert policy.trusts_host("db.internal.", 5432)
    # A grant without a port is the whole host, because an operator naming an
    # internal database host does not re-list it for every port it serves.
    assert policy.trusts_host("db.internal", 6543)
    assert policy.trusts_host("api.example.com", 443)
    assert not policy.trusts_host("api.example.com", 80)
    assert policy.trusts_host("fd00::12", 8443)
    assert policy.trusts_host("192.168.4.9", 5432)
    assert policy.trusts_address("10.4.5.6")
    assert not policy.trusts_address("11.0.0.1")
    assert not policy.trusts_address("not-an-address")


@pytest.mark.parametrize(
    "entry",
    ["[fd00::1", "db.internal:abc", "db.internal:0", "db.internal:70000", ":5432"],
)
def test_policy_rejects_a_malformed_destination(entry: str) -> None:
    with pytest.raises(ValueError):
        EgressPolicy.from_destinations([entry])


def test_policy_reads_destinations_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE, '["db.internal:5432"]'
    )
    assert EgressPolicy.from_environment().trusts_host("db.internal", 5432)

    monkeypatch.setenv(TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE, "")
    assert not EgressPolicy.from_environment().trusts_host("db.internal", 5432)

    monkeypatch.setenv(TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE, "db.internal")
    with pytest.raises(ValueError, match="must be a JSON list"):
        EgressPolicy.from_environment()


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("https://user:pass@example.com/ows", "embedded credentials"),
        ("https://example.com/ows?service=WMS", "query-free service endpoint"),
        ("http://localhost:8080/ows", "must not target localhost"),
        ("http://svc.localhost/ows", "must not target localhost"),
        ("http://[::1]/ows", "must not target a private, loopback"),
        ("http://127.0.0.1/ows", "must not target a private, loopback"),
        ("http://169.254.169.254/ows", "must not target a private, loopback"),
        ("http://10.0.0.9/ows", "must not target a private, loopback"),
    ],
)
def test_public_destination_rules_reject_a_destination_that_cannot_be_public(
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validated_public_destination(URL.validate_python(value), service_name="WMS")


def test_public_destination_rules_accept_a_name_and_a_public_literal() -> None:
    named = validated_public_destination(public(), service_name="WMS")
    literal = validated_public_destination(
        URL.validate_python("https://93.184.216.34/ows"), service_name="WMS"
    )
    assert named.host == "service.example.com"
    assert literal.host == "93.184.216.34"


def test_dial_port_falls_back_to_the_scheme_default() -> None:
    assert dial_port(URL.validate_python("https://example.com/ows")) == 443
    assert dial_port(URL.validate_python("http://example.com/ows")) == 80
    assert dial_port(URL.validate_python("https://example.com:8443/ows")) == 8443


async def test_resolution_returns_the_global_answers_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = patch_answers(
        monkeypatch, ["93.184.216.34", "93.184.216.34", "93.184.216.35"]
    )

    addresses = await resolved_dial_addresses("Service.Example.com.", 443)

    assert addresses == ("93.184.216.34", "93.184.216.35")
    assert asked == [("service.example.com", 443)]


async def test_resolution_refuses_a_name_that_resolves_to_an_internal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_answers(monkeypatch, ["127.0.0.1"])
    with pytest.raises(EgressRejectedError, match="non-public address 127.0.0.1"):
        await resolved_dial_addresses("db.internal", 5432)


async def test_resolution_refuses_a_name_mixing_public_and_internal_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_answers(monkeypatch, ["93.184.216.34", "169.254.169.254"])
    with pytest.raises(EgressRejectedError, match="non-public address 169.254.169.254"):
        await resolved_dial_addresses("service.example.com", 443)


async def test_a_trusted_host_grant_skips_the_public_address_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_answers(monkeypatch, ["10.20.30.40"])
    policy = EgressPolicy.from_destinations(["db.internal"])

    addresses = await resolved_dial_addresses("db.internal", 5432, policy=policy)
    assert addresses == ("10.20.30.40",)

    with pytest.raises(EgressRejectedError, match="non-public address"):
        await resolved_dial_addresses(
            "db.internal",
            5433,
            policy=EgressPolicy.from_destinations(["db.internal:5432"]),
        )


async def test_a_network_grant_allows_only_addresses_inside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = EgressPolicy.from_destinations(["10.0.0.0/8"])
    patch_answers(monkeypatch, ["10.20.30.40"])
    assert await resolved_dial_addresses(
        "tenant-db.example.com", 5432, policy=policy
    ) == ("10.20.30.40",)

    patch_answers(monkeypatch, ["192.168.1.5"])
    with pytest.raises(EgressRejectedError, match="non-public address 192.168.1.5"):
        await resolved_dial_addresses("tenant-db.example.com", 5432, policy=policy)


async def test_resolution_refuses_a_host_that_does_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_lookup(host: str, port: int, timeout_seconds: float) -> list[Any]:
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(egress_module, "_lookup", failing_lookup)
    with pytest.raises(EgressRejectedError, match="did not resolve"):
        await resolved_dial_addresses("nowhere.example", 443)

    async def empty_lookup(host: str, port: int, timeout_seconds: float) -> list[Any]:
        return []

    monkeypatch.setattr(egress_module, "_lookup", empty_lookup)
    with pytest.raises(EgressRejectedError, match="resolved to no address"):
        await resolved_dial_addresses("nowhere.example", 443)


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, refuses: tuple[str, ...] = ()) -> None:
        self.refuses = refuses
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.raw_host.decode()
        self.requests.append((host, request.headers["host"], dict(request.extensions)))
        if host in self.refuses:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(204, request=request)

    async def aclose(self) -> None:
        self.closed = True


async def test_the_transport_dials_the_validated_address_and_keeps_the_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_answers(monkeypatch, ["93.184.216.34"])
    inner = RecordingTransport()

    response = await PinnedPublicAddressTransport(transport=inner).handle_async_request(
        httpx.Request("GET", "https://service.example.com:8443/ows")
    )

    assert response.status_code == 204
    assert inner.requests == [
        (
            "93.184.216.34",
            "service.example.com:8443",
            {"sni_hostname": "service.example.com"},
        )
    ]


async def test_the_transport_tries_the_next_validated_address_after_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_answers(monkeypatch, ["93.184.216.34", "93.184.216.35"])
    inner = RecordingTransport(refuses=("93.184.216.34",))

    await PinnedPublicAddressTransport(transport=inner).handle_async_request(
        httpx.Request("GET", "https://service.example.com/ows")
    )

    assert [host for host, _, _ in inner.requests] == [
        "93.184.216.34",
        "93.184.216.35",
    ]


async def test_the_transport_reports_the_last_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_answers(monkeypatch, ["93.184.216.34", "93.184.216.35"])
    inner = RecordingTransport(refuses=("93.184.216.34", "93.184.216.35"))

    with pytest.raises(httpx.ConnectError):
        await PinnedPublicAddressTransport(transport=inner).handle_async_request(
            httpx.Request("GET", "https://service.example.com/ows")
        )


async def test_the_transport_refuses_a_destination_it_cannot_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_answers(monkeypatch, ["10.0.0.9"])
    with pytest.raises(EgressRejectedError, match="non-public address"):
        await PinnedPublicAddressTransport(
            transport=RecordingTransport()
        ).handle_async_request(httpx.Request("GET", "http://minio.internal/bucket"))


async def test_the_transport_closes_the_transport_it_wraps() -> None:
    inner = RecordingTransport()
    await PinnedPublicAddressTransport(transport=inner).aclose()
    assert inner.closed
