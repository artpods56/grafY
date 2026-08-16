"""Execution boundary for immutable agent-authored node releases."""

import json
from hashlib import sha256
from typing import ClassVar, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from grafy_core.domain.node_secrets import JsonValue
from grafy_core.source_bundles import GeneratedNodeBuildDocument


GENERATED_EXECUTION_TIMESTAMP_HEADER = "X-Grafy-Execution-Timestamp"
GENERATED_EXECUTION_REQUEST_ID_HEADER = "X-Grafy-Execution-Request-Id"
GENERATED_EXECUTION_SIGNATURE_HEADER = "X-Grafy-Execution-Signature"


class GeneratedNodeExecutionContractError(ValueError):
    """A generated-node execution payload violates the signed wire contract."""


class _GeneratedExecutionValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    def canonical_json_bytes(self) -> bytes:
        try:
            rendered = json.dumps(
                self.model_dump(mode="json", by_alias=True, exclude_none=False),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise GeneratedNodeExecutionContractError(
                "Generated-node execution payload is not canonical JSON"
            ) from exc
        return rendered.encode("utf-8")


class GeneratedNodeExecutionRequest(_GeneratedExecutionValue):
    request_id: UUID
    workspace_id: UUID
    workflow_run_id: UUID | None = None
    node_run_id: UUID | None = None
    graph_node_id: str | None = Field(default=None, min_length=1, max_length=255)
    invocation_path: tuple[int, ...] = ()
    node_id: UUID
    revision: int = Field(ge=1)
    build_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_document: GeneratedNodeBuildDocument
    inputs: dict[str, JsonValue]

    @field_validator("invocation_path")
    @classmethod
    def validate_invocation_path(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(isinstance(item, bool) or item < 0 for item in value):
            raise ValueError("Generated-node invocation path must not be negative")
        return value

    @model_validator(mode="after")
    def validate_build_digest(self) -> Self:
        if self.build_document.digest != self.build_digest:
            raise ValueError(
                "Generated-node build document does not match its build digest"
            )
        return self


class GeneratedNodeExecutionResult(_GeneratedExecutionValue):
    request_id: UUID
    outputs: dict[str, JsonValue]
    execution_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_ms: int = Field(ge=0)


class GeneratedNodeExecutionFailure(_GeneratedExecutionValue):
    request_id: UUID
    error_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    message: str = Field(min_length=1, max_length=4_000)
    retryable: bool = False


class GeneratedReleaseExecutorPort(Protocol):
    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult: ...


def generated_execution_signature_payload(
    *,
    direction: Literal["request", "response"],
    timestamp: int,
    request_id: UUID,
    body: bytes,
    status_code: int | None = None,
) -> bytes:
    """Bind an HMAC to one exact body, direction, request id, and response status."""

    if isinstance(timestamp, bool) or timestamp < 0:
        raise GeneratedNodeExecutionContractError(
            "Generated-node signature timestamp must not be negative"
        )
    if direction == "request":
        if status_code is not None:
            raise GeneratedNodeExecutionContractError(
                "Generated-node request signatures do not include a status code"
            )
        rendered_status = "-"
    else:
        if status_code is None or status_code < 100 or status_code > 599:
            raise GeneratedNodeExecutionContractError(
                "Generated-node response signatures require an HTTP status code"
            )
        rendered_status = str(status_code)
    body_digest = sha256(body).hexdigest()
    return (
        "grafy-generated-node-execution-v1\n"
        f"{direction}\n"
        f"{timestamp}\n"
        f"{request_id}\n"
        f"{rendered_status}\n"
        f"{body_digest}\n"
    ).encode("ascii")


__all__ = [
    "GENERATED_EXECUTION_REQUEST_ID_HEADER",
    "GENERATED_EXECUTION_SIGNATURE_HEADER",
    "GENERATED_EXECUTION_TIMESTAMP_HEADER",
    "GeneratedNodeExecutionContractError",
    "GeneratedNodeExecutionFailure",
    "GeneratedNodeExecutionRequest",
    "GeneratedNodeExecutionResult",
    "GeneratedReleaseExecutorPort",
    "generated_execution_signature_payload",
]
