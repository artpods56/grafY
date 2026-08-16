"""Signed HTTP adapter for isolated agent-authored node execution."""

import hmac
import time
from hashlib import sha256
from uuid import UUID

import httpx
from pydantic import ValidationError

from grafy_core.ports.generated_execution import (
    GENERATED_EXECUTION_REQUEST_ID_HEADER,
    GENERATED_EXECUTION_SIGNATURE_HEADER,
    GENERATED_EXECUTION_TIMESTAMP_HEADER,
    GeneratedNodeExecutionFailure,
    GeneratedNodeExecutionRequest,
    GeneratedNodeExecutionResult,
    generated_execution_signature_payload,
)


_EXECUTION_PATH = "/v1/generated-node-executions"
_MAX_CLOCK_SKEW_SECONDS = 30
_MAX_HTTP_BODY_BYTES = 67_108_864
_JSON_ENVELOPE_BYTES = 1_048_576


class GeneratedNodeExecutorError(RuntimeError):
    """The isolated execution worker could not return a trusted result."""


class GeneratedNodeRemoteExecutionError(GeneratedNodeExecutorError):
    def __init__(self, failure: GeneratedNodeExecutionFailure) -> None:
        self.error_code = failure.error_code
        self.retryable = failure.retryable
        super().__init__(
            f"Generated-node worker rejected request {failure.request_id}: "
            f"{failure.error_code}: {failure.message}"
        )


class UnavailableGeneratedReleaseExecutor:
    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        raise GeneratedNodeExecutorError(
            f"Generated node {request.node_id}@{request.revision} cannot execute "
            "because the isolated execution worker is not configured"
        )


class GeneratedNodeExecutorClient:
    """Calls one long-running worker; generated releases do not open servers."""

    def __init__(
        self,
        *,
        base_url: str,
        hmac_key: bytes,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if len(hmac_key) < 32:
            raise ValueError("Generated-node executor HMAC key must be at least 32 bytes")
        self._hmac_key = hmac_key
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        body = request.canonical_json_bytes()
        input_limit = min(
            request.build_document.capabilities.runtime.input_bytes
            + _JSON_ENVELOPE_BYTES,
            _MAX_HTTP_BODY_BYTES,
        )
        if len(body) > input_limit:
            raise GeneratedNodeExecutorError(
                f"Generated-node request {request.request_id} exceeds the "
                f"bounded HTTP input size of {input_limit} bytes"
            )
        timestamp = int(time.time())
        signature = hmac.new(
            self._hmac_key,
            generated_execution_signature_payload(
                direction="request",
                timestamp=timestamp,
                request_id=request.request_id,
                body=body,
            ),
            sha256,
        ).hexdigest()
        http_request = self._client.build_request(
            "POST",
            _EXECUTION_PATH,
            content=body,
            headers={
                "Content-Type": "application/json",
                GENERATED_EXECUTION_TIMESTAMP_HEADER: str(timestamp),
                GENERATED_EXECUTION_REQUEST_ID_HEADER: str(request.request_id),
                GENERATED_EXECUTION_SIGNATURE_HEADER: signature,
            },
        )
        try:
            response = await self._client.send(http_request, stream=True)
        except httpx.RequestError as exc:
            raise GeneratedNodeExecutorError(
                f"Generated-node worker request {request.request_id} failed "
                f"during {exc.__class__.__name__}"
            ) from exc

        output_limit = min(
            request.build_document.capabilities.runtime.output_bytes
            + _JSON_ENVELOPE_BYTES,
            _MAX_HTTP_BODY_BYTES,
        )
        response_body = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                if len(response_body) + len(chunk) > output_limit:
                    raise GeneratedNodeExecutorError(
                        f"Generated-node worker response for {request.request_id} "
                        f"exceeds {output_limit} bytes"
                    )
                response_body.extend(chunk)
        finally:
            await response.aclose()
        exact_body = bytes(response_body)
        self._verify_response_signature(
            response=response,
            request_id=request.request_id,
            body=exact_body,
        )

        if response.is_error:
            try:
                failure = GeneratedNodeExecutionFailure.model_validate_json(exact_body)
            except ValidationError as exc:
                raise GeneratedNodeExecutorError(
                    f"Generated-node worker returned signed HTTP {response.status_code} "
                    f"with an invalid error payload for request {request.request_id}"
                ) from exc
            if failure.request_id != request.request_id:
                raise GeneratedNodeExecutorError(
                    "Generated-node worker error payload has a mismatched request id"
                )
            raise GeneratedNodeRemoteExecutionError(failure)

        try:
            result = GeneratedNodeExecutionResult.model_validate_json(exact_body)
        except ValidationError as exc:
            raise GeneratedNodeExecutorError(
                f"Generated-node worker returned an invalid result payload for "
                f"request {request.request_id}"
            ) from exc
        if result.request_id != request.request_id:
            raise GeneratedNodeExecutorError(
                "Generated-node worker result has a mismatched request id"
            )
        return result

    def _verify_response_signature(
        self,
        *,
        response: httpx.Response,
        request_id: UUID,
        body: bytes,
    ) -> None:
        raw_timestamp = response.headers.get(GENERATED_EXECUTION_TIMESTAMP_HEADER)
        raw_request_id = response.headers.get(GENERATED_EXECUTION_REQUEST_ID_HEADER)
        received_signature = response.headers.get(
            GENERATED_EXECUTION_SIGNATURE_HEADER
        )
        try:
            timestamp = int(raw_timestamp or "")
            signed_request_id = UUID(raw_request_id or "")
        except ValueError as exc:
            raise GeneratedNodeExecutorError(
                "Generated-node worker response is missing valid signing metadata"
            ) from exc
        if signed_request_id != request_id:
            raise GeneratedNodeExecutorError(
                "Generated-node worker response signing id does not match the request"
            )
        if abs(int(time.time()) - timestamp) > _MAX_CLOCK_SKEW_SECONDS:
            raise GeneratedNodeExecutorError(
                "Generated-node worker response timestamp is outside the allowed skew"
            )
        if received_signature is None:
            raise GeneratedNodeExecutorError(
                "Generated-node worker response is missing its signature"
            )
        expected_signature = hmac.new(
            self._hmac_key,
            generated_execution_signature_payload(
                direction="response",
                timestamp=timestamp,
                request_id=request_id,
                body=body,
                status_code=response.status_code,
            ),
            sha256,
        ).hexdigest()
        if not hmac.compare_digest(received_signature, expected_signature):
            raise GeneratedNodeExecutorError(
                "Generated-node worker response signature is invalid"
            )


__all__ = [
    "GeneratedNodeExecutorClient",
    "GeneratedNodeExecutorError",
    "GeneratedNodeRemoteExecutionError",
    "UnavailableGeneratedReleaseExecutor",
]
