import logging
import traceback
from collections.abc import Iterator, Mapping
from types import TracebackType
from typing import cast
from uuid import UUID

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
import pytest

from grafy_api.logging_setup import configure_logging
from grafy_api.http_errors import register_http_error_handlers
from grafy_core.domain.errors import NotFoundError


_PRIVATE_IDENTIFIER = "private-resource-4cc5ae31"
_UNEXPECTED_SENTINEL = "unexpected-secret-98d58c37"


class _ValidatedRequest(BaseModel):
    count: int = Field(ge=1)


@pytest.fixture
def error_client() -> Iterator[TestClient]:
    configure_logging(level="INFO", renderer="json")
    app = FastAPI()

    @app.get("/typed")
    async def typed_failure() -> None:  # pyright: ignore[reportUnusedFunction]
        raise NotFoundError("Private resource", _PRIVATE_IDENTIFIER)

    @app.get("/unexpected")
    async def unexpected_failure() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError(_UNEXPECTED_SENTINEL)

    @app.get("/legacy-500")
    async def legacy_internal_failure() -> None:  # pyright: ignore[reportUnusedFunction]
        raise HTTPException(status_code=500, detail=_UNEXPECTED_SENTINEL)

    @app.get("/unavailable")
    async def unavailable_failure() -> None:  # pyright: ignore[reportUnusedFunction]
        try:
            raise ConnectionError(_UNEXPECTED_SENTINEL)
        except ConnectionError as exception:
            raise HTTPException(status_code=503, detail="legacy detail") from exception

    @app.get("/legacy-404")
    async def legacy_not_found() -> None:  # pyright: ignore[reportUnusedFunction]
        raise HTTPException(status_code=404, detail="Explicit public detail")

    @app.post("/validated")
    async def validate_request(  # pyright: ignore[reportUnusedFunction]
        _body: _ValidatedRequest,
    ) -> None:
        return None

    register_http_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://app.example"],
    )
    with TestClient(app) as client:
        yield client


def _event_records(
    caplog: pytest.LogCaptureFixture,
    event: str,
) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for record in caplog.records:
        raw_message = cast(  # pyright: ignore[reportUnknownMemberType]
            object,
            record.msg,
        )
        if not isinstance(raw_message, Mapping):
            continue
        message = cast(Mapping[str, object], raw_message)
        if message.get("event") == event:
            records.append(message)
    return records


def test_typed_failure_exposes_only_the_declared_contract(
    error_client: TestClient,
) -> None:
    response = error_client.get("/typed")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Not found",
        "code": "resource.not_found",
        "error_id": response.json()["error_id"],
    }
    UUID(response.json()["error_id"])
    UUID(response.headers["X-Request-ID"])
    assert _PRIVATE_IDENTIFIER not in response.text


def test_unexpected_failure_propagates(error_client: TestClient) -> None:
    with pytest.raises(RuntimeError, match=_UNEXPECTED_SENTINEL):
        error_client.get("/unexpected")


def test_internal_http_error_keeps_its_message(error_client: TestClient) -> None:
    response = error_client.get("/legacy-500")
    assert response.status_code == 500
    assert response.json() == {"detail": _UNEXPECTED_SENTINEL}


def test_unavailable_failure_logs_original_cause(
    error_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = error_client.get("/unavailable")
    assert response.status_code == 503
    assert response.json() == {"detail": "legacy detail"}
    event = _event_records(caplog, "http_request_failed")[-1]
    exc_info = cast(
        tuple[type[BaseException], BaseException, TracebackType | None],
        event["exc_info"],
    )
    output = "".join(traceback.format_exception(*exc_info))
    assert "ConnectionError: " + _UNEXPECTED_SENTINEL in output
    assert "The above exception was the direct cause" in output


def test_legacy_client_error_keeps_its_contract_without_phantom_error_id(
    error_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    response = error_client.get("/legacy-404")

    assert response.status_code == 404
    assert response.json() == {"detail": "Explicit public detail"}
    assert not _event_records(caplog, "operation_rejected")


def test_validation_redacts_input_and_context(
    error_client: TestClient,
) -> None:
    response = error_client.post("/validated", json={"count": 0})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "request.validation_failed"
    UUID(body["error_id"])
    assert body["detail"]
    assert all("input" not in error and "ctx" not in error for error in body["detail"])


def test_request_context_is_distinct_for_each_request(
    error_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    first = error_client.get("/typed")
    second = error_client.get("/typed")
    structlog.get_logger("test.after_request").info("outside_request")

    first_request_id = first.headers["X-Request-ID"]
    second_request_id = second.headers["X-Request-ID"]
    assert first_request_id != second_request_id
    completions = _event_records(caplog, "http_request_completed")
    request_ids = {
        event.get("request_id")
        for event in completions
        if event.get("route") == "/typed"
    }
    assert {first_request_id, second_request_id} <= request_ids
    outside = _event_records(caplog, "outside_request")
    assert outside
    assert "request_id" not in outside[-1]
