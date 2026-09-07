"""Hardened local Docker owner for isolated Plugin guest invocations."""

import asyncio
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
import logging
from pathlib import Path, PurePosixPath
import shutil
import tarfile
from tempfile import TemporaryDirectory
from typing import Protocol, cast, final, override
from uuid import UUID

from pydantic import StrictStr, TypeAdapter, ValidationError

from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginReleaseIdentity,
    PluginReleaseScope,
    PluginRuntimeArtifact,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginInvocationRequest,
)
from grafy_core.runtime.plugin_protocol import (
    PluginFailureCode,
    PluginInvocationEnvelope,
    PluginInvocationLimits,
)

from grafy_api.plugin_admission import (
    ISOLATED_BASE_CAPABILITIES,
    ReleaseExecutionAdmission,
    ReleaseExecutionRejection,
    ReleaseExecutionRoute,
    isolated_release_admission,
)
from grafy_api.plugin_egress import (
    PLUGIN_EGRESS_BROKER_CONFIG_VERSION,
    PLUGIN_EGRESS_BROKER_CONFIG_VERSION_LABEL,
    PLUGIN_HTTP_PROXY_PORT,
    PluginEgressAddressScope,
    PluginEgressBrokerPlan,
    PluginEgressBrokerPolicy,
    PluginEgressDestination,
    PluginEgressLimits,
    PluginEgressProtocol,
    resolve_plugin_egress_destination,
    resolve_public_destination,
)
from grafy_api.network_policy import (
    NetworkCaBundle,
    NetworkPolicy,
    resolve_http_egress_authority,
)
from grafy_api.plugins.profiles import PluginRuntimeProfile

from .plugin_artifacts import (
    PluginGuestRunError,
    PluginGuestRunner,
    PluginInvocationScratch,
)
from .plugin_sandbox import (
    PluginSandboxLifecycle,
    PluginSandboxScopeId,
    current_plugin_sandbox_scope,
)


_SANDBOX_LABEL = "io.grafy.plugin.sandbox=1"
_EGRESS_RESOURCE_LABEL = "io.grafy.plugin.egress=1"
_EGRESS_BROKER_ALIAS = "grafy-egress-broker"
_CONTAINER_INVOCATIONS = PurePosixPath("/run/grafy/invocations")
_RESULT_TAR_LIMIT = 2 * 1_024 * 1_024
_DOCKER_IMAGE_LABELS_ADAPTER: TypeAdapter[dict[str, str] | None] = TypeAdapter(
    dict[str, StrictStr] | None
)


logger = logging.getLogger(__name__)


class DockerPluginRuntimeError(RuntimeError):
    """The local Docker sandbox owner could not satisfy an operation."""


class _DockerCommandError(RuntimeError):
    pass


class _DockerOutputLimitError(RuntimeError):
    pass


class PluginRuntimeReleaseLookup(Protocol):
    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None: ...

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None: ...

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None: ...

    async def list_runtime_artifacts(self) -> list[PluginRuntimeArtifact]: ...


@dataclass(frozen=True, slots=True)
class _SandboxKey:
    scope_id: PluginSandboxScopeId
    workspace_id: UUID
    release_scope: PluginReleaseScope
    release_workspace_id: UUID | None
    release_slug: str
    release_revision: int
    source_digest: str
    descriptor_digest: str
    required_capabilities: tuple[PluginRuntimeCapability, ...]
    postgresql_destination: PluginEgressDestination | None = None
    # The effective HTTP authority and its profile digest make origin variants
    # of one release distinct sandboxes; a profile change cannot reuse a
    # sandbox created under older authority.
    network_profile_digest: str | None = None
    http_destinations: tuple[PluginEgressDestination, ...] = ()
    http_address_scope: PluginEgressAddressScope = PluginEgressAddressScope.PUBLIC
    network_ca_bundle_sha256: str | None = None

    def release_identity(self) -> tuple[object, ...]:
        return (
            self.release_scope,
            self.release_workspace_id,
            self.release_slug,
            self.release_revision,
            self.source_digest,
        )


@dataclass(frozen=True, slots=True)
class _Sandbox:
    key: _SandboxKey
    container_id: str
    scratch_root: Path
    egress_broker_id: str | None = None
    guest_network: str | None = None
    egress_network: str | None = None
    egress_plan: PluginEgressBrokerPlan | None = None


@dataclass(frozen=True, slots=True)
class PluginSandboxCapacityDiagnostics:
    max_live_sandboxes: int
    live_sandboxes: int
    waiting_sandbox_requests: int
    max_sandbox_variants_per_execution: int


async def _read_bounded(
    stream: asyncio.StreamReader,
    max_bytes: int,
) -> bytes:
    chunks: list[bytes] = []
    byte_count = 0
    while chunk := await stream.read(64 * 1_024):
        byte_count += len(chunk)
        if byte_count > max_bytes:
            raise _DockerOutputLimitError(
                f"Docker command output exceeded {max_bytes} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _kill_command(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        pass
    await process.wait()


@final
class DockerPluginRuntime(
    PluginGuestRunner,
    PluginInvocationScratch,
    PluginSandboxLifecycle,
):
    """Own scope/release containers and execute isolated guest children.

    The Docker socket remains in the API process only. Containers receive no
    socket, host credentials, working copy, database, or object-store access.
    """

    def __init__(
        self,
        *,
        releases: PluginRuntimeReleaseLookup,
        storage: FileStoragePort,
        bucket: str,
        profile: PluginRuntimeProfile,
        scratch_root: Path,
        docker_binary: str = "docker",
        seccomp_profile: Path | None = None,
        max_live_sandboxes: int = 4,
        max_distinct_releases_per_scope: int = 4,
        max_sandbox_variants_per_scope: int | None = None,
        supported_capabilities: frozenset[PluginRuntimeCapability] = (
            ISOLATED_BASE_CAPABILITIES
        ),
        egress_policy: PluginEgressBrokerPolicy = PluginEgressBrokerPolicy(),
        network_policy: NetworkPolicy | None = None,
    ) -> None:
        if max_live_sandboxes < 1:
            raise ValueError("Maximum live Plugin sandboxes must be positive")
        if max_distinct_releases_per_scope < 1:
            raise ValueError(
                "Maximum distinct Plugin releases per execution must be positive"
            )
        if max_distinct_releases_per_scope > max_live_sandboxes:
            raise ValueError(
                "Distinct Plugin releases per execution cannot exceed live sandboxes"
            )
        resolved_variant_limit = (
            max_live_sandboxes
            if max_sandbox_variants_per_scope is None
            else max_sandbox_variants_per_scope
        )
        if not 1 <= resolved_variant_limit <= max_live_sandboxes:
            raise ValueError(
                "Sandbox variants per execution must be positive and cannot "
                "exceed live sandboxes"
            )
        self._releases = releases
        self._storage = storage
        self._bucket = bucket
        self._profile = profile
        self._release_admission = isolated_release_admission(
            profile=profile,
            egress_policy=egress_policy,
            network_policy=network_policy or NetworkPolicy(),
            supported_capabilities=supported_capabilities,
        )
        self._network_policy = network_policy or NetworkPolicy()
        self._egress_policy = egress_policy
        self._scratch_root = scratch_root.resolve()
        self._docker_binary = docker_binary
        self._seccomp_profile = seccomp_profile
        self._max_distinct_releases_per_scope = max_distinct_releases_per_scope
        self._max_sandbox_variants_per_scope = resolved_variant_limit
        self._max_live_sandboxes = max_live_sandboxes
        self._live_sandbox_capacity = asyncio.BoundedSemaphore(max_live_sandboxes)
        self._waiting_sandbox_requests = 0
        self._sandboxes: dict[_SandboxKey, _Sandbox] = {}
        self._lock = asyncio.Lock()

    @property
    def release_admission(self) -> ReleaseExecutionAdmission:
        return self._release_admission

    @property
    def network_policy(self) -> NetworkPolicy:
        return self._network_policy

    @override
    def root_for(self, request: PluginInvocationRequest, /) -> Path:
        scope = current_plugin_sandbox_scope()
        if scope is None:
            raise PluginInvocationError(
                "Plugin invocation has no top-level sandbox scope"
            )
        release_root = (
            self._scratch_root
            / str(scope.value)
            / (
                f"{request.release.scope.value}-{request.release.slug}-"
                f"r{request.release.revision}-"
                f"{request.release.source_digest[:16]}"
            )
        )
        release_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return release_root

    async def recover_orphans(self) -> None:
        completed = await self._docker(
            (
                "ps",
                "-aq",
                "--filter",
                f"label={_SANDBOX_LABEL}",
            ),
            timeout=30,
            max_stdout=1 * 1_024 * 1_024,
            check=True,
        )
        container_ids = completed.stdout.decode("utf-8").split()
        if container_ids:
            await self._docker(
                ("rm", "-f", *container_ids),
                timeout=60,
                max_stdout=1 * 1_024 * 1_024,
                check=True,
            )
        egress_containers = await self._docker(
            ("ps", "-aq", "--filter", f"label={_EGRESS_RESOURCE_LABEL}"),
            timeout=30,
            max_stdout=1 * 1_024 * 1_024,
            check=True,
        )
        egress_container_ids = egress_containers.stdout.decode("utf-8").split()
        if egress_container_ids:
            await self._docker(
                ("rm", "-f", *egress_container_ids),
                timeout=60,
                max_stdout=1 * 1_024 * 1_024,
                check=True,
            )
        egress_networks = await self._docker(
            ("network", "ls", "-q", "--filter", f"label={_EGRESS_RESOURCE_LABEL}"),
            timeout=30,
            max_stdout=1 * 1_024 * 1_024,
            check=True,
        )
        for network in egress_networks.stdout.decode("utf-8").split():
            await self._remove_network(network)
        self._scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for child in self._scratch_root.iterdir():
            if child.is_symlink() or not child.is_dir():
                raise DockerPluginRuntimeError(
                    "Plugin runtime scratch root contains an unexpected entry"
                )
            shutil.rmtree(child)
        await self._remove_unreferenced_images()

    async def check_ready(self) -> None:
        await self._docker(
            ("version", "--format", "{{.Server.Version}}"),
            timeout=3,
            max_stdout=64 * 1_024,
            check=True,
        )
        broker_image = self._egress_policy.broker_image
        if broker_image is None:
            return
        inspected = await self._docker(
            (
                "image",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                broker_image,
            ),
            timeout=3,
            max_stdout=64 * 1_024,
            check=False,
        )
        if inspected.returncode != 0:
            logger.error(
                "plugin_egress_broker_incompatible",
                extra={
                    "broker_image": broker_image,
                    "reason": "image_unavailable",
                    "expected_contract_version": (
                        PLUGIN_EGRESS_BROKER_CONFIG_VERSION
                    ),
                    "actual_contract_version": "unavailable",
                },
            )
            raise DockerPluginRuntimeError(
                f"Configured Plugin egress broker image {broker_image!r} is not "
                "available to Docker"
            )
        try:
            labels = _DOCKER_IMAGE_LABELS_ADAPTER.validate_json(inspected.stdout)
        except ValidationError as exc:
            logger.error(
                "plugin_egress_broker_incompatible",
                extra={
                    "broker_image": broker_image,
                    "reason": "metadata_invalid",
                    "expected_contract_version": (
                        PLUGIN_EGRESS_BROKER_CONFIG_VERSION
                    ),
                    "actual_contract_version": "invalid",
                },
            )
            raise DockerPluginRuntimeError(
                "Plugin egress broker image has invalid compatibility metadata"
            ) from exc
        actual_version = (
            None
            if labels is None
            else labels.get(PLUGIN_EGRESS_BROKER_CONFIG_VERSION_LABEL)
        )
        expected_version = str(PLUGIN_EGRESS_BROKER_CONFIG_VERSION)
        if actual_version != expected_version:
            found = "undeclared" if actual_version is None else str(actual_version)
            logger.error(
                "plugin_egress_broker_incompatible",
                extra={
                    "broker_image": broker_image,
                    "reason": "version_mismatch",
                    "expected_contract_version": (PLUGIN_EGRESS_BROKER_CONFIG_VERSION),
                    "actual_contract_version": found,
                },
            )
            raise DockerPluginRuntimeError(
                "Plugin egress broker image is incompatible: expected policy "
                f"config version {expected_version}, found {found}. Rebuild the "
                "broker image from the same Grafy revision and update "
                "GRAFY_PLUGIN_EGRESS_BROKER_IMAGE"
            )

    async def diagnostics(self) -> PluginSandboxCapacityDiagnostics:
        async with self._lock:
            return PluginSandboxCapacityDiagnostics(
                max_live_sandboxes=self._max_live_sandboxes,
                live_sandboxes=len(self._sandboxes),
                waiting_sandbox_requests=self._waiting_sandbox_requests,
                max_sandbox_variants_per_execution=self._max_sandbox_variants_per_scope,
            )

    @override
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        envelope = PluginInvocationEnvelope.from_json_bytes(
            (invocation_root / "invocation.json").read_bytes()
        )
        if not _envelope_matches_invocation_request(envelope, request):
            raise PluginGuestRunError(
                PluginFailureCode.CONTRACT_FAILURE,
                "Plugin invocation envelope does not match its exact host request",
            )
        scope = current_plugin_sandbox_scope()
        if scope is None:
            raise PluginGuestRunError(
                PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
                "Plugin guest has no top-level sandbox scope",
            )
        release = await self._releases.get_by_revision(
            envelope.workspace_id,
            request.release.slug,
            request.release.revision,
            scope=request.release.scope,
        )
        if release is None or not _release_matches_identity(
            release,
            request.release,
        ):
            raise PluginGuestRunError(
                PluginFailureCode.CONTRACT_FAILURE,
                "Exact Plugin runtime release is unavailable",
            )
        if release.scope is PluginReleaseScope.WORKSPACE:
            revocation = await self._releases.get_revocation(
                workspace_id=envelope.workspace_id,
                slug=release.slug,
                revision=release.revision,
            )
        else:
            revocation = await self._releases.get_system_revocation(
                slug=release.slug,
                revision=release.revision,
            )
        decision = self._release_admission.decide(
            release,
            node_contract=request.contract,
            revocation=revocation,
        )
        if isinstance(decision, ReleaseExecutionRejection):
            raise PluginGuestRunError(
                PluginFailureCode.CONTRACT_FAILURE,
                f"Plugin release is not runnable ({decision.reason}): "
                f"{decision.detail}",
            )
        if decision is not ReleaseExecutionRoute.ISOLATED:
            raise PluginGuestRunError(
                PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
                f"Docker cannot satisfy Plugin execution route {decision.value!r}",
            )
        artifact = release.runtime_artifact
        if artifact is None:
            raise PluginGuestRunError(
                PluginFailureCode.CONTRACT_FAILURE,
                "Plugin release is catalog-only and has no runtime artifact",
            )
        postgresql_destination: PluginEgressDestination | None = None
        if (
            PluginRuntimeCapability.POSTGRESQL_EGRESS
            in request.required_capabilities
        ):
            host = request.config.get("host")
            port = request.config.get("port")
            if (
                not isinstance(host, str)
                or not isinstance(port, int)
                or isinstance(port, bool)
            ):
                raise PluginGuestRunError(
                    PluginFailureCode.CONTRACT_FAILURE,
                    "PostgreSQL egress requires exact string host and integer port config",
                )
            try:
                postgresql_destination = PluginEgressDestination(
                    protocol=PluginEgressProtocol.POSTGRESQL,
                    host=host,
                    port=port,
                )
            except ValueError as exc:
                raise PluginGuestRunError(
                    PluginFailureCode.CONTRACT_FAILURE,
                    str(exc),
                ) from exc
            if postgresql_destination not in self._egress_policy.destinations:
                raise PluginGuestRunError(
                    PluginFailureCode.CONTRACT_FAILURE,
                    "PostgreSQL destination is not in the deployment egress allowlist",
                )
        http_destinations: tuple[PluginEgressDestination, ...] = ()
        network_profile_digest: str | None = None
        egress_limits: PluginEgressLimits | None = None
        http_address_scope = PluginEgressAddressScope.PUBLIC
        network_ca_bundle: NetworkCaBundle | None = None
        requires_http_egress = (
            PluginRuntimeCapability.NETWORK_EGRESS in request.required_capabilities
        )
        if requires_http_egress:
            egress_resolution = resolve_http_egress_authority(
                self._network_policy,
                scope=release.scope,
                workspace_id=release.workspace_id,
                slug=release.slug,
                revision=release.revision,
                contract=request.contract,
                config=request.config,
            )
            if not egress_resolution.allowed:
                assert egress_resolution.reason is not None
                raise PluginGuestRunError(
                    PluginFailureCode.CONTRACT_FAILURE,
                    f"Network egress denied ({egress_resolution.reason.value}): "
                    f"{egress_resolution.detail}",
                )
            assert egress_resolution.profile is not None
            http_destinations = egress_resolution.origins
            network_profile_digest = egress_resolution.profile.policy_digest
            egress_limits = egress_resolution.profile.limits.broker_limits()
            if not egress_resolution.profile.public_address_only:
                http_address_scope = PluginEgressAddressScope.CURATED_RFC1918
            network_ca_bundle = egress_resolution.profile.ca_bundle
        key = _SandboxKey(
            scope_id=scope,
            workspace_id=envelope.workspace_id,
            release_scope=release.scope,
            release_workspace_id=release.workspace_id,
            release_slug=release.slug,
            release_revision=release.revision,
            source_digest=release.source_digest,
            descriptor_digest=release.descriptor.digest,
            required_capabilities=request.required_capabilities,
            postgresql_destination=postgresql_destination,
            network_profile_digest=network_profile_digest,
            http_destinations=http_destinations,
            http_address_scope=http_address_scope,
            network_ca_bundle_sha256=(
                None if network_ca_bundle is None else network_ca_bundle.sha256
            ),
        )
        try:
            sandbox = await self._sandbox_for(
                key,
                release,
                artifact,
                invocation_root.parent,
                egress_limits=egress_limits,
                network_ca_bundle=network_ca_bundle,
            )
        except DockerPluginRuntimeError as exc:
            raise PluginGuestRunError(
                PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
                str(exc),
            ) from exc
        container_root = _CONTAINER_INVOCATIONS / str(envelope.invocation_id)
        guest_environment = self._guest_egress_environment(sandbox, request)
        uncertain_cleanup = False
        try:
            archive = _invocation_tar(invocation_root, str(envelope.invocation_id))
            await self._docker(
                (
                    "exec",
                    "-i",
                    sandbox.container_id,
                    "/opt/grafy/plugin/.venv/bin/python",
                    "-I",
                    "-c",
                    (
                        "import sys,tarfile; "
                        "archive=tarfile.open(fileobj=sys.stdin.buffer,mode='r|'); "
                        "archive.extractall('/run/grafy/invocations',filter='data')"
                    ),
                ),
                input_bytes=archive,
                timeout=30,
                max_stdout=1 * 1_024 * 1_024,
                check=True,
            )
            try:
                await self._docker(
                    (
                        "exec",
                        "--workdir",
                        "/opt/grafy/plugin",
                        *guest_environment,
                        "--env",
                        f"TMPDIR={container_root / 'tmp'}",
                        sandbox.container_id,
                        "/opt/grafy/plugin/.venv/bin/python",
                        "-I",
                        "-m",
                        "grafy_core.runtime.plugin_guest",
                        str(container_root),
                    ),
                    timeout=limits.wall_time_seconds,
                    max_stdout=limits.max_log_bytes,
                    max_stderr=limits.max_log_bytes,
                    check=True,
                )
            except asyncio.TimeoutError as exc:
                uncertain_cleanup = True
                raise PluginGuestRunError(
                    PluginFailureCode.TIMEOUT,
                    f"Plugin guest exceeded {limits.wall_time_seconds} seconds",
                ) from exc
            result = await self._docker(
                (
                    "exec",
                    sandbox.container_id,
                    "/opt/grafy/plugin/.venv/bin/python",
                    "-I",
                    "-c",
                    (
                        "import pathlib,sys; "
                        "sys.stdout.buffer.write("
                        "pathlib.Path(sys.argv[1]).joinpath('result.json').read_bytes()"
                        ")"
                    ),
                    str(container_root),
                ),
                timeout=10,
                max_stdout=_RESULT_TAR_LIMIT,
                check=True,
            )
            (invocation_root / "result.json").write_bytes(result.stdout)
            output_tar_limit = (
                limits.max_output_bytes + limits.max_files * 2_048 + 1_024 * 1_024
            )
            output_archive = await self._docker(
                (
                    "exec",
                    sandbox.container_id,
                    "/opt/grafy/plugin/.venv/bin/python",
                    "-I",
                    "-c",
                    (
                        "import sys,tarfile; "
                        "archive=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); "
                        "archive.add(sys.argv[1],arcname='.',recursive=True); "
                        "archive.close()"
                    ),
                    str(container_root / "outputs"),
                ),
                timeout=30,
                max_stdout=output_tar_limit,
                check=True,
            )
            _restore_tar_files(
                output_archive.stdout,
                invocation_root / "outputs",
            )
        except asyncio.CancelledError:
            uncertain_cleanup = True
            raise
        except PluginGuestRunError:
            raise
        except (
            _DockerCommandError,
            _DockerOutputLimitError,
            OSError,
            tarfile.TarError,
        ) as exc:
            uncertain_cleanup = True
            raise PluginGuestRunError(
                PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
                "Plugin Docker invocation failed",
            ) from exc
        finally:
            cleanup_task = asyncio.create_task(
                self._cleanup_invocation(
                    sandbox,
                    container_root,
                    destroy_sandbox=uncertain_cleanup,
                )
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
                raise

    @override
    async def close_scope(self, scope_id: PluginSandboxScopeId, /) -> None:
        async with self._lock:
            sandboxes = [
                sandbox
                for key, sandbox in self._sandboxes.items()
                if key.scope_id == scope_id
            ]
            for sandbox in sandboxes:
                self._sandboxes.pop(sandbox.key, None)
        failures: list[Exception] = []
        for sandbox in sandboxes:
            try:
                await self._remove_sandbox_resources(sandbox)
            except Exception as exc:
                failures.append(exc)
            finally:
                self._live_sandbox_capacity.release()
        scope_root = self._scratch_root / str(scope_id.value)
        if scope_root.exists():
            shutil.rmtree(scope_root)
        if failures:
            raise DockerPluginRuntimeError(
                f"Could not remove {len(failures)} Plugin scope containers"
            ) from failures[0]

    async def shutdown(self) -> None:
        async with self._lock:
            sandboxes = list(self._sandboxes.values())
            self._sandboxes.clear()
        for sandbox in sandboxes:
            try:
                await self._remove_sandbox_resources(sandbox)
            finally:
                self._live_sandbox_capacity.release()

    async def _sandbox_for(
        self,
        key: _SandboxKey,
        release: InstalledPluginRelease,
        artifact: PluginRuntimeArtifact,
        scratch_root: Path,
        *,
        egress_limits: PluginEgressLimits | None = None,
        network_ca_bundle: NetworkCaBundle | None = None,
    ) -> _Sandbox:
        async with self._lock:
            existing = self._sandboxes.get(key)
            if existing is not None:
                return existing
            self._require_scope_capacity(key)
        self._waiting_sandbox_requests += 1
        try:
            await self._live_sandbox_capacity.acquire()
        finally:
            self._waiting_sandbox_requests -= 1
        try:
            async with self._lock:
                existing = self._sandboxes.get(key)
                if existing is not None:
                    self._live_sandbox_capacity.release()
                    return existing
                self._require_scope_capacity(key)
                await self._ensure_image(release, artifact)
                sandbox = await self._create_container(
                    key,
                    artifact,
                    scratch_root,
                    egress_limits=egress_limits,
                    network_ca_bundle=network_ca_bundle,
                )
                self._sandboxes[key] = sandbox
                return sandbox
        except BaseException:
            self._live_sandbox_capacity.release()
            raise

    def _require_scope_capacity(self, key: _SandboxKey) -> None:
        """Enforce per-scope release and sandbox-variant ceilings.

        Origin variants of one release count against the variant limit, never
        against the distinct-release limit.
        """

        scope_keys = [
            existing_key
            for existing_key in self._sandboxes
            if existing_key.scope_id == key.scope_id
        ]
        distinct_release_count = len(
            {existing_key.release_identity() for existing_key in scope_keys}
        )
        if distinct_release_count >= self._max_distinct_releases_per_scope:
            raise DockerPluginRuntimeError(
                "Graph execution exceeds its distinct Plugin release limit"
            )
        if len(scope_keys) >= self._max_sandbox_variants_per_scope:
            raise DockerPluginRuntimeError(
                "Graph execution exceeds its Plugin sandbox variant limit"
            )

    async def _ensure_image(
        self,
        release: InstalledPluginRelease,
        artifact: PluginRuntimeArtifact,
    ) -> None:
        image_reference = f"sha256:{artifact.manifest_digest}"
        inspected = await self._docker(
            ("image", "inspect", image_reference),
            timeout=30,
            max_stdout=8 * 1_024 * 1_024,
            check=False,
        )
        if inspected.returncode != 0:
            with TemporaryDirectory(prefix="grafy-plugin-oci-load-") as temporary:
                archive_path = Path(temporary) / "image.oci.tar"
                stream = await self._storage.load(self._bucket, artifact.object_key)
                digest = sha256()
                try:
                    with archive_path.open("wb") as destination:
                        while chunk := stream.read(1 * 1_024 * 1_024):
                            digest.update(chunk)
                            destination.write(chunk)
                finally:
                    stream.close()
                if digest.hexdigest() != artifact.archive_digest:
                    raise DockerPluginRuntimeError(
                        "Stored Plugin OCI archive failed digest validation"
                    )
                await self._docker(
                    ("load", "--input", str(archive_path)),
                    timeout=300,
                    max_stdout=4 * 1_024 * 1_024,
                    check=True,
                )
        labels = await self._docker(
            (
                "image",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                image_reference,
            ),
            timeout=30,
            max_stdout=1 * 1_024 * 1_024,
            check=True,
        )
        parsed = json.loads(labels.stdout)
        if not isinstance(parsed, dict):
            raise DockerPluginRuntimeError("Plugin image labels are unavailable")
        image_labels = cast(dict[str, object], parsed)
        expected = {
            "org.opencontainers.image.source.digest": f"sha256:{release.source_digest}",
            "io.grafy.plugin.runtime": "1",
            "io.grafy.plugin.contract.digest": f"sha256:{release.contract_digest}",
            "io.grafy.plugin.profile.digest": f"sha256:{release.profile_digest}",
            "io.grafy.plugin.base.digest": (
                f"sha256:{self._profile.base_image_digest}"
            ),
            "io.grafy.plugin.protocol.digest": f"sha256:{release.protocol_digest}",
        }
        if any(image_labels.get(name) != value for name, value in expected.items()):
            raise DockerPluginRuntimeError(
                "Plugin image labels do not match the exact release descriptor"
            )

    async def _remove_unreferenced_images(self) -> None:
        retained_artifacts = await self._releases.list_runtime_artifacts()
        retained = {
            f"sha256:{artifact.manifest_digest}" for artifact in retained_artifacts
        }
        listed = await self._docker(
            (
                "image",
                "ls",
                "--quiet",
                "--filter",
                "label=io.grafy.plugin.runtime=1",
            ),
            timeout=30,
            max_stdout=4 * 1_024 * 1_024,
            check=True,
        )
        stale = sorted(set(listed.stdout.decode("utf-8").split()) - retained)
        if stale:
            await self._docker(
                ("image", "rm", "--force", *stale),
                timeout=120,
                max_stdout=4 * 1_024 * 1_024,
                check=True,
            )

    async def _create_container(
        self,
        key: _SandboxKey,
        artifact: PluginRuntimeArtifact,
        scratch_root: Path,
        *,
        egress_limits: PluginEgressLimits | None = None,
        network_ca_bundle: NetworkCaBundle | None = None,
    ) -> _Sandbox:
        name = (
            f"grafy-plugin-{str(key.scope_id.value)[:8]}-"
            f"{key.release_scope.value[:3]}-"
            f"{key.release_slug[:24]}-r{key.release_revision}-"
            f"{_sandbox_key_sha256(key)[:16]}"
        )
        capability_profile = ",".join(
            capability.value for capability in key.required_capabilities
        )
        capability_profile_digest = sha256(
            capability_profile.encode("utf-8")
        ).hexdigest()
        seccomp = (
            "seccomp=builtin"
            if self._seccomp_profile is None
            else f"seccomp={self._seccomp_profile}"
        )
        created_at = datetime.now(UTC).isoformat()
        requires_http_egress = (
            PluginRuntimeCapability.NETWORK_EGRESS in key.required_capabilities
        )
        requires_postgresql_egress = (
            PluginRuntimeCapability.POSTGRESQL_EGRESS in key.required_capabilities
        )
        egress_plan: PluginEgressBrokerPlan | None = None
        guest_network: str | None = None
        egress_network: str | None = None
        broker_container_id: str | None = None
        sandbox_container_id: str | None = None
        network_arguments: tuple[str, ...] = ("--network=none",)
        ca_mount_arguments: tuple[str, ...] = ()
        if (network_ca_bundle is None) != (key.network_ca_bundle_sha256 is None):
            raise DockerPluginRuntimeError("Plugin network CA identity is inconsistent")
        if network_ca_bundle is not None:
            if network_ca_bundle.sha256 != key.network_ca_bundle_sha256:
                raise DockerPluginRuntimeError(
                    "Plugin network CA content identity changed"
                )
            scratch_root.mkdir(parents=True, exist_ok=True)
            staged_ca = scratch_root / f"network-ca-{network_ca_bundle.sha256}.pem"
            staged_ca.write_bytes(network_ca_bundle.content)
            staged_ca.chmod(0o444)
            ca_mount_arguments = (
                "--mount",
                (
                    f"type=bind,source={staged_ca},"
                    "target=/run/grafy/network-ca.pem,readonly"
                ),
            )
        if requires_http_egress or requires_postgresql_egress:
            broker_image = self._egress_policy.broker_image
            if broker_image is None:
                raise DockerPluginRuntimeError(
                    "Plugin egress broker image is not configured"
                )
            sandbox_key_sha256 = _sandbox_key_sha256(key)
            try:
                resolved_http = tuple(
                    await asyncio.wait_for(
                        asyncio.gather(
                            *(
                                resolve_plugin_egress_destination(
                                    destination,
                                    address_scope=key.http_address_scope,
                                )
                                for destination in key.http_destinations
                            )
                        ),
                        timeout=10,
                    )
                )
                if key.postgresql_destination is not None:
                    resolved_postgresql = (
                        await resolve_public_destination(
                            key.postgresql_destination
                        ),
                    )
                else:
                    resolved_postgresql = ()
            except (OSError, PermissionError, ValueError) as exc:
                raise DockerPluginRuntimeError(
                    "Plugin egress destinations could not be resolved safely"
                ) from exc
            egress_plan = PluginEgressBrokerPlan.from_resolved(
                broker_image=broker_image,
                sandbox_key_sha256=sandbox_key_sha256,
                destinations=(*resolved_http, *resolved_postgresql),
                limits=egress_limits or PluginEgressLimits(),
            )
            if not egress_plan.destinations:
                raise DockerPluginRuntimeError(
                    "Plugin egress plan has no destinations for the requested "
                    "capabilities"
                )
            resource_suffix = sandbox_key_sha256[:16]
            guest_network = f"grafy-plugin-internal-{resource_suffix}"
            egress_network = f"grafy-plugin-egress-{resource_suffix}"
            network_arguments = ("--network", guest_network)
        try:
            if egress_plan is not None:
                assert guest_network is not None
                assert egress_network is not None
                await self._docker(
                    (
                        "network",
                        "create",
                        "--driver",
                        "bridge",
                        "--internal",
                        "--label",
                        _EGRESS_RESOURCE_LABEL,
                        "--label",
                        f"io.grafy.plugin.sandbox_key={egress_plan.sandbox_key_sha256}",
                        guest_network,
                    ),
                    timeout=30,
                    max_stdout=1 * 1_024 * 1_024,
                    check=True,
                )
                await self._docker(
                    (
                        "network",
                        "create",
                        "--driver",
                        "bridge",
                        "--label",
                        _EGRESS_RESOURCE_LABEL,
                        "--label",
                        f"io.grafy.plugin.sandbox_key={egress_plan.sandbox_key_sha256}",
                        egress_network,
                    ),
                    timeout=30,
                    max_stdout=1 * 1_024 * 1_024,
                    check=True,
                )
                broker_created = await self._docker(
                    (
                        "create",
                        "--name",
                        f"grafy-plugin-broker-{egress_plan.sandbox_key_sha256[:16]}",
                        "--pull=never",
                        "--network",
                        egress_network,
                        "--read-only",
                        "--user",
                        "65532:65532",
                        "--cap-drop=ALL",
                        "--security-opt",
                        "no-new-privileges=true",
                        "--security-opt",
                        seccomp,
                        "--pids-limit",
                        "64",
                        "--memory",
                        "134217728",
                        "--memory-swap",
                        "134217728",
                        "--tmpfs",
                        "/tmp:rw,noexec,nosuid,nodev,size=8388608,mode=1777",
                        "--env",
                        (
                            "GRAFY_PLUGIN_EGRESS_POLICY_B64="
                            + base64.b64encode(
                                egress_plan.canonical_json_bytes()
                            ).decode("ascii")
                        ),
                        "--label",
                        _EGRESS_RESOURCE_LABEL,
                        "--label",
                        f"io.grafy.plugin.scope={key.scope_id.value}",
                        "--label",
                        f"io.grafy.plugin.sandbox_key={egress_plan.sandbox_key_sha256}",
                        "--label",
                        f"io.grafy.plugin.egress_policy={egress_plan.policy_sha256}",
                        egress_plan.broker_image,
                        "/opt/grafy/bin/grafy-plugin-egress-broker",
                        "serve",
                        "--policy-env",
                        "GRAFY_PLUGIN_EGRESS_POLICY_B64",
                    ),
                    timeout=60,
                    max_stdout=1 * 1_024 * 1_024,
                    check=True,
                )
                broker_container_id = broker_created.stdout.decode("utf-8").strip()
                if not broker_container_id:
                    raise DockerPluginRuntimeError(
                        "Docker returned no Plugin egress broker container ID"
                    )
                await self._docker(
                    (
                        "network",
                        "connect",
                        "--alias",
                        _EGRESS_BROKER_ALIAS,
                        *tuple(
                            value
                            for relay in egress_plan.postgresql_relays
                            for value in ("--alias", relay.destination.host)
                        ),
                        guest_network,
                        broker_container_id,
                    ),
                    timeout=30,
                    max_stdout=1 * 1_024 * 1_024,
                    check=True,
                )
                await self._docker(
                    ("start", broker_container_id),
                    timeout=60,
                    max_stdout=1 * 1_024 * 1_024,
                    check=True,
                )
                broker_ready = await self._docker(
                    (
                        "exec",
                        broker_container_id,
                        "/opt/grafy/bin/grafy-plugin-egress-broker",
                        "ready",
                        "--policy-sha256",
                        egress_plan.policy_sha256,
                        "--timeout-seconds",
                        "5",
                    ),
                    timeout=10,
                    max_stdout=64 * 1_024,
                    check=False,
                )
                if broker_ready.returncode != 0:
                    broker_status = "unknown"
                    broker_exit_code: int | None = None
                    broker_oom_killed: bool | None = None
                    # Preserve the primary readiness failure when diagnostics fail.
                    broker_state_probe_succeeded = False
                    try:
                        state_result = await self._docker(
                            (
                                "inspect",
                                "--format",
                                "{{json .State}}",
                                broker_container_id,
                            ),
                            timeout=10,
                            max_stdout=64 * 1_024,
                            check=False,
                        )
                    except Exception:
                        state_result = None
                    if state_result is not None and state_result.returncode == 0:
                        broker_state_probe_succeeded = True
                        try:
                            loaded_state: object = json.loads(state_result.stdout)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            loaded_state = None
                        if isinstance(loaded_state, dict):
                            state = cast(dict[str, object], loaded_state)
                            raw_status = state.get("Status")
                            raw_exit_code = state.get("ExitCode")
                            raw_oom_killed = state.get("OOMKilled")
                            if isinstance(raw_status, str):
                                broker_status = raw_status
                            if isinstance(raw_exit_code, int) and not isinstance(
                                raw_exit_code,
                                bool,
                            ):
                                broker_exit_code = raw_exit_code
                            if isinstance(raw_oom_killed, bool):
                                broker_oom_killed = raw_oom_killed
                    broker_log_probe_succeeded = False
                    rejected_config_version = False
                    try:
                        broker_logs = await self._docker(
                            ("logs", "--tail", "20", broker_container_id),
                            timeout=10,
                            max_stdout=64 * 1_024,
                            max_stderr=64 * 1_024,
                            check=False,
                        )
                    except Exception:
                        broker_logs = None
                    if broker_logs is not None and broker_logs.returncode == 0:
                        broker_log_probe_succeeded = True
                        rejected_config_version = (
                            b"Broker policy config version is unsupported"
                            in broker_logs.stdout
                            or b"Broker policy config version is unsupported"
                            in broker_logs.stderr
                        )
                    logger.error(
                        "plugin_egress_broker_readiness_failed",
                        extra={
                            "workspace_id": str(key.workspace_id),
                            "plugin_slug": key.release_slug,
                            "plugin_revision": key.release_revision,
                            "broker_image": egress_plan.broker_image,
                            "broker_contract_version": (
                                PLUGIN_EGRESS_BROKER_CONFIG_VERSION
                            ),
                            "ready_exit_code": broker_ready.returncode,
                            "broker_status": broker_status,
                            "broker_exit_code": broker_exit_code,
                            "broker_oom_killed": broker_oom_killed,
                            "broker_state_probe_succeeded": (
                                broker_state_probe_succeeded
                            ),
                            "broker_log_probe_succeeded": (
                                broker_log_probe_succeeded
                            ),
                            "broker_rejected_policy_version": (
                                rejected_config_version
                            ),
                        },
                    )
                    if rejected_config_version:
                        raise DockerPluginRuntimeError(
                            "Plugin egress broker rejected policy config version "
                            f"{PLUGIN_EGRESS_BROKER_CONFIG_VERSION}; rebuild the "
                            "broker image from the same Grafy revision and update "
                            "GRAFY_PLUGIN_EGRESS_BROKER_IMAGE"
                        )
                    raise DockerPluginRuntimeError(
                        "Plugin egress broker did not become ready "
                        f"(ready status {broker_ready.returncode}, container "
                        f"status {broker_status}, exit status "
                        f"{broker_exit_code}, OOM killed {broker_oom_killed})"
                    )
            command = (
            "create",
            "--name",
            name,
            "--pull=never",
            *network_arguments,
            *ca_mount_arguments,
            "--read-only",
            "--user",
            "65532:65532",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--security-opt",
            seccomp,
            "--cpus",
            str(self._profile.cpu_count),
            "--memory",
            str(self._profile.memory_bytes),
            "--memory-swap",
            str(self._profile.memory_bytes),
            "--pids-limit",
            str(self._profile.pid_limit),
            "--ulimit",
            (f"nofile={self._profile.open_file_limit}:{self._profile.open_file_limit}"),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16777216,mode=1777",
            "--tmpfs",
            (
                "/run/grafy/invocations:rw,noexec,nosuid,nodev,"
                f"size={self._profile.scratch_bytes},mode=700,uid=65532,gid=65532"
            ),
            "--label",
            _SANDBOX_LABEL,
            "--label",
            f"io.grafy.plugin.scope={key.scope_id.value}",
            "--label",
            f"io.grafy.plugin.release={key.release_slug}@{key.release_revision}",
            "--label",
            f"io.grafy.plugin.release_scope={key.release_scope.value}",
            "--label",
            f"io.grafy.plugin.capability_profile={capability_profile_digest}",
            "--label",
            f"io.grafy.plugin.created_at={created_at}",
            f"sha256:{artifact.manifest_digest}",
            "-c",
            "import pathlib,time; pathlib.Path('/tmp/home').mkdir(); time.sleep(10**9)",
        )
            created = await self._docker(
                command,
                timeout=60,
                max_stdout=1 * 1_024 * 1_024,
                check=True,
            )
            sandbox_container_id = created.stdout.decode("utf-8").strip()
            if not sandbox_container_id:
                raise DockerPluginRuntimeError("Docker returned no Plugin container ID")
            await self._docker(
                ("start", sandbox_container_id),
                timeout=60,
                max_stdout=1 * 1_024 * 1_024,
                check=True,
            )
            return _Sandbox(
                key=key,
                container_id=sandbox_container_id,
                scratch_root=scratch_root,
                egress_broker_id=broker_container_id,
                guest_network=guest_network,
                egress_network=egress_network,
                egress_plan=egress_plan,
            )
        except BaseException:
            for container_id in (sandbox_container_id, broker_container_id):
                if container_id is None:
                    continue
                try:
                    await self._remove_container(container_id)
                except Exception:
                    pass
            for network in (guest_network, egress_network):
                if network is None:
                    continue
                try:
                    await self._remove_network(network)
                except Exception:
                    pass
            raise

    async def _destroy_sandbox(self, sandbox: _Sandbox) -> None:
        async with self._lock:
            owned = self._sandboxes.pop(sandbox.key, None)
        if owned is None:
            return
        try:
            await self._remove_sandbox_resources(sandbox)
        finally:
            self._live_sandbox_capacity.release()

    def _guest_egress_environment(
        self,
        sandbox: _Sandbox,
        request: PluginInvocationRequest,
    ) -> tuple[str, ...]:
        environment: tuple[str, ...] = ()
        capabilities = sandbox.key.required_capabilities
        if PluginRuntimeCapability.NETWORK_EGRESS in capabilities:
            if sandbox.egress_plan is None or not sandbox.egress_plan.http_proxy_enabled:
                raise PluginGuestRunError(
                    PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
                    "Plugin HTTP egress broker is unavailable",
                )
            proxy_url = f"http://{_EGRESS_BROKER_ALIAS}:{PLUGIN_HTTP_PROXY_PORT}"
            environment += (
                "--env",
                f"HTTP_PROXY={proxy_url}",
                "--env",
                f"HTTPS_PROXY={proxy_url}",
                "--env",
                f"http_proxy={proxy_url}",
                "--env",
                f"https_proxy={proxy_url}",
                "--env",
                "NO_PROXY=",
                "--env",
                "no_proxy=",
            )
            if sandbox.key.network_ca_bundle_sha256 is not None:
                environment += (
                    "--env",
                    "SSL_CERT_FILE=/run/grafy/network-ca.pem",
                )
        return environment

    async def _remove_sandbox_resources(self, sandbox: _Sandbox) -> None:
        failures: list[Exception] = []
        for container_id in (sandbox.container_id, sandbox.egress_broker_id):
            if container_id is None:
                continue
            try:
                await self._remove_container(container_id)
            except Exception as exc:
                failures.append(exc)
        for network in (sandbox.guest_network, sandbox.egress_network):
            if network is None:
                continue
            try:
                await self._remove_network(network)
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise DockerPluginRuntimeError(
                "Could not remove all Plugin sandbox resources"
            ) from failures[0]

    async def _cleanup_invocation(
        self,
        sandbox: _Sandbox,
        container_root: PurePosixPath,
        *,
        destroy_sandbox: bool,
    ) -> None:
        if destroy_sandbox:
            await self._destroy_sandbox(sandbox)
            return
        try:
            await self._docker(
                (
                    "exec",
                    sandbox.container_id,
                    "/opt/grafy/plugin/.venv/bin/python",
                    "-I",
                    "-c",
                    "import shutil,sys; shutil.rmtree(sys.argv[1])",
                    str(container_root),
                ),
                timeout=10,
                max_stdout=64 * 1_024,
                check=True,
            )
        except Exception:
            await self._destroy_sandbox(sandbox)

    async def _remove_container(self, container_id: str) -> None:
        completed = await self._docker(
            ("rm", "-f", container_id),
            timeout=60,
            max_stdout=1 * 1_024 * 1_024,
            check=False,
        )
        if completed.returncode == 0:
            return
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if "No such container" not in detail:
            raise _DockerCommandError(
                f"Docker container removal failed with status "
                f"{completed.returncode}: {detail[-2_000:]}"
            )

    async def _remove_network(self, network: str) -> None:
        completed = await self._docker(
            ("network", "rm", network),
            timeout=30,
            max_stdout=1 * 1_024 * 1_024,
            check=False,
        )
        if completed.returncode == 0:
            return
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if "No such network" not in detail:
            raise _DockerCommandError(
                f"Docker network removal failed with status "
                f"{completed.returncode}: {detail[-2_000:]}"
            )

    @dataclass(frozen=True, slots=True)
    class _Completed:
        returncode: int
        stdout: bytes
        stderr: bytes

    async def _docker(
        self,
        arguments: tuple[str, ...],
        *,
        timeout: int,
        max_stdout: int,
        max_stderr: int = 1 * 1_024 * 1_024,
        input_bytes: bytes | None = None,
        check: bool,
    ) -> _Completed:
        docker_executable = shutil.which(self._docker_binary)
        if docker_executable is None:
            raise _DockerCommandError(
                f"Docker executable {self._docker_binary!r} is not on PATH"
            )
        process = await asyncio.create_subprocess_exec(
            docker_executable,
            *arguments,
            stdin=(
                asyncio.subprocess.PIPE
                if input_bytes is not None
                else asyncio.subprocess.DEVNULL
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=False,
        )
        if process.stdout is None or process.stderr is None:
            await _kill_command(process)
            raise _DockerCommandError("Docker command did not expose output streams")
        stdout_task = asyncio.create_task(_read_bounded(process.stdout, max_stdout))
        stderr_task = asyncio.create_task(_read_bounded(process.stderr, max_stderr))
        try:
            if input_bytes is not None:
                if process.stdin is None:
                    raise _DockerCommandError("Docker command did not expose stdin")
                process.stdin.write(input_bytes)
                await process.stdin.drain()
                process.stdin.close()
            await asyncio.wait_for(process.wait(), timeout=timeout)
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except BaseException:
            await _kill_command(process)
            for task in (stdout_task, stderr_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        completed = self._Completed(
            returncode=process.returncode or 0,
            stdout=stdout,
            stderr=stderr,
        )
        if check and completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()[-2_000:]
            raise _DockerCommandError(
                f"Docker command failed with status {completed.returncode}: {detail}"
            )
        return completed


def _sandbox_key_sha256(key: _SandboxKey) -> str:
    identity = {
        "scope_id": str(key.scope_id.value),
        "workspace_id": str(key.workspace_id),
        "release_scope": key.release_scope.value,
        "release_workspace_id": (
            None
            if key.release_workspace_id is None
            else str(key.release_workspace_id)
        ),
        "release_slug": key.release_slug,
        "release_revision": key.release_revision,
        "source_digest": key.source_digest,
        "descriptor_digest": key.descriptor_digest,
        "required_capabilities": [
            capability.value for capability in key.required_capabilities
        ],
        "postgresql_destination": (
            None
            if key.postgresql_destination is None
            else {
                "host": key.postgresql_destination.host,
                "port": key.postgresql_destination.port,
            }
        ),
        "network_profile_digest": key.network_profile_digest,
        "http_address_scope": key.http_address_scope.value,
        "network_ca_bundle_sha256": key.network_ca_bundle_sha256,
        "http_destinations": [
            {
                "protocol": destination.protocol.value,
                "host": destination.host,
                "port": destination.port,
            }
            for destination in key.http_destinations
        ],
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256(canonical).hexdigest()


def _release_matches_identity(
    release: InstalledPluginRelease,
    identity: PluginReleaseIdentity,
) -> bool:
    return (
        release.scope is identity.scope
        and release.workspace_id == identity.workspace_id
        and release.slug == identity.slug
        and release.revision == identity.revision
        and release.source_digest == identity.source_digest
        and release.contract_digest == identity.contract_digest
        and release.protocol_digest == identity.protocol_digest
        and release.descriptor.digest == identity.descriptor_digest
    )


def _envelope_matches_invocation_request(
    envelope: PluginInvocationEnvelope,
    request: PluginInvocationRequest,
) -> bool:
    return (
        envelope.workspace_id == request.workspace_id
        and envelope.release.slug == request.release.slug
        and envelope.release.revision == request.release.revision
        and envelope.release.source_digest == request.release.source_digest
        and envelope.release.contract_digest == request.release.contract_digest
        and envelope.release.protocol_digest == request.release.protocol_digest
        and envelope.operator_id == request.contract.operator_id
        and envelope.operator_version == request.contract.operator_version
        and envelope.required_capabilities == request.required_capabilities
        and envelope.secret_graph_id == request.secret_graph_id
        and envelope.secret_graph_revision == request.secret_graph_revision
    )


def _invocation_tar(invocation_root: Path, directory_name: str) -> bytes:
    destination = BytesIO()
    with tarfile.open(fileobj=destination, mode="w") as archive:
        root_info = tarfile.TarInfo(directory_name)
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o700
        root_info.uid = 65_532
        root_info.gid = 65_532
        archive.addfile(root_info)
        tmp_info = tarfile.TarInfo(f"{directory_name}/tmp")
        tmp_info.type = tarfile.DIRTYPE
        tmp_info.mode = 0o700
        tmp_info.uid = 65_532
        tmp_info.gid = 65_532
        archive.addfile(tmp_info)
        for path in sorted(invocation_root.rglob("*")):
            if path.is_symlink():
                raise DockerPluginRuntimeError(
                    "Plugin invocation scratch must not contain symlinks"
                )
            relative = path.relative_to(invocation_root).as_posix()
            info = tarfile.TarInfo(f"{directory_name}/{relative}")
            info.uid = 65_532
            info.gid = 65_532
            if path.is_dir():
                info.type = tarfile.DIRTYPE
                info.mode = 0o700
                archive.addfile(info)
                continue
            if not path.is_file():
                raise DockerPluginRuntimeError(
                    "Plugin invocation scratch contains a non-regular file"
                )
            content = path.read_bytes()
            info.size = len(content)
            info.mode = (
                0o400
                if relative.startswith(("inputs/", "secrets/"))
                else 0o600
            )
            archive.addfile(info, BytesIO(content))
    return destination.getvalue()


def _restore_tar_files(
    content: bytes,
    destination: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=BytesIO(content), mode="r:") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if not member.isfile():
                raise DockerPluginRuntimeError(
                    "Plugin output archive contains a non-regular file"
                )
            path = PurePosixPath(member.name)
            parts = tuple(part for part in path.parts if part not in {"", "."})
            if not parts or any(part == ".." for part in parts):
                raise DockerPluginRuntimeError(
                    "Plugin output archive contains an unsafe path"
                )
            relative = PurePosixPath(*parts)
            stream = archive.extractfile(member)
            if stream is None:
                raise DockerPluginRuntimeError("Plugin output archive is unreadable")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(stream.read())


__all__ = [
    "DockerPluginRuntime",
    "DockerPluginRuntimeError",
    "PluginSandboxCapacityDiagnostics",
]
