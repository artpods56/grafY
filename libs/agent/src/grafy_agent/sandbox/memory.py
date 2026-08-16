import asyncio
from gzip import GzipFile
from hashlib import sha256
from io import BytesIO
import tarfile
from time import monotonic
from typing import Protocol
from uuid import UUID

from grafy_agent.errors import SandboxOperationError
from grafy_agent.models import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxExecutionAuthority,
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
from grafy_core.source_bundles import read_source_bundle
from grafy_core.domain.agent_authoring import RuntimeLimits


class CommandHandler(Protocol):
    async def __call__(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult: ...


class InMemorySandboxWorkspace:
    """Deterministic sandbox fake; commands must be configured explicitly."""

    def __init__(self) -> None:
        self._workspaces: dict[UUID, SandboxWorkspace] = {}
        self._files: dict[UUID, dict[str, str]] = {}
        self._commands: dict[tuple[UUID, str, tuple[str, ...]], CommandHandler] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._active_sessions: dict[UUID, SandboxSession] = {}
        self._revoked_sessions: set[str] = set()
        self._active_commands: dict[str, set[asyncio.Task[SandboxExecutionResult]]] = {}
        self._artifacts: dict[str, tuple[SandboxRuntimeArtifact, dict[str, str]]] = {}
        self._runtime_limits: dict[UUID, RuntimeLimits] = {}

    def register_command(
        self,
        *,
        environment_id: UUID,
        cwd: str,
        argv: tuple[str, ...],
        handler: CommandHandler,
    ) -> None:
        self._commands[(environment_id, normalized_relative_path(cwd), argv)] = handler

    async def ensure_workspace(
        self,
        *,
        environment_id: UUID,
        provider_environment_id: str | None,
        profile_id: str,
    ) -> SandboxWorkspace:
        if profile_id.strip() == "":
            raise SandboxOperationError("Sandbox profile id must not be blank")
        existing = self._workspaces.get(environment_id)
        if existing is not None:
            if (
                provider_environment_id is not None
                and provider_environment_id != existing.provider_environment_id
            ):
                raise SandboxOperationError(
                    f"Environment {environment_id} is already bound to "
                    f"{existing.provider_environment_id!r}"
                )
            return existing
        workspace = SandboxWorkspace(
            environment_id=environment_id,
            provider="memory",
            provider_environment_id=(
                provider_environment_id or f"memory-{environment_id}"
            ),
            runtime_image_digest=sha256(b"memory-runtime-v1").hexdigest(),
            profile_digest=sha256(profile_id.encode("utf-8")).hexdigest(),
        )
        self._workspaces[environment_id] = workspace
        self._files[environment_id] = {}
        self._locks[environment_id] = asyncio.Lock()
        return workspace

    async def open_session(
        self,
        workspace: SandboxWorkspace,
        authority: SandboxExecutionAuthority,
    ) -> SandboxSession:
        self._environment_files(workspace)
        session = SandboxSession(
            workspace=workspace,
            execution_id=authority.execution_id,
            authority_token=authority.token,
            fencing_token=authority.fencing_token,
            provider_session_id=(
                f"grafy-{workspace.environment_id.hex}-{authority.execution_id.hex}"
            ),
        )
        async with self._lock(workspace):
            previous = self._active_sessions.get(workspace.environment_id)
            if previous is not None and previous != session:
                self._revoked_sessions.add(previous.provider_session_id)
            self._active_sessions[workspace.environment_id] = session
            self._revoked_sessions.discard(session.provider_session_id)
            self._active_commands.setdefault(session.provider_session_id, set())
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
        self._environment_files(workspace)
        provider_session_id = f"grafy-{workspace.environment_id.hex}-{execution_id.hex}"
        async with self._lock(workspace):
            self._revoked_sessions.add(provider_session_id)
            active = self._active_sessions.get(workspace.environment_id)
            if active is not None and active.execution_id == execution_id:
                del self._active_sessions[workspace.environment_id]
            tasks = tuple(self._active_commands.pop(provider_session_id, set()))
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return SandboxTerminationResult(
            provider_session_id=provider_session_id,
            terminated_execution_count=len(tasks),
        )

    async def destroy_workspace(self, workspace: SandboxWorkspace) -> None:
        async with self._lock(workspace):
            session = self._active_sessions.pop(workspace.environment_id, None)
            if session is not None:
                self._revoked_sessions.add(session.provider_session_id)
            self._workspaces.pop(workspace.environment_id, None)
            self._files.pop(workspace.environment_id, None)
            self._locks.pop(workspace.environment_id, None)
            self._runtime_limits.pop(workspace.environment_id, None)

    async def freeze_workspace(
        self,
        session: SandboxSession,
        *,
        artifact_name: str,
        source_digest: str,
    ) -> SandboxRuntimeArtifact:
        self._require_session(session)
        if len(source_digest) != 64:
            raise SandboxOperationError("Memory artifact source digest is invalid")
        async with self._lock(session.workspace):
            files = dict(self._environment_files(session.workspace))
        hasher = sha256()
        hasher.update(source_digest.encode("ascii"))
        hasher.update(session.workspace.runtime_image_digest.encode("ascii"))
        for path, content in sorted(files.items()):
            hasher.update(path.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(content.encode("utf-8"))
            hasher.update(b"\x00")
        artifact = SandboxRuntimeArtifact(
            provider="memory",
            reference=artifact_name,
            digest=hasher.hexdigest(),
        )
        existing = self._artifacts.get(artifact_name)
        if existing is not None and existing[0] != artifact:
            raise SandboxOperationError(
                f"Immutable memory runtime artifact {artifact_name!r} already exists"
            )
        self._artifacts[artifact_name] = (artifact, files)
        return artifact

    async def create_runtime_workspace(
        self,
        *,
        environment_id: UUID,
        artifact: SandboxRuntimeArtifact,
        limits: RuntimeLimits,
    ) -> SandboxWorkspace:
        if artifact.provider != "memory":
            raise SandboxOperationError(
                f"Memory adapter cannot start {artifact.provider!r} artifact"
            )
        try:
            stored_artifact, files = self._artifacts[artifact.reference]
        except KeyError as exc:
            raise SandboxOperationError(
                f"Memory runtime artifact {artifact.reference!r} does not exist"
            ) from exc
        if stored_artifact != artifact:
            raise SandboxOperationError(
                f"Memory runtime artifact {artifact.reference!r} digest mismatches"
            )
        workspace = SandboxWorkspace(
            environment_id=environment_id,
            provider="memory",
            provider_environment_id=f"memory-runtime-{environment_id}",
            runtime_image_digest=sha256(b"memory-runtime-v1").hexdigest(),
            profile_digest=sha256(artifact.digest.encode("ascii")).hexdigest(),
        )
        self._workspaces[environment_id] = workspace
        self._files[environment_id] = dict(files)
        self._locks[environment_id] = asyncio.Lock()
        self._runtime_limits[environment_id] = limits
        return workspace

    async def read_text(
        self,
        session: SandboxSession,
        *,
        path: str,
        max_bytes: int,
    ) -> SandboxFileContents:
        normalized = normalized_relative_path(path)
        self._require_session(session)
        workspace = session.workspace
        async with self._lock(workspace):
            self._require_session(session)
            files = self._environment_files(workspace)
            try:
                content = files[normalized]
            except KeyError as exc:
                raise FileNotFoundError(
                    f"Sandbox file {normalized!r} does not exist in environment "
                    f"{workspace.environment_id}"
                ) from exc
            byte_count = len(content.encode("utf-8"))
            if byte_count > max_bytes:
                raise SandboxOperationError(
                    f"Sandbox file {normalized!r} is {byte_count} bytes, exceeding "
                    f"the {max_bytes}-byte read limit"
                )
            return SandboxFileContents(
                path=normalized,
                content=content,
                byte_count=byte_count,
            )

    async def write_text(
        self,
        session: SandboxSession,
        *,
        path: str,
        content: str,
        max_bytes: int,
    ) -> SandboxFileChange:
        normalized = normalized_relative_path(path)
        byte_count = len(content.encode("utf-8"))
        if byte_count > max_bytes:
            raise SandboxOperationError(
                f"Refusing to write {byte_count} bytes to {normalized!r}; the limit "
                f"is {max_bytes} bytes"
            )
        self._require_session(session)
        workspace = session.workspace
        async with self._lock(workspace):
            self._require_session(session)
            files = self._environment_files(workspace)
            created = normalized not in files
            files[normalized] = content
        return SandboxFileChange(
            path=normalized,
            byte_count=byte_count,
            created=created,
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
        normalized = normalized_relative_path(path)
        self._require_session(session)
        workspace = session.workspace
        async with self._lock(workspace):
            self._require_session(session)
            files = self._environment_files(workspace)
            try:
                content = files[normalized]
            except KeyError as exc:
                raise FileNotFoundError(
                    f"Sandbox file {normalized!r} does not exist in environment "
                    f"{workspace.environment_id}"
                ) from exc
            occurrences = content.count(expected)
            if occurrences != 1:
                raise SandboxOperationError(
                    f"Patch for {normalized!r} expected exactly one match but found "
                    f"{occurrences}"
                )
            updated = content.replace(expected, replacement, 1)
            byte_count = len(updated.encode("utf-8"))
            if byte_count > max_bytes:
                raise SandboxOperationError(
                    f"Patched file {normalized!r} would exceed the {max_bytes}-byte limit"
                )
            files[normalized] = updated
        return SandboxPatchResult(
            path=normalized,
            replacements=1,
            byte_count=byte_count,
        )

    async def execute(
        self,
        session: SandboxSession,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        self._require_session(session)
        workspace = session.workspace
        limits = self._runtime_limits.get(workspace.environment_id)
        if limits is not None:
            if request.timeout_seconds > limits.wall_time_seconds:
                raise SandboxOperationError(
                    "Command exceeds the runtime wall-time limit"
                )
            if request.max_output_bytes > limits.output_bytes:
                raise SandboxOperationError("Command exceeds the runtime output limit")
            if request.stdin is not None and len(request.stdin) > limits.input_bytes:
                raise SandboxOperationError("Command exceeds the runtime input limit")
        key = (workspace.environment_id, request.cwd, request.argv)
        handler = self._commands.get(key)
        if handler is None:
            raise SandboxOperationError(
                f"No deterministic command result is registered for {request.argv!r} "
                f"in {request.cwd!r}"
            )
        started = monotonic()
        command: asyncio.Task[SandboxExecutionResult] | None = None
        try:
            command = asyncio.create_task(handler(request))
            self._active_commands[session.provider_session_id].add(command)
            result = await asyncio.wait_for(command, timeout=request.timeout_seconds)
        except TimeoutError as exc:
            raise SandboxOperationError(
                f"Command {request.argv!r} exceeded {request.timeout_seconds} seconds"
            ) from exc
        finally:
            if command is not None:
                self._active_commands.get(session.provider_session_id, set()).discard(
                    command
                )
        self._require_session(session)
        elapsed_ms = max(result.duration_ms, int((monotonic() - started) * 1_000))
        stdout_bytes = result.stdout.encode("utf-8")
        stderr_bytes = result.stderr.encode("utf-8")
        combined = stdout_bytes + stderr_bytes
        if len(combined) <= request.max_output_bytes:
            return result.model_copy(update={"duration_ms": elapsed_ms})
        kept_stdout = stdout_bytes[: request.max_output_bytes]
        remaining = request.max_output_bytes - len(kept_stdout)
        kept_stderr = stderr_bytes[:remaining]
        return SandboxExecutionResult(
            exit_code=result.exit_code,
            stdout=kept_stdout.decode("utf-8", errors="replace"),
            stderr=kept_stderr.decode("utf-8", errors="replace"),
            duration_ms=elapsed_ms,
            output_truncated=True,
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
        prefix = f"{normalized}/"
        async with self._lock(workspace):
            selected = sorted(
                (file_path.removeprefix(prefix), content)
                for file_path, content in self._environment_files(workspace).items()
                if file_path.startswith(prefix)
                and _allowed_export_path(file_path.removeprefix(prefix))
            )
        if not selected:
            raise FileNotFoundError(
                f"Sandbox directory {normalized!r} is empty or missing"
            )
        raw = BytesIO()
        with GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as bundle:
                for file_path, content in selected:
                    data = content.encode("utf-8")
                    info = tarfile.TarInfo(name=file_path)
                    info.size = len(data)
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.mode = 0o644
                    bundle.addfile(info, BytesIO(data))
        archive = raw.getvalue()
        if len(archive) > max_bytes:
            raise SandboxOperationError(
                f"Sandbox directory archive exceeds the {max_bytes}-byte limit"
            )
        return SandboxArchive(
            data=archive,
            sha256=sha256(archive).hexdigest(),
            byte_count=len(archive),
        )

    async def import_directory(
        self,
        session: SandboxSession,
        *,
        path: str,
        archive: SandboxArchive,
    ) -> SandboxImportResult:
        index = read_source_bundle(archive.data)
        self._require_session(session)
        workspace = session.workspace
        normalized = normalized_relative_path(path)
        imported = {
            f"{normalized}/{item.path}": item.content.decode("utf-8")
            for item in index.files
        }
        async with self._lock(workspace):
            self._environment_files(workspace).update(imported)
        return SandboxImportResult(
            destination=normalized,
            archive_sha256=archive.sha256,
        )

    def _require_session(self, session: SandboxSession) -> None:
        self._environment_files(session.workspace)
        active = self._active_sessions.get(session.workspace.environment_id)
        if active != session or session.provider_session_id in self._revoked_sessions:
            raise SandboxOperationError(
                f"Sandbox session {session.provider_session_id!r} is stale or revoked"
            )

    def _environment_files(self, workspace: SandboxWorkspace) -> dict[str, str]:
        registered = self._workspaces.get(workspace.environment_id)
        if registered != workspace:
            raise SandboxOperationError(
                f"Sandbox workspace {workspace.environment_id} is unknown or stale"
            )
        return self._files[workspace.environment_id]

    def _lock(self, workspace: SandboxWorkspace) -> asyncio.Lock:
        self._environment_files(workspace)
        return self._locks[workspace.environment_id]


def _allowed_export_path(path: str) -> bool:
    return path in {"pyproject.toml", "uv.lock", "node.json"} or (
        (path.startswith("src/") or path.startswith("tests/")) and path.endswith(".py")
    )


__all__ = ["CommandHandler", "InMemorySandboxWorkspace"]
