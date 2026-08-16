import asyncio
from hashlib import sha256
import hmac
import re
from time import time
from uuid import UUID

from fastapi import FastAPI, Request, Response
from pydantic import ValidationError
from starlette.responses import PlainTextResponse

from grafy_agent.errors import AgentRuntimeError, SandboxOperationError, terminal_error
from grafy_core.ports.generated_execution import (
    GENERATED_EXECUTION_REQUEST_ID_HEADER,
    GENERATED_EXECUTION_SIGNATURE_HEADER,
    GENERATED_EXECUTION_TIMESTAMP_HEADER,
    GeneratedNodeExecutionFailure,
    GeneratedNodeExecutionRequest,
    GeneratedReleaseExecutorPort,
    generated_execution_signature_payload,
)


class ExecutionRequestAuthenticator:
    """Verify one HMAC request and reject its request id on replay."""

    def __init__(
        self,
        secret: bytes,
        *,
        skew_seconds: int,
        replay_cache_entries: int,
    ) -> None:
        if len(secret) < 32:
            raise ValueError(
                "Generated execution HMAC secret must be at least 32 bytes"
            )
        self._secret = secret
        self._skew_seconds = skew_seconds
        self._replay_cache_entries = replay_cache_entries
        self._seen: dict[UUID, int] = {}
        self._lock = asyncio.Lock()

    async def verify(
        self,
        *,
        timestamp_text: str,
        request_id_text: str,
        signature: str,
        body: bytes,
    ) -> tuple[int, UUID]:
        try:
            timestamp = int(timestamp_text)
            request_id = UUID(request_id_text)
        except (ValueError, TypeError) as exc:
            raise PermissionError(
                "Invalid generated execution signing headers"
            ) from exc
        now = int(time())
        if abs(now - timestamp) > self._skew_seconds:
            raise PermissionError("Generated execution signature timestamp is stale")
        if re.fullmatch(r"[0-9a-f]{64}", signature) is None:
            raise PermissionError("Invalid generated execution signature encoding")
        payload = generated_execution_signature_payload(
            direction="request",
            timestamp=timestamp,
            request_id=request_id,
            body=body,
        )
        expected = hmac.new(self._secret, payload, sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("Generated execution signature does not match")
        async with self._lock:
            expired_before = now - self._skew_seconds
            self._seen = {
                seen_id: seen_at
                for seen_id, seen_at in self._seen.items()
                if seen_at >= expired_before
            }
            if request_id in self._seen:
                raise PermissionError("Generated execution request was replayed")
            if len(self._seen) >= self._replay_cache_entries:
                raise PermissionError("Generated execution replay cache is full")
            self._seen[request_id] = timestamp
        return timestamp, request_id

    def sign_response(
        self,
        *,
        request_id: UUID,
        body: bytes,
        status_code: int,
    ) -> tuple[int, str]:
        timestamp = int(time())
        payload = generated_execution_signature_payload(
            direction="response",
            timestamp=timestamp,
            request_id=request_id,
            body=body,
            status_code=status_code,
        )
        signature = hmac.new(self._secret, payload, sha256).hexdigest()
        return timestamp, signature


class _ExecutionAdmissionSemaphore:
    """Bound active executions and the requests allowed to wait for a slot."""

    def __init__(
        self,
        *,
        max_concurrent_executions: int,
        max_queued_executions: int,
        timeout_seconds: float,
    ) -> None:
        if max_concurrent_executions < 1:
            raise ValueError("Executor concurrency must be at least one")
        if max_queued_executions < 0:
            raise ValueError("Executor queue size must not be negative")
        if timeout_seconds <= 0:
            raise ValueError("Executor admission timeout must be positive")
        self._semaphore = asyncio.Semaphore(max_concurrent_executions)
        self._reservation_limit = max_concurrent_executions + max_queued_executions
        self._timeout_seconds = timeout_seconds
        self._reservations = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            if self._reservations >= self._reservation_limit:
                return False
            self._reservations += 1
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            async with self._lock:
                self._reservations -= 1
            return False
        except BaseException:
            async with self._lock:
                self._reservations -= 1
            raise
        return True

    async def release(self) -> None:
        async with self._lock:
            if self._reservations < 1:
                raise RuntimeError("Executor admission semaphore was over-released")
            self._reservations -= 1
            self._semaphore.release()


def create_execution_app(
    *,
    executor: GeneratedReleaseExecutorPort,
    authenticator: ExecutionRequestAuthenticator,
    max_request_bytes: int,
    max_concurrent_executions: int = 4,
    max_queued_executions: int = 16,
    admission_timeout_seconds: float = 2.0,
) -> FastAPI:
    admission = _ExecutionAdmissionSemaphore(
        max_concurrent_executions=max_concurrent_executions,
        max_queued_executions=max_queued_executions,
        timeout_seconds=admission_timeout_seconds,
    )
    app = FastAPI(
        title="Grafy generated-node executor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health", response_class=PlainTextResponse)
    async def health() -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        return PlainTextResponse("ok")

    @app.post("/v1/generated-node-executions")
    async def execute_generated_node(  # pyright: ignore[reportUnusedFunction]
        request: Request,
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                return Response(status_code=400)
            if declared_length < 1 or declared_length > max_request_bytes:
                return Response(status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_request_bytes:
                return Response(status_code=413)
        raw_body = bytes(body)
        try:
            _, signed_request_id = await authenticator.verify(
                timestamp_text=(
                    request.headers.get(GENERATED_EXECUTION_TIMESTAMP_HEADER) or ""
                ),
                request_id_text=(
                    request.headers.get(GENERATED_EXECUTION_REQUEST_ID_HEADER) or ""
                ),
                signature=(
                    request.headers.get(GENERATED_EXECUTION_SIGNATURE_HEADER) or ""
                ),
                body=raw_body,
            )
        except PermissionError:
            return Response(status_code=401)

        try:
            execution_request = GeneratedNodeExecutionRequest.model_validate_json(
                raw_body
            )
            if execution_request.request_id != signed_request_id:
                raise ValueError("Signed request id does not match request body")
            if execution_request.canonical_json_bytes() != raw_body:
                raise ValueError("Generated execution request body is not canonical")
        except (ValidationError, ValueError) as exc:
            failure = GeneratedNodeExecutionFailure(
                request_id=signed_request_id,
                error_code="invalid_request",
                message=terminal_error("Generated execution request validation", exc),
                retryable=False,
            )
            return _signed_response(
                failure.canonical_json_bytes(),
                status_code=400,
                request_id=signed_request_id,
                authenticator=authenticator,
            )

        admitted = await admission.acquire()
        if not admitted:
            failure = GeneratedNodeExecutionFailure(
                request_id=signed_request_id,
                error_code="executor_busy",
                message="Generated node executor admission capacity is exhausted",
                retryable=True,
            )
            return _signed_response(
                failure.canonical_json_bytes(),
                status_code=503,
                request_id=signed_request_id,
                authenticator=authenticator,
            )

        try:
            try:
                result = await executor.execute(execution_request)
            except SandboxOperationError as exc:
                failure = GeneratedNodeExecutionFailure(
                    request_id=signed_request_id,
                    error_code="sandbox_unavailable",
                    message=terminal_error("Generated node sandbox execution", exc),
                    retryable=True,
                )
                return _signed_response(
                    failure.canonical_json_bytes(),
                    status_code=503,
                    request_id=signed_request_id,
                    authenticator=authenticator,
                )
            except AgentRuntimeError as exc:
                failure = GeneratedNodeExecutionFailure(
                    request_id=signed_request_id,
                    error_code="execution_rejected",
                    message=terminal_error("Generated node execution", exc),
                    retryable=False,
                )
                return _signed_response(
                    failure.canonical_json_bytes(),
                    status_code=422,
                    request_id=signed_request_id,
                    authenticator=authenticator,
                )
            except Exception as exc:
                failure = GeneratedNodeExecutionFailure(
                    request_id=signed_request_id,
                    error_code="executor_failure",
                    message=terminal_error("Generated node executor", exc),
                    retryable=True,
                )
                return _signed_response(
                    failure.canonical_json_bytes(),
                    status_code=500,
                    request_id=signed_request_id,
                    authenticator=authenticator,
                )
            return _signed_response(
                result.canonical_json_bytes(),
                status_code=200,
                request_id=signed_request_id,
                authenticator=authenticator,
            )
        finally:
            await admission.release()

    return app


def _signed_response(
    body: bytes,
    *,
    status_code: int,
    request_id: UUID,
    authenticator: ExecutionRequestAuthenticator,
) -> Response:
    timestamp, signature = authenticator.sign_response(
        request_id=request_id,
        body=body,
        status_code=status_code,
    )
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/json",
        headers={
            GENERATED_EXECUTION_TIMESTAMP_HEADER: str(timestamp),
            GENERATED_EXECUTION_REQUEST_ID_HEADER: str(request_id),
            GENERATED_EXECUTION_SIGNATURE_HEADER: signature,
        },
    )


__all__ = ["ExecutionRequestAuthenticator", "create_execution_app"]
