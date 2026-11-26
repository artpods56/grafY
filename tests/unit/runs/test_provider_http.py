"""The pooled provider client and the retry policy the OCR families share."""

import json

import httpx
import pytest
from pydantic import SecretStr

from grafy_core.egress import EgressRejectedError
from grafy_core.node_context import UserFacingNodeError
from grafy_core.provider_http import (
    ProviderRequest,
    aclose_provider_clients,
    post_json,
    provider_client,
    serve_client,
)

CRAFT = "https://ai-test.ihpan.edu.pl/v1/ocr/craft/detect"
CYRILLIC = "https://ai-test.ihpan.edu.pl/v1/ocr/cyrillic/recognize"


def _request(
    *,
    attempts: int = 3,
    timeout_seconds: float = 30.0,
    max_response_bytes: int = 1024,
) -> ProviderRequest:
    return ProviderRequest(
        service="CRAFT",
        url=CRAFT,
        payload={"image_base64": "AAA="},
        api_key=SecretStr("scoped-test"),
        attempts=attempts,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


async def test_one_provider_is_dialed_through_one_client_per_event_loop() -> None:
    first = provider_client(CRAFT)
    try:
        assert provider_client(CRAFT) is first
        assert provider_client(CYRILLIC) is first  # same origin, shared connections
        assert provider_client("https://other.example/v1/detect") is not first
    finally:
        await aclose_provider_clients()
    assert provider_client(CRAFT) is not first
    await aclose_provider_clients()


async def test_a_window_the_provider_never_answered_is_tried_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("no answer", request=httpx.Request("POST", CRAFT))
        return httpx.Response(200, json={"polygons": []})

    delays: list[float] = []

    async def record(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("grafy_core.provider_http.sleep", record)
    with serve_client(httpx.AsyncClient(transport=httpx.MockTransport(respond))):
        assert json.loads(await post_json(_request())) == {"polygons": []}
    assert calls == 3
    assert delays[0] <= delays[1]


async def test_a_refusal_is_logged_without_the_key_and_not_shown_to_the_user(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(400, text="image too small, key scoped-test")

    with (
        serve_client(httpx.AsyncClient(transport=httpx.MockTransport(refuse))),
        pytest.raises(UserFacingNodeError) as error,
    ):
        await post_json(_request())

    assert str(error.value) == "CRAFT returned HTTP 400"
    assert "status=400 reply='image too small, key <redacted>'" in caplog.text
    assert "scoped-test" not in caplog.text


async def test_attempts_run_out_on_an_http_status_and_on_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_wait(_delay: float) -> None:
        return None

    monkeypatch.setattr("grafy_core.provider_http.sleep", no_wait)

    def always_503(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    with (
        serve_client(httpx.AsyncClient(transport=httpx.MockTransport(always_503))),
        pytest.raises(UserFacingNodeError, match="CRAFT returned HTTP 503"),
    ):
        await post_json(_request())

    calls = 0

    def always_refuses(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection refused")

    with (
        serve_client(httpx.AsyncClient(transport=httpx.MockTransport(always_refuses))),
        pytest.raises(UserFacingNodeError, match="Could not reach CRAFT"),
    ):
        await post_json(_request(attempts=2))
    assert calls == 2


async def test_a_destination_the_deployment_refuses_is_not_tried_again() -> None:
    calls = 0

    def refuse(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        raise EgressRejectedError("host resolved to non-public address 10.0.0.8")

    with (
        serve_client(httpx.AsyncClient(transport=httpx.MockTransport(refuse))),
        pytest.raises(
            UserFacingNodeError, match="CRAFT may not be dialed by this deployment"
        ),
    ):
        await post_json(_request())
    assert calls == 1


async def test_a_response_over_the_limit_is_reported() -> None:
    with (
        serve_client(
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, content=b"x" * 64, request=request
                    )
                )
            )
        ),
        pytest.raises(UserFacingNodeError, match="exceeds the size limit"),
    ):
        await post_json(_request(max_response_bytes=16))
