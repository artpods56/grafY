"""Provider-neutral artifact bundle protocol for isolated Plugin invocations.

The models in this module are the complete serialized host/guest contract.
They contain domain identities, relative bundle paths, limits, and typed
success or failure envelopes; process, mount, image, database, and storage
details belong to outer adapters.
"""

import json
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, ClassVar, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from grafy_core.artifacts import JsonObject
from grafy_core.domain.plugin_releases import (
    PLUGIN_INVOCATION_PROTOCOL,
    PluginArtifactBundleContract,
    PluginArtifactTypeKey,
)
from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    MAX_NODE_ERROR_MESSAGE_LENGTH,
    MAX_NODE_PROGRESS_COUNTER,
    MAX_NODE_PROGRESS_MESSAGE_LENGTH,
)


PluginArtifactShape = Literal["one", "many"]
PluginInvocationStatus = Literal["succeeded", "failed"]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_PLUGIN_PROGRESS_EVENTS: Final = 128
MAX_PLUGIN_PROGRESS_BYTES: Final = 256 * 1_024


class PluginProtocolCompatibilityError(ValueError):
    """A manifest uses a protocol version this runtime cannot execute."""


class PluginFailureCode(StrEnum):
    CONTRACT_FAILURE = "contract_failure"
    MATERIALIZATION_FAILURE = "materialization_failure"
    OPERATOR_FAILURE = "operator_failure"
    OUTPUT_VALIDATION = "output_validation"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    INTERNAL_ADAPTER_FAILURE = "internal_adapter_failure"


class PluginProtocolValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    def canonical_json_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


class _PluginProtocolHeader(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")

    protocol_version: str


def _require_supported_protocol(payload: bytes) -> None:
    header = _PluginProtocolHeader.model_validate_json(payload)
    if header.protocol_version != PLUGIN_INVOCATION_PROTOCOL:
        raise PluginProtocolCompatibilityError(
            f"Unsupported Plugin invocation protocol "
            f"{header.protocol_version!r}; expected {PLUGIN_INVOCATION_PROTOCOL!r}"
        )


def _validate_relative_bundle_path(value: str) -> str:
    if "\\" in value:
        raise ValueError("Plugin bundle paths must use POSIX separators")
    path = PurePosixPath(value)
    if (
        value == ""
        or path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(
            "Plugin bundle paths must be normalized relative paths without traversal"
        )
    return value


class PluginInvocationRelease(PluginProtocolValue):
    scope: PluginReleaseScope
    workspace_id: UUID | None
    slug: str = Field(
        pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$",
        max_length=100,
    )
    revision: int = Field(ge=1, strict=True)
    source_digest: Sha256Digest
    contract_digest: Sha256Digest
    protocol_digest: Sha256Digest
    descriptor_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_namespace(self) -> Self:
        if self.scope is PluginReleaseScope.WORKSPACE and self.workspace_id is None:
            raise ValueError("Workspace Plugin invocation release requires an owner")
        if self.scope is PluginReleaseScope.SYSTEM and self.workspace_id is not None:
            raise ValueError("System Plugin invocation release cannot have an owner")
        return self


class PluginInvocationArtifactTypeBinding(PluginProtocolValue):
    variable: str = Field(min_length=1, max_length=255)
    artifact_type: PluginArtifactTypeKey


class PluginInvocationLimits(PluginProtocolValue):
    wall_time_seconds: int = Field(default=60, ge=1, le=3_600, strict=True)
    max_input_bytes: int = Field(
        default=64 * 1_024 * 1_024,
        ge=1,
        le=16 * 1_024 * 1_024 * 1_024,
        strict=True,
    )
    max_output_bytes: int = Field(
        default=64 * 1_024 * 1_024,
        ge=1,
        le=16 * 1_024 * 1_024 * 1_024,
        strict=True,
    )
    max_files: int = Field(default=1_024, ge=1, le=100_000, strict=True)
    max_log_bytes: int = Field(
        default=256 * 1_024,
        ge=1,
        le=64 * 1_024 * 1_024,
        strict=True,
    )
    max_secret_bytes: int = Field(
        default=64 * 1_024,
        ge=1,
        le=16 * 1_024 * 1_024,
        strict=True,
    )
    max_table_rows: int = Field(default=1_000_000, ge=0, le=100_000_000, strict=True)
    max_table_columns: int = Field(default=10_000, ge=0, le=10_000, strict=True)
    max_table_chunks: int = Field(default=10_000, ge=0, le=100_000, strict=True)


class PluginInputArtifactBundle(PluginProtocolValue):
    artifact_id: UUID
    relative_path: str = Field(min_length=1, max_length=1_024)
    byte_count: int = Field(ge=0, strict=True)
    content_sha256: Sha256Digest
    content_type: str = Field(default="application/json", min_length=1, max_length=255)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_relative_path(self) -> Self:
        _validate_relative_bundle_path(self.relative_path)
        if not self.relative_path.startswith("inputs/"):
            raise ValueError("Plugin input bundle paths must be beneath inputs/")
        return self


class PluginInputArtifactDependency(PluginProtocolValue):
    artifact_type: PluginArtifactTypeKey
    bundle: PluginArtifactBundleContract
    artifact: PluginInputArtifactBundle


class PluginOutputArtifactBundle(PluginProtocolValue):
    relative_path: str = Field(min_length=1, max_length=1_024)
    byte_count: int = Field(ge=0, strict=True)
    content_sha256: Sha256Digest
    content_type: str = Field(default="application/json", min_length=1, max_length=255)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_relative_path(self) -> Self:
        _validate_relative_bundle_path(self.relative_path)
        if not self.relative_path.startswith("outputs/"):
            raise ValueError("Plugin output bundle paths must be beneath outputs/")
        return self


class PluginInputArtifactGroup(PluginProtocolValue):
    shape: PluginArtifactShape
    artifacts: tuple[PluginInputArtifactBundle, ...]

    @model_validator(mode="after")
    def validate_cardinality(self) -> Self:
        if self.shape == "one" and len(self.artifacts) != 1:
            raise ValueError("A shape='one' input group must contain one artifact")
        return self


class PluginInputBinding(PluginProtocolValue):
    port: str = Field(min_length=1, max_length=255)
    artifact_type: PluginArtifactTypeKey
    bundle: PluginArtifactBundleContract = PluginArtifactBundleContract(
        format="inline-json",
        version=1,
    )
    groups: tuple[PluginInputArtifactGroup, ...] = Field(min_length=1)


class PluginOutputDeclaration(PluginProtocolValue):
    port: str = Field(min_length=1, max_length=255)
    artifact_type: PluginArtifactTypeKey
    bundle: PluginArtifactBundleContract = PluginArtifactBundleContract(
        format="inline-json",
        version=1,
    )
    shape: PluginArtifactShape
    required: bool = True


class PluginOutputBinding(PluginProtocolValue):
    port: str = Field(min_length=1, max_length=255)
    artifact_type: PluginArtifactTypeKey
    bundle: PluginArtifactBundleContract = PluginArtifactBundleContract(
        format="inline-json",
        version=1,
    )
    shape: PluginArtifactShape
    artifacts: tuple[PluginOutputArtifactBundle, ...]

    @model_validator(mode="after")
    def validate_cardinality(self) -> Self:
        if self.shape == "one" and len(self.artifacts) != 1:
            raise ValueError("A shape='one' output must contain one artifact")
        return self


class PluginSecretBinding(PluginProtocolValue):
    """Non-secret metadata for one separately staged credential file."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=255)
    config_dependencies: tuple[str, ...] = ()
    dependency_digest: Sha256Digest
    relative_path: str = Field(min_length=1, max_length=1_024)

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if len(self.config_dependencies) != len(set(self.config_dependencies)):
            raise ValueError("Plugin secret config dependencies must be unique")
        _validate_relative_bundle_path(self.relative_path)
        if not self.relative_path.startswith("secrets/"):
            raise ValueError("Plugin secret paths must be beneath secrets/")
        return self


class PluginInvocationEnvelope(PluginProtocolValue):
    protocol_version: Literal["grafy-plugin-invocation@7"] = PLUGIN_INVOCATION_PROTOCOL
    invocation_id: UUID
    execution_scope_id: UUID
    workspace_id: UUID
    workflow_run_id: UUID | None = None
    secret_graph_id: UUID | None = None
    secret_graph_revision: int | None = Field(default=None, ge=1, strict=True)
    node_id: str | None = Field(default=None, min_length=1, max_length=255)
    invocation_index: int | None = Field(default=None, ge=0, strict=True)
    release: PluginInvocationRelease
    operator_id: str = Field(min_length=1, max_length=255)
    operator_version: int = Field(ge=1, strict=True)
    required_capabilities: tuple[PluginRuntimeCapability, ...] = ()
    artifact_type_bindings: tuple[PluginInvocationArtifactTypeBinding, ...] = ()
    config: JsonObject
    inputs: tuple[PluginInputBinding, ...]
    input_artifact_dependencies: tuple[PluginInputArtifactDependency, ...] = Field(
        default=(),
        max_length=10_000,
    )
    outputs: tuple[PluginOutputDeclaration, ...]
    secrets: tuple[PluginSecretBinding, ...] = ()
    limits: PluginInvocationLimits

    @field_validator("required_capabilities")
    @classmethod
    def normalize_required_capabilities(
        cls,
        value: tuple[PluginRuntimeCapability, ...],
    ) -> tuple[PluginRuntimeCapability, ...]:
        normalized = {PluginRuntimeCapability(capability) for capability in value}
        return tuple(sorted(normalized, key=lambda capability: capability.value))

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if (
            self.release.scope is PluginReleaseScope.WORKSPACE
            and self.release.workspace_id != self.workspace_id
        ):
            raise ValueError(
                "Plugin invocation release owner must match the invocation workspace"
            )
        input_ports = [binding.port for binding in self.inputs]
        if len(input_ports) != len(set(input_ports)):
            raise ValueError("Plugin invocation input port bindings must be unique")
        output_ports = [declaration.port for declaration in self.outputs]
        if len(output_ports) != len(set(output_ports)):
            raise ValueError("Plugin invocation output declarations must be unique")
        variables = [binding.variable for binding in self.artifact_type_bindings]
        if len(variables) != len(set(variables)):
            raise ValueError("Plugin artifact type variable bindings must be unique")
        secret_names = [binding.name for binding in self.secrets]
        if len(secret_names) != len(set(secret_names)):
            raise ValueError("Plugin invocation secret bindings must be unique")
        secret_paths = [binding.relative_path for binding in self.secrets]
        if len(secret_paths) != len(set(secret_paths)):
            raise ValueError("Plugin invocation secret paths must be unique")
        direct_artifact_ids = {
            artifact.artifact_id
            for binding in self.inputs
            for group in binding.groups
            for artifact in group.artifacts
        }
        dependency_artifact_ids = [
            dependency.artifact.artifact_id
            for dependency in self.input_artifact_dependencies
        ]
        if len(dependency_artifact_ids) != len(set(dependency_artifact_ids)):
            raise ValueError("Plugin input artifact dependencies must be unique")
        if direct_artifact_ids & set(dependency_artifact_ids):
            raise ValueError(
                "Plugin direct inputs and artifact dependencies must be disjoint"
            )
        paths = [
            artifact.relative_path
            for binding in self.inputs
            for group in binding.groups
            for artifact in group.artifacts
        ]
        paths.extend(
            dependency.artifact.relative_path
            for dependency in self.input_artifact_dependencies
        )
        if len(paths) != len(set(paths)):
            raise ValueError("Plugin invocation input bundle paths must be unique")
        json.dumps(
            self.config,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return self

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> Self:
        _require_supported_protocol(payload)
        return cls.model_validate_json(payload)


class PluginFailureEnvelope(PluginProtocolValue):
    code: PluginFailureCode
    message: str = Field(min_length=1, max_length=MAX_NODE_ERROR_MESSAGE_LENGTH)
    release_slug: str = Field(min_length=1, max_length=100)
    release_revision: int = Field(ge=1, strict=True)
    operator_id: str = Field(min_length=1, max_length=255)
    operator_version: int = Field(ge=1, strict=True)
    node_id: str | None = Field(default=None, min_length=1, max_length=255)
    invocation_index: int | None = Field(default=None, ge=0, strict=True)


class PluginProgressEvent(PluginProtocolValue):
    """One bounded user-visible progress update emitted by the guest node."""

    message: str = Field(min_length=1, max_length=MAX_NODE_PROGRESS_MESSAGE_LENGTH)
    current: int | None = Field(
        default=None,
        ge=0,
        le=MAX_NODE_PROGRESS_COUNTER,
        strict=True,
    )
    total: int | None = Field(
        default=None,
        ge=0,
        le=MAX_NODE_PROGRESS_COUNTER,
        strict=True,
    )

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Plugin progress message must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_counters(self) -> Self:
        if (
            self.current is not None
            and self.total is not None
            and self.current > self.total
        ):
            raise ValueError("Plugin progress current value must not exceed total")
        return self


class PluginInvocationResultEnvelope(PluginProtocolValue):
    protocol_version: Literal["grafy-plugin-invocation@7"] = PLUGIN_INVOCATION_PROTOCOL
    invocation_id: UUID
    status: PluginInvocationStatus
    outputs: tuple[PluginOutputBinding, ...] = ()
    failure: PluginFailureEnvelope | None = None
    progress: tuple[PluginProgressEvent, ...] = Field(
        default=(),
        max_length=MAX_PLUGIN_PROGRESS_EVENTS,
    )

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status == "succeeded" and self.failure is not None:
            raise ValueError("A successful Plugin result cannot contain a failure")
        if self.status == "failed" and self.failure is None:
            raise ValueError("A failed Plugin result requires a failure envelope")
        if self.status == "failed" and self.outputs:
            raise ValueError("A failed Plugin result cannot expose output bundles")
        output_ports = [binding.port for binding in self.outputs]
        if len(output_ports) != len(set(output_ports)):
            raise ValueError("Plugin result output port bindings must be unique")
        paths = [
            artifact.relative_path
            for binding in self.outputs
            for artifact in binding.artifacts
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("Plugin result output bundle paths must be unique")
        progress_bytes = sum(
            len(event.canonical_json_bytes()) for event in self.progress
        )
        if progress_bytes > MAX_PLUGIN_PROGRESS_BYTES:
            raise ValueError("Plugin result progress exceeds the protocol byte limit")
        return self

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> Self:
        _require_supported_protocol(payload)
        return cls.model_validate_json(payload)


__all__ = [
    "MAX_PLUGIN_PROGRESS_EVENTS",
    "MAX_PLUGIN_PROGRESS_BYTES",
    "PluginArtifactShape",
    "PluginFailureCode",
    "PluginFailureEnvelope",
    "PluginInputArtifactBundle",
    "PluginInputArtifactDependency",
    "PluginInputArtifactGroup",
    "PluginInputBinding",
    "PluginInvocationArtifactTypeBinding",
    "PluginInvocationEnvelope",
    "PluginInvocationLimits",
    "PluginInvocationRelease",
    "PluginInvocationResultEnvelope",
    "PluginOutputArtifactBundle",
    "PluginOutputBinding",
    "PluginOutputDeclaration",
    "PluginProgressEvent",
    "PluginProtocolCompatibilityError",
    "PluginSecretBinding",
]
