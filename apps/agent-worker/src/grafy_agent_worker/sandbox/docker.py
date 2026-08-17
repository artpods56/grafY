import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from time import monotonic
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_agent.errors import AgentConfigurationError, SandboxOperationError
from grafy_agent.models import (
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxArchive,
    SandboxFileChange,
    SandboxFileContents,
    SandboxImportResult,
    SandboxPatchResult,
    SandboxRuntimeArtifact,
    SandboxSession,
    SandboxTerminationResult,
    SandboxWorkspace,
    normalized_relative_path,
)
from grafy_agent_worker.sandbox.guest import program
from grafy_core.source_bundles import read_source_bundle
from grafy_core.domain.agent_authoring import RuntimeLimits


_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class _WriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created: bool
    byte_count: int = Field(ge=0)


class _PatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacements: int = Field(ge=1)
    byte_count: int = Field(ge=0)


class DockerSandboxSettings(BaseSettings):
    """Explicit opt-in settings for the non-production Docker adapter."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="GRAFY_AGENT_DOCKER_",
        extra="ignore",
    )

    trusted_development_enabled: bool = False
    executable: str = "docker"
    image: str = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
    cpu_limit: float = Field(default=2.0, gt=0.0, le=32.0)
    memory_limit: str = "2g"
    pids_limit: int = Field(default=256, ge=16, le=4_096)
    workspace_disk_bytes: int = Field(
        default=2_147_483_648,
        ge=67_108_864,
        le=68_719_476_736,
    )

    @field_validator("executable", "image", "memory_limit")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Docker sandbox settings must not be blank")
        return normalized


@dataclass(frozen=True, slots=True)
class _HostCommandResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_ms: int
    output_truncated: bool


class DockerSandboxWorkspace:
    """Trusted-development sandbox backed by one Docker container per environment."""

    def __init__(self, settings: DockerSandboxSettings) -> None:
        if not settings.trusted_development_enabled:
            raise AgentConfigurationError(
                "Docker agent workspaces are a trusted-development adapter and require "
                "GRAFY_AGENT_DOCKER_TRUSTED_DEVELOPMENT_ENABLED=true"
            )
        self._settings = settings
        self._provision_locks: dict[UUID, asyncio.Lock] = {}
        self._sessions: dict[UUID, SandboxSession] = {}
        self._revoked_sessions: set[str] = set()
        self._dependency_helpers: dict[str, str] = {}

    async def ensure_workspace(
        self,
        *,
        environment_id: UUID,
        provider_environment_id: str | None,
        profile_id: str,
    ) -> SandboxWorkspace:
        if profile_id.strip() == "":
            raise SandboxOperationError("Sandbox profile id must not be blank")
        image_inspection = await self._run_host(
            (
                self._settings.executable,
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                self._settings.image,
            ),
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(image_inspection, "inspect Docker sandbox image")
        image_id = image_inspection.stdout.decode("ascii", errors="strict").strip()
        if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
            raise SandboxOperationError(
                f"Docker returned invalid immutable image id {image_id!r}"
            )
        runtime_image_digest = image_id.removeprefix("sha256:")
        profile_document = json.dumps(
            {
                "profile_id": profile_id,
                "runtime_image_digest": runtime_image_digest,
                "cpu_limit": self._settings.cpu_limit,
                "memory_limit": self._settings.memory_limit,
                "pids_limit": self._settings.pids_limit,
                "workspace_disk_bytes": self._settings.workspace_disk_bytes,
                "network": "none",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        profile_digest = sha256(profile_document).hexdigest()
        container = provider_environment_id or f"grafy-agent-{environment_id.hex}"
        if _CONTAINER_NAME.fullmatch(container) is None:
            raise SandboxOperationError(
                f"Invalid Docker provider environment id {container!r}"
            )
        lock = self._provision_locks.setdefault(environment_id, asyncio.Lock())
        async with lock:
            inspected = await self._run_host(
                (
                    self._settings.executable,
                    "container",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    container,
                ),
                stdin=None,
                timeout_seconds=30.0,
                max_output_bytes=65_536,
            )
            if inspected.exit_code == 0:
                container_image = await self._run_host(
                    (
                        self._settings.executable,
                        "container",
                        "inspect",
                        "--format",
                        "{{.Image}}",
                        container,
                    ),
                    stdin=None,
                    timeout_seconds=30.0,
                    max_output_bytes=65_536,
                )
                self._require_success(
                    container_image,
                    "verify Docker agent environment image",
                )
                if container_image.stdout.decode("ascii").strip() != image_id:
                    raise SandboxOperationError(
                        f"Docker environment {container!r} uses a different immutable image"
                    )
                if inspected.stdout.strip() != b"true":
                    started = await self._run_host(
                        (self._settings.executable, "start", container),
                        stdin=None,
                        timeout_seconds=30.0,
                        max_output_bytes=65_536,
                    )
                    self._require_success(started, "start Docker agent environment")
            elif (
                b"No such object" in inspected.stderr
                or b"No such container" in inspected.stderr
            ):
                volume = f"{container}-workspace"
                created = await self._run_host(
                    (
                        self._settings.executable,
                        "run",
                        "--detach",
                        "--name",
                        container,
                        "--label",
                        f"grafy.agent.environment={environment_id}",
                        "--label",
                        f"grafy.agent.profile-digest={profile_digest}",
                        "--network",
                        "none",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--cpus",
                        str(self._settings.cpu_limit),
                        "--memory",
                        self._settings.memory_limit,
                        "--pids-limit",
                        str(self._settings.pids_limit),
                        "--tmpfs",
                        "/tmp:rw,noexec,nosuid,size=256m",
                        "--volume",
                        f"{volume}:/workspace",
                        "--workdir",
                        "/workspace",
                        self._settings.image,
                        "sleep",
                        "infinity",
                    ),
                    stdin=None,
                    timeout_seconds=120.0,
                    max_output_bytes=65_536,
                )
                self._require_success(created, "create Docker agent environment")
            else:
                self._require_success(inspected, "inspect Docker agent environment")
        return SandboxWorkspace(
            environment_id=environment_id,
            provider="docker-trusted-development",
            provider_environment_id=container,
            root="/workspace",
            runtime_image_digest=runtime_image_digest,
            profile_digest=profile_digest,
        )

    async def open_session(
        self,
        workspace: SandboxWorkspace,
        authority: SandboxExecutionAuthority,
    ) -> SandboxSession:
        self._require_workspace(workspace)
        session = SandboxSession(
            workspace=workspace,
            execution_id=authority.execution_id,
            authority_token=authority.token,
            fencing_token=authority.fencing_token,
            provider_session_id=(
                f"grafy-{workspace.environment_id.hex}-{authority.execution_id.hex}"
            ),
        )
        marker = self._session_marker(session)
        written = await self._raw_docker_exec(
            workspace,
            self._guest("write_marker", marker, self._fence_value(session)),
            cwd=workspace.root,
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(written, "activate Docker sandbox lease fence")
        previous = self._sessions.get(workspace.environment_id)
        if previous is not None and previous != session:
            self._revoked_sessions.add(previous.provider_session_id)
        self._sessions[workspace.environment_id] = session
        self._revoked_sessions.discard(session.provider_session_id)
        return session

    async def terminate_session(
        self,
        session: SandboxSession,
    ) -> SandboxTerminationResult:
        return await self.terminate_execution(
            session.workspace,
            execution_id=session.execution_id,
        )

    async def terminate_execution(
        self,
        workspace: SandboxWorkspace,
        *,
        execution_id: UUID,
    ) -> SandboxTerminationResult:
        self._require_workspace(workspace)
        provider_session_id = f"grafy-{workspace.environment_id.hex}-{execution_id.hex}"
        self._revoked_sessions.add(provider_session_id)
        marker = self._session_marker_for(workspace, provider_session_id)
        revoked = await self._raw_docker_exec(
            workspace,
            self._guest("write_marker", marker, f"revoked:{provider_session_id}"),
            cwd=workspace.root,
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(revoked, "revoke Docker sandbox lease fence")
        helper = self._dependency_helpers.pop(provider_session_id, None)
        if helper is not None:
            removed = await self._run_host(
                (self._settings.executable, "container", "rm", "--force", helper),
                stdin=None,
                timeout_seconds=30.0,
                max_output_bytes=65_536,
            )
            if removed.exit_code != 0 and b"No such container" not in removed.stderr:
                self._require_success(removed, "terminate Docker dependency helper")
        stopped = await self._run_host(
            (
                self._settings.executable,
                "container",
                "stop",
                "--time",
                "0",
                workspace.provider_environment_id,
            ),
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(stopped, "stop Docker sandbox execution cgroup")
        stopped_state = await self._run_host(
            (
                self._settings.executable,
                "container",
                "inspect",
                "--format",
                "{{.State.Running}}",
                workspace.provider_environment_id,
            ),
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(stopped_state, "verify Docker sandbox stopped")
        if stopped_state.stdout.strip() != b"false":
            raise SandboxOperationError(
                "Docker sandbox still has a live execution cgroup after revocation"
            )
        restarted = await self._run_host(
            (
                self._settings.executable,
                "container",
                "start",
                workspace.provider_environment_id,
            ),
            stdin=None,
            timeout_seconds=60.0,
            max_output_bytes=65_536,
        )
        self._require_success(restarted, "restart clean Docker sandbox container")
        active = self._sessions.get(workspace.environment_id)
        if active is not None and active.execution_id == execution_id:
            del self._sessions[workspace.environment_id]
        return SandboxTerminationResult(
            provider_session_id=provider_session_id,
            terminated_execution_count=1,
        )

    async def destroy_workspace(self, workspace: SandboxWorkspace) -> None:
        self._require_workspace(workspace)
        container = workspace.provider_environment_id
        removed = await self._run_host(
            (self._settings.executable, "container", "rm", "--force", container),
            stdin=None,
            timeout_seconds=60.0,
            max_output_bytes=65_536,
        )
        if removed.exit_code != 0 and b"No such container" not in removed.stderr:
            self._require_success(removed, "destroy Docker sandbox container")
        volume = f"{container}-workspace"
        volume_removed = await self._run_host(
            (self._settings.executable, "volume", "rm", volume),
            stdin=None,
            timeout_seconds=60.0,
            max_output_bytes=65_536,
        )
        if (
            volume_removed.exit_code != 0
            and b"no such volume" not in volume_removed.stderr.lower()
        ):
            self._require_success(volume_removed, "destroy Docker sandbox volume")
        self._sessions.pop(workspace.environment_id, None)

    async def freeze_workspace(
        self,
        session: SandboxSession,
        *,
        artifact_name: str,
        source_digest: str,
    ) -> SandboxRuntimeArtifact:
        self._require_session(session)
        if _CONTAINER_NAME.fullmatch(artifact_name) is None:
            raise SandboxOperationError(
                f"Invalid Docker runtime artifact name {artifact_name!r}"
            )
        expected_identity = sha256(
            (
                f"{source_digest}:{session.workspace.runtime_image_digest}:"
                f"{session.workspace.profile_digest}"
            ).encode("ascii")
        ).hexdigest()
        if artifact_name != f"grafy-node-{expected_identity}":
            raise SandboxOperationError(
                "Docker runtime artifact name does not match its provenance"
            )
        existing = await self._run_host(
            (
                self._settings.executable,
                "image",
                "inspect",
                "--format",
                (
                    '{{.Id}} {{index .Config.Labels "grafy.source-digest"}} '
                    '{{index .Config.Labels "grafy.runtime-image-digest"}} '
                    '{{index .Config.Labels "grafy.profile-digest"}}'
                ),
                artifact_name,
            ),
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        if existing.exit_code == 0:
            provenance = existing.stdout.decode("ascii").strip().split()
            expected = [
                source_digest,
                session.workspace.runtime_image_digest,
                session.workspace.profile_digest,
            ]
            if len(provenance) != 4 or provenance[1:] != expected:
                raise SandboxOperationError(
                    f"Docker runtime artifact {artifact_name!r} has invalid provenance"
                )
            return SandboxRuntimeArtifact(
                provider="docker-trusted-development",
                reference=provenance[0],
                digest=provenance[0].removeprefix("sha256:"),
            )
        freezer = f"grafy-freeze-{sha256(artifact_name.encode()).hexdigest()[:24]}"
        volume = f"{session.workspace.provider_environment_id}-workspace"
        created = await self._run_host(
            (
                self._settings.executable,
                "container",
                "create",
                "--name",
                freezer,
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--volume",
                f"{volume}:/source:ro",
                self._settings.image,
                *self._guest(
                    "copy_runtime_tree",
                    "/source/node",
                    "/opt/grafy-runtime/node",
                ),
            ),
            stdin=None,
            timeout_seconds=60.0,
            max_output_bytes=65_536,
        )
        self._require_success(created, "create Docker runtime freezer")
        try:
            started = await self._run_host(
                (self._settings.executable, "container", "start", "--attach", freezer),
                stdin=None,
                timeout_seconds=120.0,
                max_output_bytes=1_048_576,
            )
            self._require_success(started, "copy verified Docker runtime tree")
            committed = await self._run_host(
                (
                    self._settings.executable,
                    "container",
                    "commit",
                    "--change",
                    f"LABEL grafy.source-digest={source_digest}",
                    "--change",
                    (
                        "LABEL grafy.runtime-image-digest="
                        f"{session.workspace.runtime_image_digest}"
                    ),
                    "--change",
                    f"LABEL grafy.profile-digest={session.workspace.profile_digest}",
                    freezer,
                    artifact_name,
                ),
                stdin=None,
                timeout_seconds=120.0,
                max_output_bytes=65_536,
            )
            self._require_success(committed, "freeze Docker runtime artifact")
        finally:
            await self._run_host(
                (self._settings.executable, "container", "rm", "--force", freezer),
                stdin=None,
                timeout_seconds=30.0,
                max_output_bytes=65_536,
            )
        image_id = committed.stdout.decode("ascii").strip()
        if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
            raise SandboxOperationError(
                "Docker commit returned an invalid image digest"
            )
        return SandboxRuntimeArtifact(
            provider="docker-trusted-development",
            reference=image_id,
            digest=image_id.removeprefix("sha256:"),
        )

    async def create_runtime_workspace(
        self,
        *,
        environment_id: UUID,
        artifact: SandboxRuntimeArtifact,
        limits: RuntimeLimits,
    ) -> SandboxWorkspace:
        if artifact.provider != "docker-trusted-development":
            raise SandboxOperationError(
                f"Docker adapter cannot start {artifact.provider!r} runtime artifact"
            )
        inspected = await self._run_host(
            (
                self._settings.executable,
                "image",
                "inspect",
                "--format",
                "{{.Id}} {{.Size}}",
                artifact.reference,
            ),
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(inspected, "verify Docker runtime artifact")
        inspection = inspected.stdout.decode("ascii").strip().split()
        if len(inspection) != 2 or not inspection[1].isdigit():
            raise SandboxOperationError(
                "Docker returned invalid runtime image metadata"
            )
        image_id, image_size_text = inspection
        if image_id.removeprefix("sha256:") != artifact.digest:
            raise SandboxOperationError("Docker runtime artifact digest mismatch")
        if int(image_size_text) > limits.persistent_disk_bytes:
            raise SandboxOperationError(
                "Docker runtime artifact exceeds the approved persistent-disk limit"
            )
        container = f"grafy-runtime-{environment_id.hex}"
        created = await self._run_host(
            (
                self._settings.executable,
                "run",
                "--detach",
                "--name",
                container,
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--cpus",
                str(min(self._settings.cpu_limit, limits.cpu_millis / 1_000)),
                "--memory",
                f"{limits.memory_megabytes}m",
                "--pids-limit",
                str(
                    min(
                        self._settings.pids_limit,
                        limits.process_count,
                        limits.thread_count,
                    )
                ),
                "--tmpfs",
                f"/tmp:rw,noexec,nosuid,size={limits.temporary_disk_bytes}",
                "--workdir",
                "/opt/grafy-runtime",
                artifact.reference,
                "sleep",
                "infinity",
            ),
            stdin=None,
            timeout_seconds=120.0,
            max_output_bytes=65_536,
        )
        self._require_success(created, "start Docker runtime artifact")
        return SandboxWorkspace(
            environment_id=environment_id,
            provider="docker-trusted-development",
            provider_environment_id=container,
            root="/opt/grafy-runtime",
            runtime_image_digest=artifact.digest,
            profile_digest=sha256(
                f"docker-runtime:{artifact.digest}".encode("ascii")
            ).hexdigest(),
        )

    async def read_text(
        self,
        session: SandboxSession,
        *,
        path: str,
        max_bytes: int,
    ) -> SandboxFileContents:
        self._require_session(session)
        workspace = session.workspace
        normalized = normalized_relative_path(path)
        result = await self._docker_exec(
            session,
            self._guest(
                "read_text",
                f"{workspace.root}/{normalized}",
                str(max_bytes),
            ),
            cwd=workspace.root,
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=max_bytes,
        )
        if result.exit_code != 0:
            message = result.stderr.decode("utf-8", errors="replace")
            if "FileNotFoundError" in message:
                raise FileNotFoundError(
                    f"Sandbox file {normalized!r} does not exist in environment "
                    f"{workspace.environment_id}"
                )
            self._require_success(result, f"read sandbox file {normalized!r}")
        try:
            content = result.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SandboxOperationError(
                f"Sandbox file {normalized!r} is not valid UTF-8"
            ) from exc
        return SandboxFileContents(
            path=normalized,
            content=content,
            byte_count=len(result.stdout),
        )

    async def write_text(
        self,
        session: SandboxSession,
        *,
        path: str,
        content: str,
        max_bytes: int,
    ) -> SandboxFileChange:
        self._require_session(session)
        workspace = session.workspace
        normalized = normalized_relative_path(path)
        raw = content.encode("utf-8")
        if len(raw) > max_bytes:
            raise SandboxOperationError(
                f"Refusing to write {len(raw)} bytes to {normalized!r}; the limit "
                f"is {max_bytes} bytes"
            )
        result = await self._docker_exec(
            session,
            self._guest(
                "write_text",
                f"{workspace.root}/{normalized}",
                str(max_bytes),
            ),
            cwd=workspace.root,
            stdin=raw,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(result, f"write sandbox file {normalized!r}")
        payload = _WriteResponse.model_validate_json(result.stdout)
        return SandboxFileChange(
            path=normalized,
            created=payload.created,
            byte_count=payload.byte_count,
        )

    async def replace_text(
        self,
        session: SandboxSession,
        *,
        path: str,
        expected: str,
        replacement: str,
        max_bytes: int,
    ) -> SandboxPatchResult:
        self._require_session(session)
        workspace = session.workspace
        normalized = normalized_relative_path(path)
        patch = json.dumps(
            {"expected": expected, "replacement": replacement},
            separators=(",", ":"),
        ).encode("utf-8")
        if len(patch) > max_bytes * 2 + 4_096:
            raise SandboxOperationError("Patch request exceeds its bounded input size")
        result = await self._docker_exec(
            session,
            self._guest(
                "replace_text",
                f"{workspace.root}/{normalized}",
                str(max_bytes),
            ),
            cwd=workspace.root,
            stdin=patch,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(result, f"patch sandbox file {normalized!r}")
        payload = _PatchResponse.model_validate_json(result.stdout)
        return SandboxPatchResult(
            path=normalized,
            replacements=payload.replacements,
            byte_count=payload.byte_count,
        )

    async def execute(
        self,
        session: SandboxSession,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        self._require_session(session)
        if request.network_mode.value == "package-index":
            self._require_dependency_command(request.argv)
            result = await self._run_dependency_helper(session, request)
        else:
            result = await self._docker_exec(
                session,
                (
                    "timeout",
                    "--signal=KILL",
                    f"{request.timeout_seconds}s",
                    *request.argv,
                ),
                cwd=f"{session.workspace.root}/{request.cwd}",
                stdin=request.stdin,
                timeout_seconds=request.timeout_seconds + 10.0,
                max_output_bytes=request.max_output_bytes,
            )
        return SandboxExecutionResult(
            exit_code=result.exit_code,
            stdout=result.stdout.decode("utf-8", errors="replace"),
            stderr=result.stderr.decode("utf-8", errors="replace"),
            duration_ms=result.duration_ms,
            output_truncated=result.output_truncated,
        )

    async def export_directory(
        self,
        session: SandboxSession,
        *,
        path: str,
        max_bytes: int,
    ) -> SandboxArchive:
        self._require_session(session)
        workspace = session.workspace
        normalized = normalized_relative_path(path)
        result = await self._docker_exec(
            session,
            self._guest(
                "archive_reviewable_tree",
                f"{workspace.root}/{normalized}",
            ),
            cwd=workspace.root,
            stdin=None,
            timeout_seconds=60.0,
            max_output_bytes=max_bytes,
        )
        self._require_success(result, f"archive sandbox directory {normalized!r}")
        if result.output_truncated or not result.stdout:
            raise SandboxOperationError(
                f"Archive for {normalized!r} is empty or exceeds {max_bytes} bytes"
            )
        return SandboxArchive(
            data=result.stdout,
            sha256=sha256(result.stdout).hexdigest(),
            byte_count=len(result.stdout),
        )

    async def import_directory(
        self,
        session: SandboxSession,
        *,
        path: str,
        archive: SandboxArchive,
    ) -> SandboxImportResult:
        read_source_bundle(archive.data)
        self._require_session(session)
        workspace = session.workspace
        normalized = normalized_relative_path(path)
        created = await self._docker_exec(
            session,
            ("mkdir", "-p", f"{workspace.root}/{normalized}"),
            cwd=workspace.root,
            stdin=None,
            timeout_seconds=30.0,
            max_output_bytes=65_536,
        )
        self._require_success(created, f"create import directory {normalized!r}")
        imported = await self._docker_exec(
            session,
            (
                "tar",
                "--no-same-owner",
                "--no-same-permissions",
                "-C",
                f"{workspace.root}/{normalized}",
                "-xzf",
                "-",
            ),
            cwd=workspace.root,
            stdin=archive.data,
            timeout_seconds=60.0,
            max_output_bytes=65_536,
        )
        self._require_success(imported, f"import archive into {normalized!r}")
        return SandboxImportResult(
            destination=normalized,
            archive_sha256=archive.sha256,
        )

    async def _docker_exec(
        self,
        session: SandboxSession,
        command: tuple[str, ...],
        *,
        cwd: str,
        stdin: bytes | None,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> _HostCommandResult:
        self._require_session(session)
        workspace = session.workspace
        guarded = (
            *self._guest(
                "fence_exec",
                self._session_marker(session),
                self._fence_value(session),
            ),
            *command,
        )
        return await self._raw_docker_exec(
            workspace,
            guarded,
            cwd=cwd,
            stdin=stdin,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    async def _raw_docker_exec(
        self,
        workspace: SandboxWorkspace,
        command: tuple[str, ...],
        *,
        cwd: str,
        stdin: bytes | None,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> _HostCommandResult:
        self._require_workspace(workspace)
        if workspace.provider != "docker-trusted-development":
            raise SandboxOperationError(
                f"Docker adapter cannot use {workspace.provider!r} workspace"
            )
        interactive = ("--interactive",) if stdin is not None else ()
        return await self._run_host(
            (
                self._settings.executable,
                "exec",
                *interactive,
                "--workdir",
                cwd,
                workspace.provider_environment_id,
                *command,
            ),
            stdin=stdin,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    async def _run_dependency_helper(
        self,
        session: SandboxSession,
        request: SandboxExecutionRequest,
    ) -> _HostCommandResult:
        workspace = session.workspace
        helper = f"grafy-deps-{sha256(session.provider_session_id.encode()).hexdigest()[:24]}"
        self._dependency_helpers[session.provider_session_id] = helper
        volume = f"{workspace.provider_environment_id}-workspace"
        result = await self._run_host(
            (
                self._settings.executable,
                "run",
                "--rm",
                "--name",
                helper,
                "--network",
                "bridge",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--cpus",
                str(self._settings.cpu_limit),
                "--memory",
                self._settings.memory_limit,
                "--pids-limit",
                str(self._settings.pids_limit),
                "--volume",
                f"{volume}:{workspace.root}",
                "--workdir",
                f"{workspace.root}/{request.cwd}",
                self._settings.image,
                *self._guest(
                    "fence_exec",
                    self._session_marker(session),
                    self._fence_value(session),
                ),
                "timeout",
                "--signal=KILL",
                f"{request.timeout_seconds}s",
                *request.argv,
            ),
            stdin=None,
            timeout_seconds=request.timeout_seconds + 15.0,
            max_output_bytes=request.max_output_bytes,
        )
        self._dependency_helpers.pop(session.provider_session_id, None)
        return result

    @staticmethod
    def _require_dependency_command(argv: tuple[str, ...]) -> None:
        allowed = (
            argv[:2] in {("uv", "add"), ("uv", "lock"), ("uv", "sync")}
            and argv[0] == "uv"
        )
        if not allowed:
            raise SandboxOperationError(
                "Trusted-development network phase permits only uv add/lock/sync"
            )

    def _require_workspace(self, workspace: SandboxWorkspace) -> None:
        if (
            workspace.provider != "docker-trusted-development"
            or _CONTAINER_NAME.fullmatch(workspace.provider_environment_id) is None
        ):
            raise SandboxOperationError("Docker sandbox workspace identity is invalid")

    def _require_session(self, session: SandboxSession) -> None:
        self._require_workspace(session.workspace)
        if (
            self._sessions.get(session.workspace.environment_id) != session
            or session.provider_session_id in self._revoked_sessions
        ):
            raise SandboxOperationError(
                f"Docker sandbox session {session.provider_session_id!r} is stale or revoked"
            )

    @staticmethod
    def _fence_value(session: SandboxSession) -> str:
        return (
            f"{session.execution_id}:{session.authority_token}:{session.fencing_token}"
        )

    @staticmethod
    def _session_marker(session: SandboxSession) -> str:
        return DockerSandboxWorkspace._session_marker_for(
            session.workspace,
            session.provider_session_id,
        )

    @staticmethod
    def _session_marker_for(
        workspace: SandboxWorkspace,
        provider_session_id: str,
    ) -> str:
        digest = sha256(provider_session_id.encode("utf-8")).hexdigest()
        if workspace.root == "/workspace":
            return f"{workspace.root}/.grafy-control/{digest}.fence"
        return f"/tmp/grafy-fence-{digest}"

    async def _run_host(
        self,
        argv: tuple[str, ...],
        *,
        stdin: bytes | None,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> _HostCommandResult:
        started = monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise SandboxOperationError(
                f"Could not start Docker operation {argv[1:3]!r}: {exc}"
            ) from exc
        if stdin is not None:
            if process.stdin is None:
                process.kill()
                await process.wait()
                raise SandboxOperationError("Docker operation did not expose stdin")
            process.stdin.write(stdin)
            await process.stdin.drain()
            process.stdin.close()
        if process.stdout is None or process.stderr is None:
            process.kill()
            await process.wait()
            raise SandboxOperationError(
                "Docker operation did not expose output streams"
            )
        stdout_task = asyncio.create_task(
            _read_limited(process.stdout, max_output_bytes)
        )
        stderr_task = asyncio.create_task(
            _read_limited(process.stderr, max_output_bytes)
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            await stdout_task
            await stderr_task
            raise SandboxOperationError(
                f"Docker operation {argv[1:3]!r} exceeded {timeout_seconds} seconds"
            ) from exc
        except BaseException:
            process.kill()
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        stdout, stdout_truncated = await stdout_task
        stderr, stderr_truncated = await stderr_task
        if len(stdout) + len(stderr) > max_output_bytes:
            stdout = stdout[:max_output_bytes]
            stderr = stderr[: max(0, max_output_bytes - len(stdout))]
            stdout_truncated = True
        return _HostCommandResult(
            exit_code=process.returncode or 0,
            stdout=stdout,
            stderr=stderr,
            duration_ms=int((monotonic() - started) * 1_000),
            output_truncated=stdout_truncated or stderr_truncated,
        )

    @staticmethod
    def _guest(name: str, *args: str) -> tuple[str, ...]:
        return ("python3", "-c", program(name), *args)

    @staticmethod
    def _require_success(result: _HostCommandResult, operation: str) -> None:
        if result.exit_code == 0:
            return
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise SandboxOperationError(
            f"Could not {operation}; exit code {result.exit_code}: {stderr}"
        )


async def _read_limited(
    stream: asyncio.StreamReader,
    limit: int,
) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    stored = 0
    truncated = False
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            break
        remaining = limit - stored
        if remaining > 0:
            kept = chunk[:remaining]
            chunks.append(kept)
            stored += len(kept)
        if len(chunk) > max(0, remaining):
            truncated = True
    return b"".join(chunks), truncated


__all__ = ["DockerSandboxSettings", "DockerSandboxWorkspace"]
