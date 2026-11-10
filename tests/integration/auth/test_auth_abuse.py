from types import SimpleNamespace
from typing import cast
from uuid import UUID

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp
from uvicorn._types import ASGI3Application
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from grafy_api.auth.abuse import (
    AuthAbuseControl,
    make_browser_abuse_cookie,
    request_browser_keys,
)


async def test_abuse_windows_and_outstanding_logins_are_deterministic() -> None:
    current = 100.0

    def clock() -> float:
        return current

    abuse = AuthAbuseControl(
        window_seconds=10,
        login_start_limit=2,
        callback_limit=1,
        session_failure_limit=1,
        pat_creation_limit=1,
        outstanding_login_limit=2,
        outstanding_login_ttl_seconds=20,
        clock=clock,
    )

    first_transaction = UUID(int=1)
    second_transaction = UUID(int=2)
    third_transaction = UUID(int=3)
    assert await abuse.allow_login_start("browser")
    assert await abuse.allow_login_start("browser")
    assert not await abuse.allow_login_start("browser")
    assert await abuse.reserve_login("browser", first_transaction)
    assert await abuse.reserve_login("browser", second_transaction)
    assert not await abuse.reserve_login("browser", third_transaction)

    current += 10
    assert await abuse.allow_login_start("browser")
    assert await abuse.allow_callback("browser")
    assert not await abuse.allow_callback("browser")
    await abuse.release_login(first_transaction)
    assert await abuse.reserve_login("browser", third_transaction)

    current += 20
    assert await abuse.reserve_login("browser", UUID(int=4))
    assert await abuse.allow_session_failure("browser")
    assert not await abuse.allow_session_failure("browser")


async def test_outstanding_login_capacity_preserves_existing_browser_count() -> None:
    abuse = AuthAbuseControl(outstanding_login_limit=2)

    assert await abuse.reserve_login("existing", UUID(int=1))
    for index in range(abuse._max_tracked_keys - 1):
        assert await abuse.reserve_login(f"browser-{index}", UUID(int=index + 2))

    assert await abuse.reserve_login("existing", UUID(int=10000))
    assert not await abuse.reserve_login("existing", UUID(int=10001))


async def test_outstanding_login_capacity_rejects_new_browser_key() -> None:
    abuse = AuthAbuseControl(outstanding_login_limit=2)

    for index in range(abuse._max_tracked_keys):
        assert await abuse.reserve_login(f"browser-{index}", UUID(int=index + 1))

    assert not await abuse.reserve_login("new-browser", UUID(int=10000))


async def test_reservations_expire_individually_and_release_by_transaction() -> None:
    current = 100.0

    def clock() -> float:
        return current

    abuse = AuthAbuseControl(
        outstanding_login_limit=2,
        outstanding_login_ttl_seconds=20,
        clock=clock,
    )
    first = UUID(int=1)
    second = UUID(int=2)
    third = UUID(int=3)

    assert await abuse.reserve_login("stable-browser", first)
    current += 10
    assert await abuse.reserve_login("stable-browser", second)
    current += 10
    assert await abuse.reserve_login("stable-browser", third)
    await abuse.release_login(second)
    assert await abuse.reserve_login("stable-browser", UUID(int=4))


async def test_network_backstop_handles_missing_forged_and_rotated_cookies() -> None:
    abuse = AuthAbuseControl(
        login_start_limit=1,
        outstanding_login_limit=1,
        network_outstanding_login_limit=2,
    )
    assert await abuse.allow_login_start("random-browser-one", "ip:one")
    assert not await abuse.allow_login_start("random-browser-two", "ip:one")
    assert not await abuse.allow_login_start("rotated-browser", "ip:one")

    transaction_id = UUID(int=10)
    assert await abuse.reserve_login("browser-one", transaction_id, "ip:one")
    assert await abuse.reserve_login("browser-two", UUID(int=11), "ip:one")
    assert not await abuse.reserve_login("rotated-browser", UUID(int=12), "ip:one")


async def test_browser_reservation_survives_ip_change_and_releases_by_transaction() -> (
    None
):
    abuse = AuthAbuseControl(outstanding_login_limit=1)
    transaction_id = UUID(int=12)
    assert await abuse.reserve_login("stable-browser", transaction_id, "ip:one")
    assert not await abuse.reserve_login("stable-browser", UUID(int=13), "ip:two")
    await abuse.release_login(transaction_id)
    assert await abuse.reserve_login("stable-browser", UUID(int=13), "ip:two")


def test_forged_browser_cookie_is_rejected_without_using_the_submitted_handle() -> None:
    secret = b"browser-cookie-secret"
    valid_cookie = make_browser_abuse_cookie("stable-browser", secret=secret)
    request = SimpleNamespace(
        state=SimpleNamespace(),
        cookies={"grafy_browser_abuse": valid_cookie[:-1] + "x"},
        client=SimpleNamespace(host="127.0.0.1"),
        url=SimpleNamespace(path="/v1/auth/oidc/login"),
    )
    keys = request_browser_keys(request, secret=secret)
    assert keys.browser_key != "stable-browser"
    assert keys.network_key == "ip:127.0.0.1"


@pytest.mark.parametrize(
    ("peer_host", "forwarded_for", "expected"),
    (
        ("198.51.100.8", "198.51.100.7", "198.51.100.8|ip:198.51.100.8"),
        (
            "172.30.0.1",
            "198.51.100.7, 172.30.0.1",
            "198.51.100.7|ip:198.51.100.7",
        ),
    ),
)
async def test_proxy_headers_bound_network_limiter_identity(
    peer_host: str,
    forwarded_for: str,
    expected: str,
) -> None:
    async def capture_identity(request: Request) -> PlainTextResponse:
        client = request.client
        assert client is not None
        keys = request_browser_keys(request, secret=b"test-secret")
        return PlainTextResponse(f"{client.host}|{keys.network_key}")

    application = cast(
        ASGIApp,
        ProxyHeadersMiddleware(
            cast(
                ASGI3Application,
                Starlette(routes=[Route("/v1/auth/oidc/login", capture_identity)]),
            ),
            trusted_hosts="172.30.0.1",
        ),
    )
    transport = httpx.ASGITransport(
        app=application,
        client=(peer_host, 40000),
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/v1/auth/oidc/login",
            headers={"X-Forwarded-For": forwarded_for},
        )

    assert response.text == expected
