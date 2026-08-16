import asyncio
import base64
from hashlib import sha256
import json
from math import ceil
import re
import shlex
from time import monotonic
from typing import ClassVar
from uuid import UUID, uuid4

from daytona import (
    AsyncDaytona,
    AsyncSandbox,
    CreateSandboxFromSnapshotParams,
    DaytonaConfig,
    DaytonaConflictError,
    DaytonaNotFoundError,
    SessionExecuteRequest,
)
from daytona.common.snapshot import Snapshot
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_agent.errors import AgentConfigurationError, SandboxOperationError
from grafy_agent.models import (
    SandboxArchive,
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxFileChange,
    SandboxFileContents,
    SandboxImportResult,
    SandboxNetworkMode,
    SandboxPatchResult,
    SandboxRuntimeArtifact,
    SandboxSession,
    SandboxTerminationResult,
    SandboxWorkspace,
    normalized_relative_path,
)
from grafy_core.source_bundles import read_source_bundle
from grafy_core.domain.agent_authoring import RuntimeLimits


_READ_SCRIPT = """import pathlib,sys
marker=pathlib.Path(sys.argv[1]); expected=sys.argv[2]
if marker.read_text(encoding='utf-8')!=expected: raise RuntimeError('sandbox lease fence is stale')
p=pathlib.Path(sys.argv[3]); limit=int(sys.argv[4]); data=p.read_bytes()
if len(data)>limit: raise RuntimeError(f'file exceeds {limit} bytes')
sys.stdout.buffer.write(data)
"""
_WRITE_SCRIPT = """import json,os,pathlib,sys,tempfile
marker=pathlib.Path(sys.argv[1]); expected=sys.argv[2]
if marker.read_text(encoding='utf-8')!=expected: raise RuntimeError('sandbox lease fence is stale')
source=pathlib.Path(sys.argv[3]); p=pathlib.Path(sys.argv[4]); limit=int(sys.argv[5])
data=source.read_bytes()
if len(data)>limit: raise RuntimeError(f'content exceeds {limit} bytes')
p.parent.mkdir(parents=True,exist_ok=True); created=not p.exists()
fd,tmp=tempfile.mkstemp(dir=p.parent,prefix=f'.{p.name}.')
try:
 os.write(fd,data); os.fsync(fd); os.close(fd); os.replace(tmp,p)
except BaseException:
 try: os.close(fd)
 except OSError: pass
 try: os.unlink(tmp)
 except OSError: pass
 raise
print(json.dumps({'created':created,'byte_count':len(data)}))
"""
_PATCH_SCRIPT = """import json,os,pathlib,sys,tempfile
marker=pathlib.Path(sys.argv[1]); expected=sys.argv[2]
if marker.read_text(encoding='utf-8')!=expected: raise RuntimeError('sandbox lease fence is stale')
request=json.loads(pathlib.Path(sys.argv[3]).read_text(encoding='utf-8'))
p=pathlib.Path(sys.argv[4]); limit=int(sys.argv[5]); data=p.read_text(encoding='utf-8')
expected_text=request['expected']; replacement=request['replacement']; count=data.count(expected_text)
if count!=1: raise RuntimeError(f'expected exactly one match but found {count}')
raw=data.replace(expected_text,replacement,1).encode()
if len(raw)>limit: raise RuntimeError(f'patched file exceeds {limit} bytes')
fd,tmp=tempfile.mkstemp(dir=p.parent,prefix=f'.{p.name}.')
try:
 os.write(fd,raw); os.fsync(fd); os.close(fd); os.replace(tmp,p)
except BaseException:
 try: os.close(fd)
 except OSError: pass
 try: os.unlink(tmp)
 except OSError: pass
 raise
print(json.dumps({'replacements':1,'byte_count':len(raw)}))
"""
_EXEC_SCRIPT = """import base64,json,os,pathlib,selectors,signal,subprocess,sys,time
marker=pathlib.Path(sys.argv[1]); expected=sys.argv[2]
if marker.read_text(encoding='utf-8')!=expected: raise RuntimeError('sandbox lease fence is stale')
argv=json.loads(base64.urlsafe_b64decode(sys.argv[3]+'===')); cwd=sys.argv[4]
timeout=float(sys.argv[5]); limit=int(sys.argv[6]); stdin_path=sys.argv[7]; started=time.monotonic()
stdin=open(stdin_path,'rb') if stdin_path!='-' else subprocess.DEVNULL
process=subprocess.Popen(argv,cwd=cwd,stdin=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
selector=selectors.DefaultSelector(); stdout=bytearray(); stderr=bytearray(); truncated=False; killed=False
selector.register(process.stdout,selectors.EVENT_READ,'stdout'); selector.register(process.stderr,selectors.EVENT_READ,'stderr')
deadline=started+timeout
while selector.get_map():
 if time.monotonic()>=deadline and not killed:
  os.killpg(process.pid,signal.SIGKILL); killed=True
 for key,_ in selector.select(.1):
  chunk=os.read(key.fileobj.fileno(),65536)
  if not chunk: selector.unregister(key.fileobj); continue
  remaining=max(0,limit-len(stdout)-len(stderr))
  if remaining: (stdout if key.data=='stdout' else stderr).extend(chunk[:remaining])
  if len(chunk)>remaining and not killed:
   truncated=True; os.killpg(process.pid,signal.SIGKILL); killed=True
process.wait();
if stdin_path!='-': stdin.close()
print(json.dumps({'exit_code':process.returncode,'stdout':base64.b64encode(stdout).decode(),'stderr':base64.b64encode(stderr).decode(),'duration_ms':int((time.monotonic()-started)*1000),'output_truncated':truncated},separators=(',',':')))
"""


class _WriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    created: bool
    byte_count: int = Field(ge=0)


class _PatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replacements: int = Field(ge=1)
    byte_count: int = Field(ge=0)


class _ExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int = Field(ge=0)
    output_truncated: bool


class DaytonaSandboxSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="GRAFY_AGENT_DAYTONA_", extra="ignore"
    )
    api_key: SecretStr | None = None
    api_url: str = "https://app.daytona.io/api"
    target: str | None = None
    auto_pause_minutes: int = Field(default=15, ge=0, le=10_080)
    profile_snapshots: dict[str, str] = {}
    package_index_domains: tuple[str, ...] = (
        "pypi.org",
        "files.pythonhosted.org",
    )

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("Daytona API URL must use HTTPS")
        return normalized

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Daytona target must not be blank")
        return normalized

    @field_validator("profile_snapshots")
    @classmethod
    def validate_profiles(cls, value: dict[str, str]) -> dict[str, str]:
        profiles: dict[str, str] = {}
        for profile_id, snapshot in value.items():
            normalized_id = profile_id.strip()
            normalized_snapshot = snapshot.strip()
            if normalized_id == "" or normalized_snapshot == "":
                raise ValueError("Daytona profile and snapshot names must not be blank")
            profiles[normalized_id] = normalized_snapshot
        return profiles

    @field_validator("package_index_domains")
    @classmethod
    def validate_domains(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        domains: list[str] = []
        for item in value:
            domain = item.strip().lower()
            if domain == "" or "/" in domain or ":" in domain:
                raise ValueError("Daytona package-index entries must be hostnames")
            domains.append(domain)
        if not domains:
            raise ValueError("At least one package-index hostname is required")
        return tuple(sorted(set(domains)))


class DaytonaSandboxWorkspace:
    """Production sandbox adapter with provider sessions and default-deny egress."""

    def __init__(
        self,
        settings: DaytonaSandboxSettings,
        *,
        client: AsyncDaytona | None = None,
    ) -> None:
        if settings.api_key is None and client is None:
            raise AgentConfigurationError(
                "Daytona sandboxing requires GRAFY_AGENT_DAYTONA_API_KEY"
            )
        if not settings.profile_snapshots:
            raise AgentConfigurationError(
                "Daytona sandboxing requires GRAFY_AGENT_DAYTONA_PROFILE_SNAPSHOTS"
            )
        self._settings = settings
        self._client = client or AsyncDaytona(
            DaytonaConfig(
                api_key=settings.api_key.get_secret_value()
                if settings.api_key is not None
                else None,
                api_url=settings.api_url,
                target=settings.target,
            )
        )
        self._sandboxes: dict[str, AsyncSandbox] = {}
        self._provision_locks: dict[UUID, asyncio.Lock] = {}
        self._sessions: dict[UUID, SandboxSession] = {}
        self._revoked_sessions: set[str] = set()
        self._network_locks: dict[UUID, asyncio.Lock] = {}

    async def close(self) -> None:
        await self._client.close()

    async def ensure_workspace(
        self,
        *,
        environment_id: UUID,
        provider_environment_id: str | None,
        profile_id: str,
    ) -> SandboxWorkspace:
        snapshot, runtime_digest, profile_digest = await self._resolve_profile(
            profile_id
        )
        sandbox_id = provider_environment_id or f"grafy-agent-{environment_id.hex}"
        lock = self._provision_locks.setdefault(environment_id, asyncio.Lock())
        async with lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is None:
                try:
                    sandbox = await self._client.get(sandbox_id)
                except DaytonaNotFoundError:
                    if provider_environment_id is not None:
                        raise SandboxOperationError(
                            f"Daytona environment {provider_environment_id!r} no longer exists"
                        ) from None
                    sandbox = await self._client.create(
                        CreateSandboxFromSnapshotParams(
                            name=sandbox_id,
                            snapshot=snapshot.name,
                            language="python",
                            labels={
                                "grafy.environment_id": str(environment_id),
                                "grafy.profile_id": profile_id,
                                "grafy.profile_digest": profile_digest,
                            },
                            public=False,
                            auto_pause_interval=self._settings.auto_pause_minutes,
                            auto_delete_interval=-1,
                            network_block_all=True,
                            secrets={},
                        )
                    )
                if sandbox.snapshot not in {snapshot.id, snapshot.name, snapshot.ref}:
                    raise SandboxOperationError(
                        f"Daytona environment {sandbox.id!r} uses the wrong profile snapshot"
                    )
                if sandbox.state is not None and sandbox.state.value != "started":
                    await sandbox.start(timeout=60)
                await self._block_network(sandbox)
                self._sandboxes[sandbox.id] = sandbox
                self._sandboxes[sandbox_id] = sandbox
        return SandboxWorkspace(
            environment_id=environment_id,
            provider="daytona",
            provider_environment_id=sandbox.id,
            root="workspace",
            runtime_image_digest=runtime_digest,
            profile_digest=profile_digest,
        )

    async def open_session(
        self,
        workspace: SandboxWorkspace,
        authority: SandboxExecutionAuthority,
    ) -> SandboxSession:
        sandbox = await self._sandbox(workspace)
        await self._block_network(sandbox)
        session = SandboxSession(
            workspace=workspace,
            execution_id=authority.execution_id,
            authority_token=authority.token,
            fencing_token=authority.fencing_token,
            provider_session_id=(
                f"grafy-{workspace.environment_id.hex}-{authority.execution_id.hex}"
            ),
        )
        try:
            await sandbox.process.delete_session(session.provider_session_id)
        except DaytonaNotFoundError:
            pass
        await sandbox.process.create_session(session.provider_session_id)
        try:
            await sandbox.fs.create_folder(workspace.root, "755")
        except DaytonaConflictError:
            pass
        await sandbox.fs.upload_file(
            self._fence_value(session).encode(),
            self._session_marker(session),
            timeout=30,
        )
        previous = self._sessions.get(workspace.environment_id)
        if previous is not None and previous != session:
            self._revoked_sessions.add(previous.provider_session_id)
        self._sessions[workspace.environment_id] = session
        self._revoked_sessions.discard(session.provider_session_id)
        return session

    async def terminate_session(
        self, session: SandboxSession
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
        sandbox = await self._sandbox(workspace)
        provider_session_id = f"grafy-{workspace.environment_id.hex}-{execution_id.hex}"
        self._revoked_sessions.add(provider_session_id)
        await sandbox.fs.upload_file(
            f"revoked:{provider_session_id}".encode(),
            self._session_marker_for(provider_session_id),
            timeout=30,
        )
        terminated = 0
        try:
            provider_session = await sandbox.process.get_session(provider_session_id)
            terminated = sum(
                1 for command in provider_session.commands if command.exit_code is None
            )
        except DaytonaNotFoundError:
            pass

        # Provider sessions are an API grouping, not an operating-system kill
        # boundary. Stop the complete sandbox so detached descendants cannot
        # outlive the database lease, then restart the reusable environment.
        try:
            await sandbox.stop(timeout=60, force=True)
            if sandbox.state is None or sandbox.state.value != "stopped":
                raise SandboxOperationError(
                    f"Daytona environment {sandbox.id!r} did not stop during revocation"
                )
            await sandbox.start(timeout=60)
            await self._block_network(sandbox)
            try:
                await sandbox.process.delete_session(provider_session_id)
            except DaytonaNotFoundError:
                pass
            await sandbox.fs.delete_file(
                self._session_marker_for(provider_session_id)
            )
        except Exception as exc:
            raise SandboxOperationError(
                f"Daytona execution {provider_session_id!r} could not be revoked"
            ) from exc
        active = self._sessions.get(workspace.environment_id)
        if active is not None and active.execution_id == execution_id:
            del self._sessions[workspace.environment_id]
        return SandboxTerminationResult(
            provider_session_id=provider_session_id,
            terminated_execution_count=terminated,
        )

    async def destroy_workspace(self, workspace: SandboxWorkspace) -> None:
        sandbox = await self._sandbox(workspace)
        await sandbox.delete(timeout=60, wait=True)
        self._sandboxes.pop(workspace.provider_environment_id, None)
        self._sessions.pop(workspace.environment_id, None)

    async def freeze_workspace(
        self,
        session: SandboxSession,
        *,
        artifact_name: str,
        source_digest: str,
    ) -> SandboxRuntimeArtifact:
        self._require_session(session)
        sandbox = await self._sandbox(session.workspace)
        await self._block_network(sandbox)
        expected_identity = sha256(
            (
                f"{source_digest}:{session.workspace.runtime_image_digest}:"
                f"{session.workspace.profile_digest}"
            ).encode("ascii")
        ).hexdigest()
        if artifact_name != f"grafy-node-{expected_identity}":
            raise SandboxOperationError(
                "Daytona runtime artifact name does not match its provenance"
            )
        snapshot_name = f"{artifact_name}-{uuid4().hex[:12]}"
        marker = self._session_marker(session)
        await sandbox.fs.delete_file(marker)
        try:
            # Snapshot only after the provider has killed every process in the
            # sandbox. The verifier uses wheel-only sync in this clean workspace,
            # so no source-build hook runs before this stop boundary.
            await sandbox.stop(timeout=60, force=True)
            if sandbox.state is None or sandbox.state.value != "stopped":
                raise SandboxOperationError(
                    f"Daytona environment {sandbox.id!r} did not stop before snapshot"
                )
            await sandbox.create_snapshot(snapshot_name, timeout=600)
            snapshot = await self._client.snapshot.get(snapshot_name)
        finally:
            if sandbox.state is None or sandbox.state.value != "started":
                await sandbox.start(timeout=60)
            await self._block_network(sandbox)
            await sandbox.fs.upload_file(
                self._fence_value(session).encode(),
                marker,
                timeout=30,
            )
        return SandboxRuntimeArtifact(
            provider="daytona",
            reference=snapshot.name,
            digest=self._snapshot_digest(snapshot),
        )

    async def create_runtime_workspace(
        self,
        *,
        environment_id: UUID,
        artifact: SandboxRuntimeArtifact,
        limits: RuntimeLimits,
    ) -> SandboxWorkspace:
        if artifact.provider != "daytona":
            raise SandboxOperationError(
                f"Daytona adapter cannot start {artifact.provider!r} runtime artifact"
            )
        snapshot = await self._client.snapshot.get(artifact.reference)
        if self._snapshot_digest(snapshot) != artifact.digest:
            raise SandboxOperationError("Daytona runtime artifact digest mismatch")
        snapshot_cpu_millis = int(float(snapshot.cpu) * 1_000)
        snapshot_memory_megabytes = int(float(snapshot.mem) * 1_024)
        snapshot_disk_bytes = int(float(snapshot.disk) * 1_073_741_824)
        if snapshot_cpu_millis > limits.cpu_millis:
            raise SandboxOperationError(
                "Daytona runtime profile exceeds the approved CPU ceiling"
            )
        if snapshot_memory_megabytes > limits.memory_megabytes:
            raise SandboxOperationError(
                "Daytona runtime profile exceeds the approved memory ceiling"
            )
        if snapshot_disk_bytes > (
            limits.persistent_disk_bytes + limits.temporary_disk_bytes
        ):
            raise SandboxOperationError(
                "Daytona runtime profile exceeds the approved disk ceiling"
            )
        sandbox = await self._client.create(
            CreateSandboxFromSnapshotParams(
                name=f"grafy-runtime-{environment_id.hex}",
                snapshot=snapshot.name,
                language="python",
                labels={"grafy.runtime_artifact_digest": artifact.digest},
                public=False,
                ephemeral=True,
                ttl_minutes=60,
                network_block_all=True,
                secrets={},
            )
        )
        await self._block_network(sandbox)
        self._sandboxes[sandbox.id] = sandbox
        return SandboxWorkspace(
            environment_id=environment_id,
            provider="daytona",
            provider_environment_id=sandbox.id,
            root="workspace",
            runtime_image_digest=artifact.digest,
            profile_digest=sha256(
                f"daytona-runtime:{snapshot.id}:{artifact.digest}".encode()
            ).hexdigest(),
        )

    async def read_text(
        self, session: SandboxSession, *, path: str, max_bytes: int
    ) -> SandboxFileContents:
        self._require_session(session)
        normalized = normalized_relative_path(path)
        response = await self._session_command(
            session,
            (
                "python3",
                "-c",
                _READ_SCRIPT,
                self._session_marker(session),
                self._fence_value(session),
                f"{session.workspace.root}/{normalized}",
                str(max_bytes),
            ),
            cwd=session.workspace.root,
            timeout=30,
        )
        if response.exit_code != 0:
            if "FileNotFoundError" in response.stderr:
                raise FileNotFoundError(f"Sandbox file {normalized!r} does not exist")
            raise SandboxOperationError(
                f"Could not read Daytona sandbox file {normalized!r}: {response.stderr}"
            )
        raw = response.stdout.encode()
        if len(raw) > max_bytes:
            raise SandboxOperationError(f"Sandbox file {normalized!r} is too large")
        return SandboxFileContents(
            path=normalized, content=response.stdout, byte_count=len(raw)
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
        normalized = normalized_relative_path(path)
        raw = content.encode()
        if len(raw) > max_bytes:
            raise SandboxOperationError(f"Write to {normalized!r} exceeds its limit")
        sandbox = await self._sandbox(session.workspace)
        temporary = f"/tmp/grafy-write-{uuid4().hex}"
        await sandbox.fs.upload_file(raw, temporary, timeout=30)
        try:
            response = await self._session_command(
                session,
                (
                    "python3",
                    "-c",
                    _WRITE_SCRIPT,
                    self._session_marker(session),
                    self._fence_value(session),
                    temporary,
                    f"{session.workspace.root}/{normalized}",
                    str(max_bytes),
                ),
                cwd=session.workspace.root,
                timeout=30,
            )
        finally:
            await sandbox.fs.delete_file(temporary)
        if response.exit_code != 0:
            raise SandboxOperationError(
                f"Could not write {normalized!r}: {response.stderr}"
            )
        payload = _WriteResponse.model_validate_json(response.stdout)
        return SandboxFileChange(
            path=normalized, byte_count=payload.byte_count, created=payload.created
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
        normalized = normalized_relative_path(path)
        patch = json.dumps(
            {"expected": expected, "replacement": replacement}, separators=(",", ":")
        ).encode()
        if len(patch) > max_bytes * 2 + 4_096:
            raise SandboxOperationError("Patch request exceeds its input limit")
        sandbox = await self._sandbox(session.workspace)
        temporary = f"/tmp/grafy-patch-{uuid4().hex}.json"
        await sandbox.fs.upload_file(patch, temporary, timeout=30)
        try:
            response = await self._session_command(
                session,
                (
                    "python3",
                    "-c",
                    _PATCH_SCRIPT,
                    self._session_marker(session),
                    self._fence_value(session),
                    temporary,
                    f"{session.workspace.root}/{normalized}",
                    str(max_bytes),
                ),
                cwd=session.workspace.root,
                timeout=30,
            )
        finally:
            await sandbox.fs.delete_file(temporary)
        if response.exit_code != 0:
            raise SandboxOperationError(
                f"Could not patch {normalized!r}: {response.stderr}"
            )
        payload = _PatchResponse.model_validate_json(response.stdout)
        return SandboxPatchResult(
            path=normalized,
            replacements=payload.replacements,
            byte_count=payload.byte_count,
        )

    async def execute(
        self, session: SandboxSession, request: SandboxExecutionRequest
    ) -> SandboxExecutionResult:
        self._require_session(session)
        if request.network_mode is SandboxNetworkMode.PACKAGE_INDEX:
            self._require_dependency_command(request.argv)
            lock = self._network_locks.setdefault(
                session.workspace.environment_id, asyncio.Lock()
            )
            async with lock:
                sandbox = await self._sandbox(session.workspace)
                expected = ",".join(self._settings.package_index_domains)
                await sandbox.update_network_settings(domain_allow_list=expected)
                if sandbox.network_block_all or sandbox.domain_allow_list != expected:
                    raise SandboxOperationError(
                        "Daytona did not enforce package-index-only egress"
                    )
                try:
                    return await self._execute_bounded(session, request)
                finally:
                    await self._reset_after_network_phase(session)
        sandbox = await self._sandbox(session.workspace)
        if not sandbox.network_block_all:
            raise SandboxOperationError("Refusing command while Daytona egress is open")
        return await self._execute_bounded(session, request)

    async def export_directory(
        self, session: SandboxSession, *, path: str, max_bytes: int
    ) -> SandboxArchive:
        self._require_session(session)
        normalized = normalized_relative_path(path)
        sandbox = await self._sandbox(session.workspace)
        temporary = f"/tmp/grafy-export-{uuid4().hex}.tar.gz"
        response = await self._session_command(
            session,
            (
                "tar",
                "--sort=name",
                "--mtime=@0",
                "--owner=0",
                "--group=0",
                "--numeric-owner",
                "-C",
                f"{session.workspace.root}/{normalized}",
                "-czf",
                temporary,
                "pyproject.toml",
                "uv.lock",
                "node.json",
                "src",
                "tests",
            ),
            cwd=session.workspace.root,
            timeout=60,
        )
        if response.exit_code != 0:
            raise SandboxOperationError(
                f"Could not archive {normalized!r}: {response.stderr}"
            )
        try:
            raw = await sandbox.fs.download_file(temporary, timeout=60)
        finally:
            await sandbox.fs.delete_file(temporary)
        if not raw or len(raw) > max_bytes:
            raise SandboxOperationError(f"Archive for {normalized!r} exceeds its limit")
        archive = SandboxArchive(
            data=raw, sha256=sha256(raw).hexdigest(), byte_count=len(raw)
        )
        read_source_bundle(archive.data)
        return archive

    async def import_directory(
        self,
        session: SandboxSession,
        *,
        path: str,
        archive: SandboxArchive,
    ) -> SandboxImportResult:
        read_source_bundle(archive.data)
        self._require_session(session)
        normalized = normalized_relative_path(path)
        sandbox = await self._sandbox(session.workspace)
        temporary = f"/tmp/grafy-import-{uuid4().hex}.tar.gz"
        await sandbox.fs.upload_file(archive.data, temporary, timeout=60)
        try:
            created = await self._session_command(
                session,
                ("mkdir", "-p", f"{session.workspace.root}/{normalized}"),
                cwd=session.workspace.root,
                timeout=30,
            )
            if created.exit_code != 0:
                raise SandboxOperationError(
                    f"Could not create import path: {created.stderr}"
                )
            response = await self._session_command(
                session,
                (
                    "tar",
                    "--no-same-owner",
                    "--no-same-permissions",
                    "-C",
                    f"{session.workspace.root}/{normalized}",
                    "-xzf",
                    temporary,
                ),
                cwd=session.workspace.root,
                timeout=60,
            )
        finally:
            await sandbox.fs.delete_file(temporary)
        if response.exit_code != 0:
            raise SandboxOperationError(f"Could not import archive: {response.stderr}")
        return SandboxImportResult(
            destination=normalized, archive_sha256=archive.sha256
        )

    async def _execute_bounded(
        self, session: SandboxSession, request: SandboxExecutionRequest
    ) -> SandboxExecutionResult:
        argv_document = base64.urlsafe_b64encode(
            json.dumps(list(request.argv), separators=(",", ":")).encode()
        ).decode()
        sandbox = await self._sandbox(session.workspace)
        stdin_path = "-"
        if request.stdin is not None:
            stdin_path = f"/tmp/grafy-stdin-{uuid4().hex}"
            await sandbox.fs.upload_file(request.stdin, stdin_path, timeout=60)
        try:
            response = await self._session_command(
                session,
                (
                    "python3",
                    "-c",
                    _EXEC_SCRIPT,
                    self._session_marker(session),
                    self._fence_value(session),
                    argv_document,
                    f"{session.workspace.root}/{request.cwd}",
                    str(request.timeout_seconds),
                    str(request.max_output_bytes),
                    stdin_path,
                ),
                cwd=session.workspace.root,
                timeout=ceil(request.timeout_seconds + 10),
            )
        finally:
            if stdin_path != "-":
                await sandbox.fs.delete_file(stdin_path)
        if response.exit_code != 0:
            return SandboxExecutionResult(
                exit_code=response.exit_code,
                stdout="",
                stderr=response.stderr,
                duration_ms=response.duration_ms,
            )
        payload = _ExecutionResponse.model_validate_json(response.stdout)
        return SandboxExecutionResult(
            exit_code=payload.exit_code,
            stdout=base64.b64decode(payload.stdout).decode(errors="replace"),
            stderr=base64.b64decode(payload.stderr).decode(errors="replace"),
            duration_ms=payload.duration_ms,
            output_truncated=payload.output_truncated,
        )

    async def _session_command(
        self,
        session: SandboxSession,
        argv: tuple[str, ...],
        *,
        cwd: str,
        timeout: int,
    ) -> SandboxExecutionResult:
        self._require_session(session)
        sandbox = await self._sandbox(session.workspace)
        started = monotonic()
        response = await sandbox.process.execute_session_command(
            session.provider_session_id,
            SessionExecuteRequest(command=shlex.join(argv), run_async=False),
            timeout=timeout,
        )
        return SandboxExecutionResult(
            exit_code=response.exit_code if response.exit_code is not None else -1,
            stdout=response.stdout or "",
            stderr=response.stderr or "",
            duration_ms=int((monotonic() - started) * 1_000),
        )

    async def _reset_after_network_phase(self, session: SandboxSession) -> None:
        sandbox = await self._sandbox(session.workspace)
        try:
            await sandbox.process.delete_session(session.provider_session_id)
            await self._block_network(sandbox)
            await sandbox.process.create_session(session.provider_session_id)
        except Exception as exc:
            self._revoked_sessions.add(session.provider_session_id)
            await sandbox.stop(timeout=60, force=True)
            raise SandboxOperationError(
                "Daytona dependency phase could not reset to blocked egress"
            ) from exc

    async def _block_network(self, sandbox: AsyncSandbox) -> None:
        await sandbox.update_network_settings(network_block_all=True)
        if not sandbox.network_block_all:
            raise SandboxOperationError("Daytona did not enforce blocked egress")

    async def _resolve_profile(self, profile_id: str) -> tuple[Snapshot, str, str]:
        normalized = profile_id.strip()
        try:
            snapshot_name = self._settings.profile_snapshots[normalized]
        except KeyError as exc:
            raise SandboxOperationError(
                f"Daytona profile {normalized!r} is not configured"
            ) from exc
        snapshot = await self._client.snapshot.get(snapshot_name)
        runtime_digest = self._snapshot_digest(snapshot)
        profile_document = json.dumps(
            {
                "snapshot_id": snapshot.id,
                "snapshot_name": snapshot.name,
                "snapshot_ref": snapshot.ref,
                "image_name": snapshot.image_name,
                "cpu": snapshot.cpu,
                "memory": snapshot.mem,
                "disk": snapshot.disk,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return snapshot, runtime_digest, sha256(profile_document).hexdigest()

    @staticmethod
    def _snapshot_digest(snapshot: Snapshot) -> str:
        reference = snapshot.ref
        if reference is None and snapshot.build_info is not None:
            reference = snapshot.build_info.snapshot_ref
        if reference is None or reference.strip() == "":
            raise SandboxOperationError(
                f"Daytona snapshot {snapshot.name!r} has no immutable reference"
            )
        match = re.search(r"sha256:([0-9a-f]{64})", reference)
        if match is not None:
            return match.group(1)
        return sha256(
            f"daytona-snapshot:{snapshot.id}:{reference}".encode()
        ).hexdigest()

    async def _sandbox(self, workspace: SandboxWorkspace) -> AsyncSandbox:
        if workspace.provider != "daytona":
            raise SandboxOperationError(
                f"Daytona adapter cannot use {workspace.provider!r} workspace"
            )
        sandbox = self._sandboxes.get(workspace.provider_environment_id)
        if sandbox is None:
            try:
                sandbox = await self._client.get(workspace.provider_environment_id)
            except DaytonaNotFoundError as exc:
                raise SandboxOperationError(
                    f"Daytona environment {workspace.provider_environment_id!r} is gone"
                ) from exc
            self._sandboxes[workspace.provider_environment_id] = sandbox
        return sandbox

    def _require_session(self, session: SandboxSession) -> None:
        if (
            self._sessions.get(session.workspace.environment_id) != session
            or session.provider_session_id in self._revoked_sessions
        ):
            raise SandboxOperationError(
                f"Daytona session {session.provider_session_id!r} is stale or revoked"
            )

    @staticmethod
    def _fence_value(session: SandboxSession) -> str:
        return (
            f"{session.execution_id}:{session.authority_token}:{session.fencing_token}"
        )

    @staticmethod
    def _session_marker(session: SandboxSession) -> str:
        return DaytonaSandboxWorkspace._session_marker_for(session.provider_session_id)

    @staticmethod
    def _session_marker_for(provider_session_id: str) -> str:
        digest = sha256(provider_session_id.encode("utf-8")).hexdigest()
        return f"/tmp/grafy-fence-{digest}"

    @staticmethod
    def _require_dependency_command(argv: tuple[str, ...]) -> None:
        if argv[:2] not in {("uv", "add"), ("uv", "lock"), ("uv", "sync")}:
            raise SandboxOperationError(
                "Daytona package-index phase permits only uv add/lock/sync"
            )


__all__ = ["DaytonaSandboxSettings", "DaytonaSandboxWorkspace"]
