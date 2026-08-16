from pathlib import PurePosixPath
from hashlib import sha256
import re
from enum import StrEnum
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from grafy_core.domain.agent_authoring import (
    CapabilityManifest,
    GeneratedNodeManifest,
)

from grafy_agent.errors import SandboxPathError


class AgentModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


def normalized_relative_path(value: str, *, label: str = "Path") -> str:
    if "\x00" in value:
        raise SandboxPathError(f"{label} must not contain a NUL byte")
    if "\\" in value:
        raise SandboxPathError(f"{label} must use POSIX separators")
    candidate = value.strip()
    path = PurePosixPath(candidate)
    if candidate == "" or path.is_absolute():
        raise SandboxPathError(f"{label} must be a non-empty relative path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SandboxPathError(
            f"{label} must not contain empty, dot, or parent segments"
        )
    normalized = path.as_posix()
    if normalized != candidate:
        raise SandboxPathError(f"{label} must be normalized")
    return normalized


class SandboxWorkspace(AgentModel):
    environment_id: UUID
    provider: str = Field(min_length=1, max_length=255)
    provider_environment_id: str = Field(min_length=1, max_length=1_024)
    root: str = Field(default="/workspace", min_length=1, max_length=2_048)
    runtime_image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("provider", "provider_environment_id", "root")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Sandbox workspace values must not be blank")
        return normalized


class SandboxExecutionAuthority(AgentModel):
    execution_id: UUID
    token: UUID = Field(repr=False)
    fencing_token: int = Field(ge=1)

    @classmethod
    def from_agent_lease(cls, lease: "AgentLease") -> "SandboxExecutionAuthority":
        return cls(
            execution_id=lease.run_id,
            token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )


class SandboxSession(AgentModel):
    """Lease-fenced authority to mutate one reusable sandbox workspace."""

    workspace: SandboxWorkspace
    execution_id: UUID
    authority_token: UUID = Field(repr=False)
    fencing_token: int = Field(ge=1)
    provider_session_id: str = Field(min_length=1, max_length=255)

    @field_validator("provider_session_id")
    @classmethod
    def validate_provider_session_id(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Sandbox provider session id must not be blank")
        return normalized


class SandboxTerminationResult(AgentModel):
    provider_session_id: str = Field(min_length=1, max_length=255)
    terminated_execution_count: int = Field(ge=0)
    revocation_verified: Literal[True] = True


class SandboxRuntimeArtifact(AgentModel):
    provider: str = Field(min_length=1, max_length=255)
    reference: str = Field(min_length=1, max_length=2_048)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class SandboxNetworkMode(StrEnum):
    BLOCKED = "blocked"
    PACKAGE_INDEX = "package-index"


class SandboxExecutionRequest(AgentModel):
    argv: tuple[str, ...] = Field(min_length=1, max_length=128)
    cwd: str
    stdin: bytes | None = Field(default=None, repr=False, max_length=67_108_864)
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=86_400.0)
    max_output_bytes: int = Field(default=1_048_576, ge=1_024, le=16_777_216)
    network_mode: SandboxNetworkMode = SandboxNetworkMode.BLOCKED

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for argument in value:
            if argument == "" or "\x00" in argument:
                raise ValueError("Command arguments must be non-empty and NUL-free")
            if len(argument) > 16_384:
                raise ValueError("Command arguments must be at most 16384 characters")
        return value

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        return normalized_relative_path(value, label="Command working directory")


class SandboxExecutionResult(AgentModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int = Field(ge=0)
    output_truncated: bool = False


class SandboxFileContents(AgentModel):
    path: str
    content: str
    byte_count: int = Field(ge=0)


class SandboxFileChange(AgentModel):
    path: str
    byte_count: int = Field(ge=0)
    created: bool


class SandboxPatchResult(AgentModel):
    path: str
    replacements: int = Field(ge=1)
    byte_count: int = Field(ge=0)


class SandboxArchive(AgentModel):
    data: bytes = Field(repr=False)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=1, le=67_108_864)

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        if len(self.data) != self.byte_count:
            raise ValueError("Sandbox archive byte count does not match its data")
        if sha256(self.data).hexdigest() != self.sha256:
            raise ValueError("Sandbox archive SHA-256 does not match its data")
        return self


class SandboxImportResult(AgentModel):
    destination: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentLease(AgentModel):
    workspace_id: UUID
    thread_id: UUID
    environment_id: UUID
    run_id: UUID
    lease_token: UUID
    fencing_token: int = Field(ge=1)
    target_draft_ids: tuple[UUID, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        if len(self.target_draft_ids) != len(set(self.target_draft_ids)):
            raise ValueError("Agent lease target drafts must be unique")
        return self


class AgentProgress(AgentModel):
    message: str = Field(min_length=1, max_length=4_000)
    draft_node_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Agent progress messages must not be blank")
        return normalized


class CapabilityProposal(AgentModel):
    draft_node_id: UUID
    capabilities: CapabilityManifest
    rationale: str = Field(min_length=1, max_length=4_000)

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Capability proposal rationale must not be blank")
        return normalized


class CapabilityProposalReceipt(AgentModel):
    capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    awaiting_user_approval: Literal[True] = True


class ReleaseProposal(AgentModel):
    draft_node_id: UUID
    manifest: GeneratedNodeManifest
    capabilities: CapabilityManifest
    source_bundle: "NodeSourceBundle"
    verification: "SourceBundleVerification"
    summary: str = Field(min_length=1, max_length=4_000)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Release proposal summary must not be blank")
        return normalized


class ReleaseProposalReceipt(AgentModel):
    build_attempt_id: UUID
    awaiting_user_approval: Literal[True] = True


class NodeSourceBundle(AgentModel):
    archive: SandboxArchive
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    tests_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_count: int = Field(ge=4, le=2_000)


class SourceBundleVerification(AgentModel):
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    tests_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_artifact: SandboxRuntimeArtifact
    lock_check_passed: Literal[True] = True
    locked_sync_passed: Literal[True] = True
    tests_passed: Literal[True] = True


class CodingMessage(AgentModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Coding messages must not be blank")
        return normalized


class CodingAgentRequest(AgentModel):
    instructions: str = Field(min_length=1, max_length=20_000)
    history: tuple[CodingMessage, ...] = ()

    @field_validator("instructions")
    @classmethod
    def validate_instructions(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Coding-agent instructions must not be blank")
        return normalized


class CodingAgentResult(AgentModel):
    summary: str = Field(min_length=1, max_length=20_000)
    model_name: str = Field(min_length=1, max_length=255)


_PACKAGE_REQUIREMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_.,-]+\])?"
    r"(?:\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[^\s;]+)?$"
)


def validated_package_requirements(values: tuple[str, ...]) -> tuple[str, ...]:
    if not values:
        raise ValueError("At least one package requirement is required")
    normalized: list[str] = []
    for value in values:
        candidate = value.strip()
        if (
            candidate.startswith("-")
            or _PACKAGE_REQUIREMENT.fullmatch(candidate) is None
        ):
            raise ValueError(f"Unsupported package requirement {value!r}")
        normalized.append(candidate)
    return tuple(normalized)


__all__ = [
    "AgentLease",
    "AgentProgress",
    "CapabilityProposal",
    "CapabilityProposalReceipt",
    "CodingAgentRequest",
    "CodingAgentResult",
    "CodingMessage",
    "NodeSourceBundle",
    "ReleaseProposal",
    "ReleaseProposalReceipt",
    "SandboxExecutionRequest",
    "SandboxExecutionAuthority",
    "SandboxExecutionResult",
    "SandboxArchive",
    "SandboxFileChange",
    "SandboxFileContents",
    "SandboxPatchResult",
    "SandboxRuntimeArtifact",
    "SandboxSession",
    "SandboxTerminationResult",
    "SandboxImportResult",
    "SandboxNetworkMode",
    "SandboxWorkspace",
    "SourceBundleVerification",
    "normalized_relative_path",
    "validated_package_requirements",
]
