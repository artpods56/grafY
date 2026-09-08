"""Host authorization, artifact staging, and atomic Plugin output import."""

import asyncio
from io import BytesIO
import json
import os
import signal
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, cast, final, override
from uuid import UUID, uuid4

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
    UnitOfWorkPort,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactBundleContract,
    PluginArtifactReferenceContract,
    PluginArtifactTypeKey,
    PluginPortContract,
    plugin_protocol_digest,
)
from grafy_core.domain.node_secrets import (
    JsonValue,
    node_secret_dependency_sha256,
)
from grafy_core.plugins import PluginUnitOfWorkPort
from grafy_core.staged_upload_paths import resolve_staged_upload_path
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableChunk,
    TableChunkDescriptor,
    TableManifest,
)
from grafy_core.ports.storage import (
    FileMetadata,
    FileStoragePort,
    SaveFileCommand,
    StoredFile,
)
from grafy_core.ports.node_secrets import (
    NodeSecretResolverPort,
    UnavailableNodeSecretResolver,
)
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginInvocationRequest,
    PluginInvocationResult,
    PluginInvoker,
)
from grafy_core.runtime.plugin_loader import (
    PluginGuestLoaderManifest,
    WORKSPACE_PLUGIN_LOADER_TARGET,
)
from grafy_core.runtime.plugin_protocol import (
    PluginArtifactShape,
    PluginFailureCode,
    PluginInputArtifactBundle,
    PluginInputArtifactDependency,
    PluginInputArtifactGroup,
    PluginInputBinding,
    PluginInvocationArtifactTypeBinding,
    PluginInvocationEnvelope,
    PluginInvocationLimits,
    PluginInvocationRelease,
    PluginInvocationResultEnvelope,
    PluginOutputDeclaration,
    PluginSecretBinding,
    PluginStagedUploadBinding,
)
from grafy_core.runtime.object_set_bundle import (
    ObjectSetBundleError,
    ObjectSetBundleManifest,
    PORTABLE_BUNDLE_METADATA_KEY,
    PortableArtifactBundleMetadata,
    PortableArtifactFile,
    PortableMetadataReference,
    load_object_set_bundle,
    object_set_manifest,
    portable_metadata,
    write_object_set_bundle,
)
from grafy_core.runtime.table_bundle import (
    TableBundleChunkDescriptor,
    TableBundleError,
    TableBundleManifest,
    file_identity,
    iter_table_bundle_chunks,
    validate_table_bundle,
    write_table_bundle,
    write_table_bundle_archive,
)
from grafy_core.runtime.table_storage import load_table_manifest


_RESULT_MANIFEST_MAX_BYTES = 1 * 1_024 * 1_024
_INPUT_BUNDLE_SUFFIX = {
    "table-bundle": ".table.tar",
    "binary-file": ".bin",
    "object-set": ".objects.tar",
    "inline-json": ".json",
}


class PluginGuestRunner(Protocol):
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None: ...


class PluginInvocationScratch(Protocol):
    def root_for(self, request: PluginInvocationRequest, /) -> Path: ...


class PluginGuestRunError(RuntimeError):
    def __init__(self, code: PluginFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PluginInvocationCapacityDiagnostics:
    max_active_invocations: int
    active_invocations: int
    waiting_invocations: int
    total_invocations: int
    completed_invocations: int
    failed_invocations: int


class _BoundedLogError(RuntimeError):
    pass


async def _read_bounded_log(
    stream: asyncio.StreamReader,
    max_bytes: int,
) -> None:
    byte_count = 0
    while chunk := await stream.read(64 * 1_024):
        byte_count += len(chunk)
        if byte_count > max_bytes:
            raise _BoundedLogError(f"Plugin guest log exceeded {max_bytes} bytes")


async def _wait_for_process(process: asyncio.subprocess.Process) -> None:
    _ = await process.wait()


async def _kill_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    await process.wait()


@final
class SubprocessPluginGuestRunner(PluginGuestRunner):
    """Run the guest protocol entrypoint in a bounded local subprocess.

    This adapter is useful for protocol contract tests and development. It is
    not an operating-system sandbox; the Docker adapter in the next slice owns
    production isolation.
    """

    def __init__(
        self,
        command: tuple[str, ...],
        *,
        environment: Mapping[str, str] | None = None,
        loader_target: str = WORKSPACE_PLUGIN_LOADER_TARGET,
    ) -> None:
        if not command:
            raise ValueError("Plugin guest subprocess command must not be empty")
        self._command = command
        self._environment = {
            "PYTHONHASHSEED": "0",
            "PYTHONUTF8": "1",
        }
        if environment is not None:
            self._environment.update(environment)
        self._loader_target = loader_target

    @override
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest | None = None,
    ) -> None:
        command = (*self._command, str(invocation_root))
        if request is not None:
            loader_manifest_path = invocation_root / "plugin-loader.json"
            loader_manifest_path.write_bytes(
                PluginGuestLoaderManifest(
                    slug=request.release.slug,
                    loader_target=self._loader_target,
                ).canonical_json_bytes()
            )
            command = (*command, str(loader_manifest_path))
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=invocation_root,
            env=self._environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process.stdout is None or process.stderr is None:
            await _kill_process(process)
            raise PluginGuestRunError(
                PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
                "Plugin guest subprocess did not expose bounded log streams",
            )
        wait_task = asyncio.create_task(_wait_for_process(process))
        stdout_task = asyncio.create_task(
            _read_bounded_log(process.stdout, limits.max_log_bytes)
        )
        stderr_task = asyncio.create_task(
            _read_bounded_log(process.stderr, limits.max_log_bytes)
        )
        tasks = {wait_task, stdout_task, stderr_task}
        try:
            done, pending = await asyncio.wait(
                tasks,
                timeout=limits.wall_time_seconds,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            log_failure = next(
                (
                    task.exception()
                    for task in done
                    if not task.cancelled()
                    and isinstance(task.exception(), _BoundedLogError)
                ),
                None,
            )
            if log_failure is not None:
                await _kill_process(process)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                raise PluginGuestRunError(
                    PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
                    str(log_failure),
                ) from log_failure
            if pending:
                await _kill_process(process)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                raise PluginGuestRunError(
                    PluginFailureCode.TIMEOUT,
                    f"Plugin guest exceeded {limits.wall_time_seconds} seconds",
                )
            wait_task.result()
            stdout_task.result()
            stderr_task.result()
            return_code = process.returncode
            if return_code != 0:
                raise PluginGuestRunError(
                    PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
                    f"Plugin guest subprocess exited with status {return_code}",
                )
        except asyncio.CancelledError:
            await _kill_process(process)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


@dataclass(frozen=True, slots=True)
class _ValidatedInlineOutputArtifact:
    payload: JsonObject
    byte_count: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class _ValidatedTableOutputArtifact:
    path: Path
    manifest: TableBundleManifest
    byte_count: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class _ValidatedBinaryOutputArtifact:
    path: Path
    content_type: str
    byte_count: int
    content_sha256: str
    metadata: JsonObject


@dataclass(frozen=True, slots=True)
class _ValidatedObjectSetOutputArtifact:
    manifest: ObjectSetBundleManifest
    contents: Mapping[str, bytes]
    byte_count: int
    content_sha256: str


type _ValidatedOutputArtifact = (
    _ValidatedInlineOutputArtifact
    | _ValidatedTableOutputArtifact
    | _ValidatedBinaryOutputArtifact
    | _ValidatedObjectSetOutputArtifact
)


def _canonical_payload_bytes(payload: JsonObject) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _resolved_artifact_type(
    port: PluginPortContract,
    bindings: Mapping[str, ArtifactTypeKey],
) -> ArtifactTypeKey:
    if port.artifact_type is not None:
        return ArtifactTypeKey(
            port.artifact_type.id,
            port.artifact_type.schema_version,
        )
    variable = port.artifact_type_variable
    if variable is None or variable not in bindings:
        raise PluginInvocationError(
            f"Plugin port {port.name!r} has no concrete artifact type"
        )
    return bindings[variable]


def _input_groups(
    port: PluginPortContract,
    value: object,
) -> list[ArtifactRef | ArtifactRefSequence]:
    if port.instance_plugs or port.variadic:
        if not isinstance(value, list):
            raise PluginInvocationError(
                f"Plugin input {port.name!r} expected one artifact "
                "container per incoming edge"
            )
        groups = cast(list[object], value)
        if any(
            not isinstance(group, ArtifactRef | ArtifactRefSequence) for group in groups
        ):
            raise PluginInvocationError(
                f"Plugin input {port.name!r} contains a non-reference input group"
            )
        return cast(list[ArtifactRef | ArtifactRefSequence], groups)
    if not isinstance(value, ArtifactRef | ArtifactRefSequence):
        raise PluginInvocationError(
            f"Plugin input {port.name!r} is not an artifact reference container"
        )
    return [value]


def _group_refs(
    port: PluginPortContract,
    group: ArtifactRef | ArtifactRefSequence,
    expected: ArtifactTypeKey,
) -> tuple[PluginArtifactShape, list[ArtifactRef]]:
    if isinstance(group, ArtifactRef):
        if port.shape != "one":
            raise PluginInvocationError(
                f"Plugin input {port.name!r} expected cardinality many"
            )
        refs = [group]
        shape = "one"
    else:
        if port.shape != "many":
            raise PluginInvocationError(
                f"Plugin input {port.name!r} expected cardinality one"
            )
        refs = list(group.item_refs)
        shape = "many"
    if any(ref.key() != expected for ref in refs):
        raise PluginInvocationError(
            f"Plugin input {port.name!r} does not match "
            f"{expected.id}@{expected.schema_version}"
        )
    return shape, refs


def _bundle_path(invocation_root: Path, relative_path: str) -> Path:
    root = invocation_root.resolve()
    path = invocation_root.joinpath(*relative_path.split("/"))
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise PluginInvocationError("Plugin bundle path escapes invocation scratch")
    return path


def _bundle_contract_for(
    request: PluginInvocationRequest,
    key: ArtifactTypeKey,
) -> PluginArtifactBundleContract:
    contract = request.artifact_bundle_contracts.get(key)
    if contract is None:
        raise PluginInvocationError(
            f"Plugin release does not declare a portable bundle for "
            f"{key.id}@{key.schema_version}"
        )
    return contract


def _referenced_artifact_refs(
    artifact: ArtifactObject,
    contracts: tuple[PluginArtifactReferenceContract, ...],
) -> list[ArtifactRef]:
    if not contracts:
        return []
    payload = artifact.inline_payload
    if payload is None:
        raise PluginInvocationError(
            f"Artifact {artifact.id} declares references without inline JSON"
        )
    refs: list[ArtifactRef] = []
    for contract in contracts:
        value: object = payload
        for segment in contract.path:
            if not isinstance(value, dict) or segment not in value:
                rendered_path = ".".join(contract.path)
                raise PluginInvocationError(
                    f"Artifact {artifact.id} is missing declared reference "
                    f"field {rendered_path!r}"
                )
            mapping = cast(dict[str, object], value)
            value = mapping[segment]
        if contract.shape == "many" and not isinstance(value, list):
            rendered_path = ".".join(contract.path)
            raise PluginInvocationError(
                f"Artifact {artifact.id} reference field {rendered_path!r} "
                f"does not have {contract.shape!r} shape"
            )
        values = cast(list[object], value) if contract.shape == "many" else [value]
        for raw_ref in values:
            try:
                ref = ArtifactRef.model_validate(raw_ref)
            except Exception as exc:
                rendered_path = ".".join(contract.path)
                raise PluginInvocationError(
                    f"Artifact {artifact.id} reference field "
                    f"{rendered_path!r} contains an invalid artifact reference"
                ) from exc
            expected = ArtifactTypeKey(
                contract.target.id,
                contract.target.schema_version,
            )
            if ref.key() != expected:
                rendered_path = ".".join(contract.path)
                raise PluginInvocationError(
                    f"Artifact {artifact.id} reference field {rendered_path!r} "
                    f"must target {expected.id}@{expected.schema_version}"
                )
            refs.append(ref)
    return refs


@final
class ArtifactBundlePluginInvoker(PluginInvoker):
    """Authorize refs, exchange inline bundles, and mint host output refs."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWorkPort,
        runner: PluginGuestRunner,
        limits: PluginInvocationLimits | None = None,
        scratch_root: Path | None = None,
        scratch: PluginInvocationScratch | None = None,
        storage: FileStoragePort | None = None,
        bucket: str = "artifacts",
        storage_backend: str = "local",
        max_concurrent_invocations: int = 4,
        wall_time_seconds_by_plugin_slug: Mapping[str, int] | None = None,
        node_secrets: NodeSecretResolverPort | None = None,
        uploads_dir: Path | None = None,
    ) -> None:
        if scratch_root is not None and scratch is not None:
            raise ValueError(
                "Plugin invocation scratch path and provider are mutually exclusive"
            )
        if max_concurrent_invocations < 1:
            raise ValueError("Maximum concurrent Plugin invocations must be positive")
        self._unit_of_work = unit_of_work
        self._runner = runner
        self._limits = limits or PluginInvocationLimits()
        self._limits_by_plugin_slug = {
            slug: PluginInvocationLimits.model_validate(
                {
                    **self._limits.model_dump(),
                    "wall_time_seconds": seconds,
                }
            )
            for slug, seconds in (wall_time_seconds_by_plugin_slug or {}).items()
        }
        self._scratch_root = scratch_root
        self._scratch = scratch
        self._storage = storage
        self._bucket = bucket
        self._storage_backend = storage_backend
        self._node_secrets = node_secrets or UnavailableNodeSecretResolver()
        self._uploads_dir = (
            None if uploads_dir is None else uploads_dir.expanduser().resolve()
        )
        self._max_concurrent_invocations = max_concurrent_invocations
        self._invocation_capacity = asyncio.Semaphore(max_concurrent_invocations)
        self._active_invocations = 0
        self._waiting_invocations = 0
        self._total_invocations = 0
        self._completed_invocations = 0
        self._failed_invocations = 0

    @override
    async def invoke(
        self,
        request: PluginInvocationRequest,
        /,
    ) -> PluginInvocationResult:
        self._total_invocations += 1
        self._waiting_invocations += 1
        try:
            await self._invocation_capacity.acquire()
        except BaseException:
            self._waiting_invocations -= 1
            self._failed_invocations += 1
            raise
        self._waiting_invocations -= 1
        self._active_invocations += 1
        try:
            result = await self._invoke_with_capacity(request)
        except BaseException:
            self._failed_invocations += 1
            raise
        else:
            self._completed_invocations += 1
            return result
        finally:
            self._active_invocations -= 1
            self._invocation_capacity.release()

    def diagnostics(self) -> PluginInvocationCapacityDiagnostics:
        return PluginInvocationCapacityDiagnostics(
            max_active_invocations=self._max_concurrent_invocations,
            active_invocations=self._active_invocations,
            waiting_invocations=self._waiting_invocations,
            total_invocations=self._total_invocations,
            completed_invocations=self._completed_invocations,
            failed_invocations=self._failed_invocations,
        )

    async def _invoke_with_capacity(
        self,
        request: PluginInvocationRequest,
    ) -> PluginInvocationResult:
        if request.release.protocol_digest != plugin_protocol_digest():
            raise PluginInvocationError(
                f"Plugin {request.release.slug!r} revision "
                f"{request.release.revision} uses an unsupported invocation "
                "protocol"
            )
        scratch_parent = None
        resolved_scratch_root = self._scratch_root
        if self._scratch is not None:
            resolved_scratch_root = self._scratch.root_for(request)
        if resolved_scratch_root is not None:
            resolved_scratch_root.mkdir(parents=True, exist_ok=True)
            scratch_parent = str(resolved_scratch_root)
        with TemporaryDirectory(
            prefix="grafy-plugin-invocation-",
            dir=scratch_parent,
        ) as temporary_directory:
            invocation_root = Path(temporary_directory)
            (invocation_root / "inputs").mkdir(mode=0o700)
            (invocation_root / "outputs").mkdir(mode=0o700)
            (invocation_root / "secrets").mkdir(mode=0o700)
            invocation_limits = self._limits_by_plugin_slug.get(
                request.release.slug,
                self._limits,
            )
            envelope = await self._stage_inputs(
                request,
                invocation_root,
                invocation_limits,
            )
            (invocation_root / "invocation.json").write_bytes(
                envelope.canonical_json_bytes()
            )
            try:
                await self._runner.run(invocation_root, invocation_limits, request)
            except PluginGuestRunError as exc:
                raise PluginInvocationError(
                    f"Plugin {request.release.slug!r} revision "
                    f"{request.release.revision} {exc.code.value} during "
                    f"invocation {envelope.invocation_id} for workflow "
                    f"{request.workflow_run_id}, node {request.node_id!r}, "
                    f"MAP index {request.invocation_index}: {exc}",
                    failure_code=exc.code,
                ) from exc
            result = self._read_result(invocation_root, envelope)
            progress_context = request.progress_context
            if progress_context is not None:
                for event in result.progress:
                    await progress_context.progress(
                        event.message,
                        current=event.current,
                        total=event.total,
                    )
            if result.status == "failed":
                failure = result.failure
                if failure is None:
                    raise PluginInvocationError(
                        "Plugin returned a failed result without context"
                    )
                raise PluginInvocationError(
                    f"Plugin {failure.release_slug!r} revision "
                    f"{failure.release_revision} operator {failure.operator_id}@"
                    f"{failure.operator_version} {failure.code.value}: "
                    f"{failure.message}",
                    failure_code=failure.code,
                    user_facing=True,
                )
            validated_outputs = self._validate_outputs(
                invocation_root,
                envelope,
                result,
            )
            return await self._import_outputs(request, validated_outputs)

    async def _stage_table_input(
        self,
        artifact: ArtifactObject,
        path: Path,
    ) -> tuple[int, str, int]:
        try:
            if artifact.inline_payload is not None:
                table = Table.model_validate(artifact.inline_payload)
                if len(table.rows) > self._limits.max_table_rows:
                    raise PluginInvocationError(
                        "Plugin Table input exceeds its row limit"
                    )
                if len(table.columns) > self._limits.max_table_columns:
                    raise PluginInvocationError(
                        "Plugin Table input exceeds its column limit"
                    )
                manifest = write_table_bundle(path, table)
            else:
                if self._storage is None:
                    raise PluginInvocationError(
                        "Plugin Table input requires artifact storage"
                    )
                source_manifest = await load_table_manifest(artifact, self._storage)
                if artifact.bucket is None:
                    raise PluginInvocationError(
                        f"Plugin Table artifact {artifact.id} has no bucket"
                    )
                if artifact.byte_size is None or artifact.sha256 is None:
                    raise PluginInvocationError(
                        f"Plugin Table artifact {artifact.id} has no "
                        "logical content identity"
                    )
                if source_manifest.row_count > self._limits.max_table_rows:
                    raise PluginInvocationError(
                        "Plugin Table input exceeds its row limit"
                    )
                if len(source_manifest.columns) > self._limits.max_table_columns:
                    raise PluginInvocationError(
                        "Plugin Table input exceeds its column limit"
                    )
                if len(source_manifest.chunks) > self._limits.max_table_chunks:
                    raise PluginInvocationError(
                        "Plugin Table input exceeds its chunk limit"
                    )
                canonical_root = (
                    f"workspaces/{artifact.workspace_id}/{TABLE_DATA.key.id}/"
                    f"v{TABLE_DATA.key.schema_version}"
                )
                manifest_sha256 = artifact.metadata.get("manifest_sha256")
                if (
                    not isinstance(manifest_sha256, str)
                    or artifact.object_key
                    != f"{canonical_root}/manifests/{manifest_sha256}.json"
                ):
                    raise PluginInvocationError(
                        f"Plugin Table artifact {artifact.id} has a "
                        "non-canonical manifest object"
                    )
                manifest = TableBundleManifest(
                    columns=tuple(source_manifest.columns),
                    row_count=source_manifest.row_count,
                    logical_byte_size=artifact.byte_size,
                    logical_sha256=artifact.sha256,
                    chunks=tuple(
                        TableBundleChunkDescriptor(
                            offset=descriptor.offset,
                            row_count=descriptor.row_count,
                            relative_path=f"chunks/{index:06d}.json",
                            byte_size=descriptor.byte_size,
                            sha256=descriptor.sha256,
                        )
                        for index, descriptor in enumerate(source_manifest.chunks)
                    ),
                )
                with TemporaryDirectory(
                    prefix="grafy-table-export-",
                    dir=path.parent,
                ) as staging_directory:
                    staged_paths: list[Path] = []
                    staged_byte_size = 0
                    for index, descriptor in enumerate(source_manifest.chunks):
                        expected_object_key = (
                            f"{canonical_root}/chunks/{descriptor.sha256}.json"
                        )
                        if descriptor.object_key != expected_object_key:
                            raise PluginInvocationError(
                                f"Plugin Table artifact {artifact.id} "
                                f"references a non-canonical chunk at offset "
                                f"{descriptor.offset}"
                            )
                        staged_byte_size += descriptor.byte_size
                        if staged_byte_size > self._limits.max_input_bytes:
                            raise PluginInvocationError(
                                "Plugin Table input exceeds its byte limit"
                            )
                        stream = await self._storage.load(
                            artifact.bucket,
                            descriptor.object_key,
                        )
                        try:
                            content = stream.read(descriptor.byte_size + 1)
                        finally:
                            stream.close()
                        if (
                            len(content) != descriptor.byte_size
                            or sha256(content).hexdigest() != descriptor.sha256
                        ):
                            raise PluginInvocationError(
                                f"Plugin Table artifact {artifact.id} "
                                f"chunk at offset {descriptor.offset} failed "
                                "stored content validation"
                            )
                        chunk = TableChunk.model_validate_json(content)
                        if (
                            chunk.offset != descriptor.offset
                            or len(chunk.rows) != descriptor.row_count
                            or chunk.model_dump_json().encode("utf-8") != content
                        ):
                            raise PluginInvocationError(
                                f"Plugin Table artifact {artifact.id} "
                                f"chunk at offset {descriptor.offset} does not "
                                "match its manifest"
                            )
                        staged_path = Path(staging_directory) / f"{index:06d}.json"
                        staged_path.write_bytes(content)
                        staged_paths.append(staged_path)
                    write_table_bundle_archive(
                        path,
                        manifest,
                        (
                            (descriptor, staged_path.read_bytes())
                            for descriptor, staged_path in zip(
                                manifest.chunks,
                                staged_paths,
                                strict=True,
                            )
                        ),
                    )

            validated_manifest = validate_table_bundle(
                path,
                max_bytes=self._limits.max_input_bytes,
                max_files=self._limits.max_files,
                max_rows=self._limits.max_table_rows,
                max_columns=self._limits.max_table_columns,
                max_chunks=self._limits.max_table_chunks,
            )
            if (
                artifact.byte_size is not None
                and artifact.byte_size != validated_manifest.logical_byte_size
            ) or (
                artifact.sha256 is not None
                and artifact.sha256 != validated_manifest.logical_sha256
            ):
                raise PluginInvocationError(
                    f"Plugin Table artifact {artifact.id} logical "
                    "content metadata is stale"
                )
            identity = file_identity(path)
            path.chmod(0o400)
            return (
                identity.byte_size,
                identity.sha256,
                1 + len(validated_manifest.chunks),
            )
        except PluginInvocationError:
            raise
        except Exception as exc:
            raise PluginInvocationError(
                f"Plugin Table artifact {artifact.id} could not be staged"
            ) from exc

    async def _stage_binary_input(
        self,
        artifact: ArtifactObject,
        path: Path,
    ) -> tuple[int, str]:
        if (
            self._storage is None
            or artifact.bucket is None
            or artifact.object_key is None
            or artifact.byte_size is None
            or artifact.sha256 is None
        ):
            raise PluginInvocationError(
                f"Plugin binary artifact {artifact.id} is not backed by "
                "exact durable content"
            )
        stream = await self._storage.load(artifact.bucket, artifact.object_key)
        try:
            content = stream.read(artifact.byte_size + 1)
        finally:
            stream.close()
        digest = sha256(content).hexdigest()
        if len(content) != artifact.byte_size or digest != artifact.sha256:
            raise PluginInvocationError(
                f"Plugin binary artifact {artifact.id} failed stored content validation"
            )
        path.write_bytes(content)
        path.chmod(0o400)
        return len(content), digest

    async def _stage_object_set_input(
        self,
        artifact: ArtifactObject,
        path: Path,
    ) -> tuple[int, str, int]:
        if (
            self._storage is None
            or artifact.bucket is None
            or artifact.object_key is None
            or artifact.byte_size is None
            or artifact.sha256 is None
        ):
            raise PluginInvocationError(
                f"Plugin object-set artifact {artifact.id} is not backed "
                "by exact durable content"
            )
        try:
            portable = portable_metadata(artifact.metadata)
            object_prefix = (
                f"workspaces/{artifact.workspace_id}/{artifact.artifact_type}/"
                f"v{artifact.schema_version}"
            )
            manifest = object_set_manifest(
                content_type=artifact.content_type,
                primary_object_key=artifact.object_key,
                logical_byte_size=artifact.byte_size,
                logical_sha256=artifact.sha256,
                metadata=artifact.metadata,
                portable=portable,
                object_prefix=object_prefix,
            )
            contents: dict[str, bytes] = {}
            total_bytes = 0
            paths_by_object = {
                source.object_key: descriptor.relative_path
                for source, descriptor in zip(
                    portable.files,
                    manifest.files,
                    strict=True,
                )
            }
            for source in portable.files:
                stream = await self._storage.load(
                    artifact.bucket,
                    source.object_key,
                )
                try:
                    content = stream.read(source.byte_size + 1)
                finally:
                    stream.close()
                if (
                    len(content) != source.byte_size
                    or sha256(content).hexdigest() != source.sha256
                ):
                    raise PluginInvocationError(
                        f"Plugin object-set artifact {artifact.id} file "
                        f"{source.object_key!r} failed stored content validation"
                    )
                total_bytes += len(content)
                if total_bytes > self._limits.max_input_bytes:
                    raise PluginInvocationError(
                        "Plugin object-set input exceeds its byte limit"
                    )
                contents[paths_by_object[source.object_key]] = content
            write_object_set_bundle(path, manifest, contents)
            identity = file_identity(path)
            path.chmod(0o400)
            return identity.byte_size, identity.sha256, 1 + len(manifest.files)
        except PluginInvocationError:
            raise
        except Exception as exc:
            raise PluginInvocationError(
                f"Plugin object-set artifact {artifact.id} could not be staged"
            ) from exc

    async def _stage_input_artifact_bundle(
        self,
        artifact: ArtifactObject,
        ref: ArtifactRef,
        bundle_contract: PluginArtifactBundleContract,
        path: Path,
    ) -> tuple[int, str, int]:
        path.parent.mkdir(parents=True, exist_ok=True)
        if bundle_contract.format == "table-bundle":
            return await self._stage_table_input(artifact, path)
        if bundle_contract.format == "binary-file":
            byte_count, content_digest = await self._stage_binary_input(
                artifact,
                path,
            )
            return byte_count, content_digest, 1
        if bundle_contract.format == "object-set":
            return await self._stage_object_set_input(artifact, path)
        if bundle_contract.format != "inline-json":
            raise PluginInvocationError(
                f"Plugin bundle adapter {bundle_contract.format}@"
                f"{bundle_contract.version} is unavailable"
            )
        payload = artifact.inline_payload
        if payload is None:
            raise PluginInvocationError(
                f"Plugin input artifact {ref.artifact_id} is not supported by "
                "the inline JSON protocol"
            )
        content = _canonical_payload_bytes(payload)
        content_digest = sha256(content).hexdigest()
        if (
            artifact.byte_size != len(content)
            or artifact.sha256 != content_digest
            or ref.content_hash != content_digest
        ):
            raise PluginInvocationError(
                f"Plugin input artifact {ref.artifact_id} content metadata is stale"
            )
        path.write_bytes(content)
        path.chmod(0o400)
        return len(content), content_digest, 1

    async def _save_content_addressed_output(
        self,
        command: SaveFileCommand,
        *,
        expected_byte_size: int,
        expected_sha256: str,
    ) -> tuple[StoredFile, bool]:
        storage = self._storage
        if storage is None:
            raise PluginInvocationError("Plugin Table output requires artifact storage")
        try:
            stored = await storage.save(command)
        except ObjectAlreadyExistsError:
            stream = await storage.load(command.bucket, command.path)
            try:
                content = stream.read(expected_byte_size + 1)
            finally:
                stream.close()
            if (
                len(content) != expected_byte_size
                or sha256(content).hexdigest() != expected_sha256
            ):
                raise PluginInvocationError(
                    "Plugin Table output collided with invalid "
                    f"content-addressed object {command.bucket}/{command.path}"
                )
            return (
                StoredFile(
                    bucket=command.bucket,
                    path=command.path,
                    etag=None,
                    version_id=None,
                    byte_size=expected_byte_size,
                    sha256=expected_sha256,
                ),
                False,
            )
        if stored.byte_size != expected_byte_size or stored.sha256 != expected_sha256:
            try:
                await storage.delete(stored.bucket, stored.path)
            except Exception as cleanup_exc:
                raise PluginInvocationError(
                    "Plugin Table output storage changed a new "
                    "content-addressed object and cleanup failed"
                ) from cleanup_exc
            raise PluginInvocationError(
                "Plugin Table output storage changed a new content-addressed object"
            )
        return stored, True

    async def _stage_secrets(
        self,
        request: PluginInvocationRequest,
        invocation_root: Path,
    ) -> tuple[PluginSecretBinding, ...]:
        bindings: list[PluginSecretBinding] = []
        total_secret_bytes = 0
        for index, declaration in enumerate(request.contract.secret_inputs):
            missing_dependencies = sorted(
                set(declaration.config_dependencies) - set(request.config)
            )
            if missing_dependencies:
                raise PluginInvocationError(
                    f"Plugin secret {declaration.name!r} has missing "
                    "configuration dependencies: " + ", ".join(missing_dependencies)
                )
            dependencies = cast(
                dict[str, JsonValue],
                {
                    name: request.config[name]
                    for name in declaration.config_dependencies
                },
            )
            dependency_digest = node_secret_dependency_sha256(dependencies)
            try:
                secret = await self._node_secrets.resolve_secret(
                    workspace_id=request.workspace_id,
                    graph_id=request.secret_graph_id,
                    graph_revision=request.secret_graph_revision,
                    node_id=request.node_id,
                    name=declaration.name,
                    dependencies=dependencies,
                )
            except Exception as exc:
                raise PluginInvocationError(
                    f"Plugin secret {declaration.name!r} could not be "
                    "resolved for this exact invocation"
                ) from exc
            content = secret.get_secret_value().encode("utf-8")
            if not content:
                raise PluginInvocationError(
                    f"Plugin secret {declaration.name!r} must not be empty"
                )
            total_secret_bytes += len(content)
            if total_secret_bytes > self._limits.max_secret_bytes:
                raise PluginInvocationError(
                    "Plugin staged secrets exceed their byte limit"
                )
            relative_path = f"secrets/s{index:04d}-{declaration.name}"
            path = _bundle_path(invocation_root, relative_path)
            path.write_bytes(content)
            path.chmod(0o400)
            bindings.append(
                PluginSecretBinding(
                    name=declaration.name,
                    config_dependencies=declaration.config_dependencies,
                    dependency_digest=dependency_digest,
                    relative_path=relative_path,
                )
            )
        return tuple(bindings)

    async def _stage_uploads(
        self,
        request: PluginInvocationRequest,
        invocation_root: Path,
    ) -> tuple[tuple[PluginStagedUploadBinding, ...], int, int]:
        if not request.contract.staged_upload_inputs:
            return (), 0, 0
        if self._uploads_dir is None:
            raise PluginInvocationError("Plugin staged-upload adapter is unavailable")
        requested: list[tuple[str, str, str, int]] = []
        for declaration in request.contract.staged_upload_inputs:
            raw_items = request.config.get(declaration.config_field)
            if not isinstance(raw_items, list):
                raise PluginInvocationError(
                    f"Plugin staged-upload field "
                    f"{declaration.config_field!r} must be a list"
                )
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    raise PluginInvocationError(
                        "Plugin staged-upload items must be objects"
                    )
                upload_key = raw_item.get("upload_key")
                filename = raw_item.get("filename")
                byte_size = raw_item.get("byte_size")
                if (
                    not isinstance(upload_key, str)
                    or not isinstance(filename, str)
                    or not isinstance(byte_size, int)
                    or isinstance(byte_size, bool)
                    or byte_size < 0
                ):
                    raise PluginInvocationError(
                        "Plugin staged-upload item must declare exact "
                        "upload_key, filename, and byte_size values"
                    )
                requested.append(
                    (declaration.config_field, upload_key, filename, byte_size)
                )
        if len(requested) > self._limits.max_files:
            raise PluginInvocationError(
                "Plugin staged uploads exceed their file-count limit"
            )
        keys = [upload_key for _, upload_key, _, _ in requested]
        if len(keys) != len(set(keys)):
            raise PluginInvocationError("Plugin staged-upload keys must be unique")
        records = {}
        plugin_uow = cast(PluginUnitOfWorkPort, self._unit_of_work)
        async with plugin_uow as entered:
            for upload_key in keys:
                record = await entered.staged_uploads.get(
                    request.workspace_id,
                    upload_key,
                )
                if record is None:
                    raise PluginInvocationError(
                        f"Plugin staged upload {upload_key!r} is "
                        "missing or unauthorized"
                    )
                records[upload_key] = record
        bindings: list[PluginStagedUploadBinding] = []
        total_bytes = 0
        for index, (config_field, upload_key, filename, byte_size) in enumerate(
            requested
        ):
            record = records[upload_key]
            if (
                record.workspace_id != request.workspace_id
                or record.original_filename != filename
                or record.byte_size != byte_size
            ):
                raise PluginInvocationError(
                    f"Plugin staged upload {upload_key!r} metadata "
                    "does not match its authorized record"
                )
            source = resolve_staged_upload_path(
                self._uploads_dir,
                workspace_id=request.workspace_id,
                upload_key=upload_key,
            )
            if source.is_symlink() or not source.is_file():
                raise PluginInvocationError(
                    f"Plugin staged upload {upload_key!r} is not a regular file"
                )
            relative_path = f"uploads/{request.workspace_id}/{upload_key}"
            destination = _bundle_path(invocation_root, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = sha256()
            copied = 0
            with source.open("rb") as source_stream, destination.open("xb") as output:
                while chunk := source_stream.read(1 * 1_024 * 1_024):
                    copied += len(chunk)
                    total_bytes += len(chunk)
                    if copied > byte_size or total_bytes > self._limits.max_input_bytes:
                        raise PluginInvocationError(
                            "Plugin staged uploads exceed their byte limit"
                        )
                    digest.update(chunk)
                    output.write(chunk)
            if copied != byte_size:
                raise PluginInvocationError(
                    f"Plugin staged upload {upload_key!r} changed size"
                )
            destination.chmod(0o400)
            bindings.append(
                PluginStagedUploadBinding(
                    config_field=config_field,
                    upload_key=upload_key,
                    original_filename=filename,
                    byte_count=copied,
                    content_sha256=digest.hexdigest(),
                    relative_path=relative_path,
                )
            )
        return tuple(bindings), total_bytes, len(bindings)

    async def _load_referenced_input_artifacts(
        self,
        request: PluginInvocationRequest,
        direct_artifacts: Mapping[UUID, ArtifactObject],
    ) -> dict[UUID, ArtifactObject]:
        known_artifacts = dict(direct_artifacts)
        dependencies: dict[UUID, ArtifactObject] = {}
        pending = list(direct_artifacts.values())
        while pending:
            refs_by_id: dict[UUID, ArtifactRef] = {}
            for artifact in pending:
                contracts = request.artifact_reference_contracts.get(
                    ArtifactTypeKey(
                        artifact.artifact_type,
                        artifact.schema_version,
                    ),
                    (),
                )
                for ref in _referenced_artifact_refs(artifact, contracts):
                    existing_ref = refs_by_id.get(ref.artifact_id)
                    if existing_ref is not None and existing_ref != ref:
                        raise PluginInvocationError(
                            f"Artifact {artifact.id} contains conflicting refs for "
                            f"artifact {ref.artifact_id}"
                        )
                    known = known_artifacts.get(ref.artifact_id)
                    if known is not None:
                        if known.ref() != ref:
                            raise PluginInvocationError(
                                f"Artifact {artifact.id} contains a stale or "
                                f"type-mismatched ref for artifact {ref.artifact_id}"
                            )
                        continue
                    refs_by_id[ref.artifact_id] = ref
            if not refs_by_id:
                break
            if len(dependencies) + len(refs_by_id) > 10_000:
                raise PluginInvocationError(
                    "Plugin input references more than 10000 artifacts"
                )
            async with self._unit_of_work as unit_of_work:
                loaded = await unit_of_work.artifacts.get_many(
                    request.workspace_id,
                    set(refs_by_id),
                )
            next_pending: list[ArtifactObject] = []
            for artifact_id, ref in refs_by_id.items():
                artifact = loaded.get(artifact_id)
                if artifact is None:
                    raise PluginInvocationError(
                        f"Plugin input references inaccessible or missing artifact "
                        f"{artifact_id}"
                    )
                if artifact.ref() != ref:
                    raise PluginInvocationError(
                        f"Plugin input contains a stale or type-mismatched ref for "
                        f"artifact {artifact_id}"
                    )
                known_artifacts[artifact_id] = artifact
                dependencies[artifact_id] = artifact
                next_pending.append(artifact)
            pending = next_pending
        return dependencies

    async def _stage_inputs(
        self,
        request: PluginInvocationRequest,
        invocation_root: Path,
        invocation_limits: PluginInvocationLimits,
    ) -> PluginInvocationEnvelope:
        ports_by_name = {port.name: port for port in request.contract.inputs}
        unknown_inputs = sorted(set(request.inputs) - set(ports_by_name))
        if unknown_inputs:
            raise PluginInvocationError(
                f"Plugin invocation contains unknown inputs: "
                f"{', '.join(unknown_inputs)}"
            )
        missing_inputs = sorted(
            port.name
            for port in request.contract.inputs
            if port.required and port.name not in request.inputs
        )
        if missing_inputs:
            raise PluginInvocationError(
                f"Plugin invocation is missing required inputs: "
                f"{', '.join(missing_inputs)}"
            )

        refs: list[ArtifactRef] = []
        staged_groups: dict[
            str,
            list[tuple[PluginArtifactShape, list[ArtifactRef]]],
        ] = {}
        for port in request.contract.inputs:
            if port.name not in request.inputs:
                continue
            expected = _resolved_artifact_type(
                port,
                request.artifact_type_bindings,
            )
            groups: list[tuple[PluginArtifactShape, list[ArtifactRef]]] = []
            for group in _input_groups(port, request.inputs[port.name]):
                shape, group_refs = _group_refs(port, group, expected)
                groups.append((shape, group_refs))
                refs.extend(group_refs)
            staged_groups[port.name] = groups

        artifact_ids = {ref.artifact_id for ref in refs}
        async with self._unit_of_work as unit_of_work:
            artifacts = await unit_of_work.artifacts.get_many(
                request.workspace_id,
                artifact_ids,
            )
        dependencies = await self._load_referenced_input_artifacts(
            request,
            artifacts,
        )

        bindings: list[PluginInputBinding] = []
        total_bytes = 0
        total_files = 0
        for port_index, port in enumerate(request.contract.inputs):
            if port.name not in staged_groups:
                continue
            expected = _resolved_artifact_type(
                port,
                request.artifact_type_bindings,
            )
            bundle_contract = _bundle_contract_for(request, expected)
            protocol_groups: list[PluginInputArtifactGroup] = []
            for group_index, (shape, group_refs) in enumerate(staged_groups[port.name]):
                bundles: list[PluginInputArtifactBundle] = []
                for artifact_index, ref in enumerate(group_refs):
                    artifact = artifacts.get(ref.artifact_id)
                    if artifact is None:
                        raise PluginInvocationError(
                            f"Plugin input {port.name!r} references an "
                            "inaccessible or missing artifact"
                        )
                    if artifact.ref() != ref:
                        raise PluginInvocationError(
                            f"Plugin input {port.name!r} contains a stale "
                            f"or type-mismatched ref for artifact {ref.artifact_id}"
                        )
                    relative_path = (
                        f"inputs/p{port_index:04d}/g{group_index:04d}/"
                        f"a{artifact_index:06d}"
                        f"{_INPUT_BUNDLE_SUFFIX[bundle_contract.format]}"
                    )
                    path = _bundle_path(invocation_root, relative_path)
                    (
                        byte_count,
                        content_digest,
                        file_count,
                    ) = await self._stage_input_artifact_bundle(
                        artifact,
                        ref,
                        bundle_contract,
                        path,
                    )
                    total_bytes += byte_count
                    total_files += file_count
                    if total_bytes > self._limits.max_input_bytes:
                        raise PluginInvocationError(
                            "Plugin aggregate input byte limit exceeded"
                        )
                    if total_files > self._limits.max_files:
                        raise PluginInvocationError(
                            "Plugin aggregate input file-count limit exceeded"
                        )
                    bundles.append(
                        PluginInputArtifactBundle(
                            artifact_id=ref.artifact_id,
                            relative_path=relative_path,
                            byte_count=byte_count,
                            content_sha256=content_digest,
                            content_type=artifact.content_type,
                            metadata=(
                                artifact.metadata
                                if bundle_contract.format == "binary-file"
                                else {}
                            ),
                        )
                    )
                protocol_groups.append(
                    PluginInputArtifactGroup(
                        shape=shape,
                        artifacts=tuple(bundles),
                    )
                )
            bindings.append(
                PluginInputBinding(
                    port=port.name,
                    artifact_type=PluginArtifactTypeKey.from_key(expected),
                    bundle=bundle_contract,
                    groups=tuple(protocol_groups),
                )
            )

        dependency_bindings: list[PluginInputArtifactDependency] = []
        for dependency_index, artifact in enumerate(
            sorted(dependencies.values(), key=lambda value: str(value.id))
        ):
            key = ArtifactTypeKey(
                artifact.artifact_type,
                artifact.schema_version,
            )
            bundle_contract = _bundle_contract_for(request, key)
            ref = artifact.ref()
            relative_path = (
                f"inputs/references/r{dependency_index:06d}"
                f"{_INPUT_BUNDLE_SUFFIX[bundle_contract.format]}"
            )
            path = _bundle_path(invocation_root, relative_path)
            (
                byte_count,
                content_digest,
                file_count,
            ) = await self._stage_input_artifact_bundle(
                artifact,
                ref,
                bundle_contract,
                path,
            )
            total_bytes += byte_count
            total_files += file_count
            if total_bytes > self._limits.max_input_bytes:
                raise PluginInvocationError(
                    "Plugin aggregate input byte limit exceeded"
                )
            if total_files > self._limits.max_files:
                raise PluginInvocationError(
                    "Plugin aggregate input file-count limit exceeded"
                )
            dependency_bindings.append(
                PluginInputArtifactDependency(
                    artifact_type=PluginArtifactTypeKey.from_key(key),
                    bundle=bundle_contract,
                    artifact=PluginInputArtifactBundle(
                        artifact_id=artifact.id,
                        relative_path=relative_path,
                        byte_count=byte_count,
                        content_sha256=content_digest,
                        content_type=artifact.content_type,
                        metadata=(
                            artifact.metadata
                            if bundle_contract.format == "binary-file"
                            else {}
                        ),
                    ),
                )
            )

        declarations: list[PluginOutputDeclaration] = []
        for port in request.contract.outputs:
            shape: PluginArtifactShape = "many" if port.shape == "many" else "one"
            output_key = _resolved_artifact_type(
                port,
                request.artifact_type_bindings,
            )
            declarations.append(
                PluginOutputDeclaration(
                    port=port.name,
                    artifact_type=PluginArtifactTypeKey.from_key(output_key),
                    bundle=_bundle_contract_for(request, output_key),
                    shape=shape,
                    required=port.required,
                )
            )
        invocation_id = uuid4()
        execution_scope_id = request.workflow_run_id or invocation_id
        secret_bindings = await self._stage_secrets(request, invocation_root)
        (
            staged_uploads,
            staged_upload_bytes,
            staged_upload_files,
        ) = await self._stage_uploads(request, invocation_root)
        if total_bytes + staged_upload_bytes > self._limits.max_input_bytes:
            raise PluginInvocationError("Plugin aggregate input byte limit exceeded")
        if total_files + staged_upload_files > self._limits.max_files:
            raise PluginInvocationError(
                "Plugin aggregate input file-count limit exceeded"
            )
        return PluginInvocationEnvelope(
            invocation_id=invocation_id,
            execution_scope_id=execution_scope_id,
            workspace_id=request.workspace_id,
            workflow_run_id=request.workflow_run_id,
            secret_graph_id=request.secret_graph_id,
            secret_graph_revision=request.secret_graph_revision,
            node_id=request.node_id,
            invocation_index=request.invocation_index,
            release=PluginInvocationRelease(
                scope=request.release.scope,
                workspace_id=request.release.workspace_id,
                slug=request.release.slug,
                revision=request.release.revision,
                source_digest=request.release.source_digest,
                contract_digest=request.release.contract_digest,
                protocol_digest=request.release.protocol_digest,
                descriptor_digest=request.release.descriptor_digest,
            ),
            operator_id=request.contract.operator_id,
            operator_version=request.contract.operator_version,
            required_capabilities=request.required_capabilities,
            artifact_type_bindings=tuple(
                PluginInvocationArtifactTypeBinding(
                    variable=variable,
                    artifact_type=PluginArtifactTypeKey.from_key(artifact_type),
                )
                for variable, artifact_type in sorted(
                    request.artifact_type_bindings.items()
                )
            ),
            config=request.config,
            inputs=tuple(bindings),
            input_artifact_dependencies=tuple(dependency_bindings),
            outputs=tuple(declarations),
            secrets=secret_bindings,
            staged_uploads=staged_uploads,
            limits=invocation_limits,
        )

    def _read_result(
        self,
        invocation_root: Path,
        request: PluginInvocationEnvelope,
    ) -> PluginInvocationResultEnvelope:
        result_path = invocation_root / "result.json"
        if result_path.is_symlink() or not result_path.is_file():
            raise PluginInvocationError(
                f"Plugin {request.release.slug!r} revision "
                f"{request.release.revision} returned no regular result manifest"
            )
        result_size = result_path.stat().st_size
        if result_size > _RESULT_MANIFEST_MAX_BYTES:
            raise PluginInvocationError(
                "Plugin result manifest exceeds the protocol limit"
            )
        try:
            result = PluginInvocationResultEnvelope.from_json_bytes(
                result_path.read_bytes()
            )
        except Exception as exc:
            raise PluginInvocationError(
                f"Plugin {request.release.slug!r} revision "
                f"{request.release.revision} returned an invalid result manifest"
            ) from exc
        if result.invocation_id != request.invocation_id:
            raise PluginInvocationError(
                "Plugin result invocation identity does not match its request"
            )
        if result.status == "failed":
            failure = result.failure
            if failure is None:
                raise PluginInvocationError(
                    "Plugin returned a failed result without context"
                )
            if (
                failure.release_slug != request.release.slug
                or failure.release_revision != request.release.revision
                or failure.operator_id != request.operator_id
                or failure.operator_version != request.operator_version
                or failure.node_id != request.node_id
                or failure.invocation_index != request.invocation_index
            ):
                raise PluginInvocationError(
                    "Plugin failure context does not match its request"
                )
        return result

    def _validate_outputs(
        self,
        invocation_root: Path,
        request: PluginInvocationEnvelope,
        result: PluginInvocationResultEnvelope,
    ) -> dict[str, list[_ValidatedOutputArtifact]]:
        declarations = {
            declaration.port: declaration for declaration in request.outputs
        }
        bindings = {binding.port: binding for binding in result.outputs}
        extra_ports = sorted(set(bindings) - set(declarations))
        if extra_ports:
            raise PluginInvocationError(
                f"Plugin returned undeclared outputs: {', '.join(extra_ports)}"
            )
        missing_ports = sorted(
            declaration.port
            for declaration in request.outputs
            if declaration.required and declaration.port not in bindings
        )
        if missing_ports:
            raise PluginInvocationError(
                f"Plugin omitted required outputs: {', '.join(missing_ports)}"
            )

        declared_paths = {
            artifact.relative_path
            for binding in result.outputs
            for artifact in binding.artifacts
        }
        actual_paths: set[str] = set()
        output_dir = invocation_root / "outputs"
        for path in output_dir.rglob("*"):
            if path.is_symlink():
                raise PluginInvocationError(
                    "Plugin output bundles must not contain symlinks"
                )
            if path.is_file():
                actual_paths.add(path.relative_to(invocation_root).as_posix())
        if actual_paths != declared_paths:
            raise PluginInvocationError(
                "Plugin output directory must contain exactly the declared bundle files"
            )

        validated: dict[str, list[_ValidatedOutputArtifact]] = {}
        total_bytes = 0
        total_files = 0
        for port, binding in bindings.items():
            declaration = declarations[port]
            if (
                binding.artifact_type != declaration.artifact_type
                or binding.shape != declaration.shape
                or binding.bundle != declaration.bundle
            ):
                raise PluginInvocationError(
                    f"Plugin output {port!r} does not match its declared "
                    "type or cardinality"
                )
            artifacts: list[_ValidatedOutputArtifact] = []
            for bundle in binding.artifacts:
                total_bytes += bundle.byte_count
                if total_bytes > request.limits.max_output_bytes:
                    raise PluginInvocationError(
                        "Plugin aggregate output byte limit exceeded"
                    )
                path = _bundle_path(invocation_root, bundle.relative_path)
                if path.is_symlink() or not path.is_file():
                    raise PluginInvocationError(
                        f"Plugin output bundle "
                        f"{bundle.relative_path!r} is not a regular file"
                    )
                identity = file_identity(path)
                if (
                    identity.byte_size != bundle.byte_count
                    or identity.sha256 != bundle.content_sha256
                ):
                    raise PluginInvocationError(
                        f"Plugin output bundle "
                        f"{bundle.relative_path!r} failed size or digest validation"
                    )
                if declaration.bundle.format == "table-bundle":
                    try:
                        manifest = validate_table_bundle(
                            path,
                            max_bytes=request.limits.max_output_bytes,
                            max_files=request.limits.max_files,
                            max_rows=request.limits.max_table_rows,
                            max_columns=request.limits.max_table_columns,
                            max_chunks=request.limits.max_table_chunks,
                        )
                    except TableBundleError as exc:
                        raise PluginInvocationError(
                            f"Plugin output Table bundle "
                            f"{bundle.relative_path!r} is invalid"
                        ) from exc
                    total_files += 1 + len(manifest.chunks)
                    artifacts.append(
                        _ValidatedTableOutputArtifact(
                            path=path,
                            manifest=manifest,
                            byte_count=bundle.byte_count,
                            content_sha256=bundle.content_sha256,
                        )
                    )
                elif declaration.bundle.format == "binary-file":
                    total_files += 1
                    artifacts.append(
                        _ValidatedBinaryOutputArtifact(
                            path=path,
                            content_type=bundle.content_type,
                            byte_count=bundle.byte_count,
                            content_sha256=bundle.content_sha256,
                            metadata=bundle.metadata,
                        )
                    )
                elif declaration.bundle.format == "object-set":
                    try:
                        object_manifest, contents = load_object_set_bundle(
                            path,
                            max_bytes=request.limits.max_output_bytes,
                            max_files=request.limits.max_files,
                        )
                    except ObjectSetBundleError as exc:
                        raise PluginInvocationError(
                            f"Plugin output object-set bundle "
                            f"{bundle.relative_path!r} is invalid"
                        ) from exc
                    total_files += 1 + len(object_manifest.files)
                    artifacts.append(
                        _ValidatedObjectSetOutputArtifact(
                            manifest=object_manifest,
                            contents=contents,
                            byte_count=bundle.byte_count,
                            content_sha256=bundle.content_sha256,
                        )
                    )
                elif declaration.bundle.format == "inline-json":
                    content = path.read_bytes()
                    value = json.loads(content)
                    if not isinstance(value, dict):
                        raise PluginInvocationError(
                            f"Plugin output bundle "
                            f"{bundle.relative_path!r} must contain one JSON object"
                        )
                    raw_payload = cast(dict[object, object], value)
                    if any(not isinstance(key, str) for key in raw_payload):
                        raise PluginInvocationError(
                            f"Plugin output bundle "
                            f"{bundle.relative_path!r} must contain one JSON object"
                        )
                    payload = cast(JsonObject, dict(raw_payload))
                    if _canonical_payload_bytes(payload) != content:
                        raise PluginInvocationError(
                            f"Plugin output bundle "
                            f"{bundle.relative_path!r} is not canonical inline JSON"
                        )
                    total_files += 1
                    artifacts.append(
                        _ValidatedInlineOutputArtifact(
                            payload=payload,
                            byte_count=len(content),
                            content_sha256=bundle.content_sha256,
                        )
                    )
                else:
                    raise PluginInvocationError(
                        f"Plugin output bundle adapter "
                        f"{declaration.bundle.format}@{declaration.bundle.version} "
                        "is unavailable"
                    )
                if total_files > request.limits.max_files:
                    raise PluginInvocationError(
                        "Plugin aggregate output file-count limit exceeded"
                    )
            validated[port] = artifacts
        return validated

    async def _import_outputs(
        self,
        request: PluginInvocationRequest,
        validated: Mapping[str, list[_ValidatedOutputArtifact]],
    ) -> PluginInvocationResult:
        artifacts_by_port: dict[str, list[ArtifactObject]] = {}
        created_objects: list[tuple[str, str]] = []
        ports_by_name = {port.name: port for port in request.contract.inputs}
        input_provenance: dict[str, object] = {}
        for name, value in request.inputs.items():
            provenance_entries: list[dict[str, object]] = []
            for group in _input_groups(ports_by_name[name], value):
                refs = (
                    group.item_refs
                    if isinstance(group, ArtifactRefSequence)
                    else [group]
                )
                provenance_entries.extend(
                    {
                        "artifact_id": str(ref.artifact_id),
                        "artifact_type": ref.artifact_type,
                        "schema_version": ref.schema_version,
                    }
                    for ref in refs
                )
            input_provenance[name] = provenance_entries
        try:
            for port in request.contract.outputs:
                bundles = validated.get(port.name)
                if bundles is None:
                    continue
                key = _resolved_artifact_type(port, request.artifact_type_bindings)
                artifacts: list[ArtifactObject] = []
                for bundle in bundles:
                    artifact_metadata: JsonObject = {
                        "producer_node_id": request.node_id,
                        "provenance": input_provenance,
                        "plugin_release": request.release.provenance_document(),
                    }
                    if isinstance(bundle, _ValidatedInlineOutputArtifact):
                        artifact = ArtifactObject(
                            workspace_id=request.workspace_id,
                            artifact_type=key.id,
                            schema_version=key.schema_version,
                            content_type="application/json",
                            storage_backend="inline",
                            inline_payload=bundle.payload,
                            byte_size=bundle.byte_count,
                            sha256=bundle.content_sha256,
                            metadata=artifact_metadata,
                        )
                    elif isinstance(bundle, _ValidatedBinaryOutputArtifact):
                        if self._storage is None:
                            raise PluginInvocationError(
                                "Plugin binary output requires artifact storage"
                            )
                        object_key = (
                            f"workspaces/{request.workspace_id}/{key.id}/"
                            f"v{key.schema_version}/files/"
                            f"{bundle.content_sha256}.bin"
                        )
                        content = bundle.path.read_bytes()
                        stored, created = await self._save_content_addressed_output(
                            SaveFileCommand(
                                bucket=self._bucket,
                                path=object_key,
                                stream=BytesIO(content),
                                content_type=bundle.content_type,
                                metadata={
                                    "artifact_kind": key.id,
                                    "sha256": bundle.content_sha256,
                                },
                                allow_overwrite=False,
                            ),
                            expected_byte_size=bundle.byte_count,
                            expected_sha256=bundle.content_sha256,
                        )
                        if created:
                            created_objects.append((stored.bucket, stored.path))
                        plugin_release_metadata = artifact_metadata["plugin_release"]
                        artifact_metadata.update(bundle.metadata)
                        artifact_metadata.update(
                            {
                                "producer_node_id": request.node_id,
                                "provenance": input_provenance,
                                "plugin_release": plugin_release_metadata,
                            }
                        )
                        artifact = ArtifactObject(
                            workspace_id=request.workspace_id,
                            artifact_type=key.id,
                            schema_version=key.schema_version,
                            content_type=bundle.content_type,
                            storage_backend=self._storage_backend,
                            bucket=stored.bucket,
                            object_key=stored.path,
                            byte_size=stored.byte_size,
                            sha256=stored.sha256,
                            metadata=artifact_metadata,
                        )
                    elif isinstance(bundle, _ValidatedObjectSetOutputArtifact):
                        if self._storage is None:
                            raise PluginInvocationError(
                                "Plugin object-set output requires artifact storage"
                            )
                        manifest_digest = sha256(
                            bundle.manifest.model_dump_json().encode("utf-8")
                        ).hexdigest()
                        destination_root = (
                            f"workspaces/{request.workspace_id}/{key.id}/"
                            f"v{key.schema_version}/bundles/{manifest_digest}"
                        )
                        paths: dict[str, str] = {}
                        stored_portable_files: list[PortableArtifactFile] = []
                        for descriptor in bundle.manifest.files:
                            suffix = descriptor.relative_path.removeprefix("files/")
                            object_key = f"{destination_root}/{suffix}"
                            content = bundle.contents[descriptor.relative_path]
                            stored, created = await self._save_content_addressed_output(
                                SaveFileCommand(
                                    bucket=self._bucket,
                                    path=object_key,
                                    stream=BytesIO(content),
                                    content_type=descriptor.content_type,
                                    metadata={
                                        "artifact_kind": key.id,
                                        "sha256": descriptor.sha256,
                                    },
                                    allow_overwrite=False,
                                ),
                                expected_byte_size=descriptor.byte_size,
                                expected_sha256=descriptor.sha256,
                            )
                            if created:
                                created_objects.append((stored.bucket, stored.path))
                            paths[descriptor.relative_path] = stored.path
                            stored_portable_files.append(
                                PortableArtifactFile(
                                    object_key=stored.path,
                                    byte_size=stored.byte_size,
                                    sha256=stored.sha256,
                                    content_type=descriptor.content_type,
                                )
                            )
                        restored_metadata = bundle.manifest.restored_metadata(
                            bucket=self._bucket,
                            paths=paths,
                        )
                        restored_metadata.update(artifact_metadata)
                        restored_metadata[PORTABLE_BUNDLE_METADATA_KEY] = (
                            PortableArtifactBundleMetadata(
                                files=tuple(stored_portable_files),
                                references=tuple(
                                    PortableMetadataReference(
                                        path=reference.path,
                                        kind=reference.kind,
                                    )
                                    for reference in bundle.manifest.references
                                ),
                            ).as_metadata_value()
                        )
                        primary_path = paths[bundle.manifest.primary_path]
                        artifact = ArtifactObject(
                            workspace_id=request.workspace_id,
                            artifact_type=key.id,
                            schema_version=key.schema_version,
                            content_type=bundle.manifest.content_type,
                            storage_backend=self._storage_backend,
                            bucket=self._bucket,
                            object_key=primary_path,
                            byte_size=bundle.manifest.logical_byte_size,
                            sha256=bundle.manifest.logical_sha256,
                            metadata=restored_metadata,
                        )
                    else:
                        if self._storage is None:
                            raise PluginInvocationError(
                                "Plugin Table output requires artifact storage"
                            )
                        stored_byte_size = 0
                        chunk_descriptors: list[TableChunkDescriptor] = []
                        for descriptor, content in iter_table_bundle_chunks(
                            bundle.path,
                            bundle.manifest,
                        ):
                            object_key = (
                                f"workspaces/{request.workspace_id}/"
                                f"{TABLE_DATA.key.id}/"
                                f"v{TABLE_DATA.key.schema_version}/chunks/"
                                f"{descriptor.sha256}.json"
                            )
                            metadata: FileMetadata = {
                                "artifact_kind": TABLE_DATA.key.id,
                                "sha256": descriptor.sha256,
                            }
                            if request.node_id is not None:
                                metadata["job_id"] = request.node_id
                            stored, created = await self._save_content_addressed_output(
                                SaveFileCommand(
                                    bucket=self._bucket,
                                    path=object_key,
                                    stream=BytesIO(content),
                                    content_type="application/json",
                                    metadata=metadata,
                                    allow_overwrite=False,
                                ),
                                expected_byte_size=descriptor.byte_size,
                                expected_sha256=descriptor.sha256,
                            )
                            if created:
                                created_objects.append((stored.bucket, stored.path))
                            stored_byte_size += stored.byte_size
                            chunk_descriptors.append(
                                TableChunkDescriptor(
                                    offset=descriptor.offset,
                                    row_count=descriptor.row_count,
                                    object_key=stored.path,
                                    byte_size=stored.byte_size,
                                    sha256=stored.sha256,
                                )
                            )
                        table_manifest = TableManifest(
                            columns=list(bundle.manifest.columns),
                            row_count=bundle.manifest.row_count,
                            chunks=chunk_descriptors,
                        )
                        manifest_content = table_manifest.model_dump_json().encode(
                            "utf-8"
                        )
                        manifest_sha256 = sha256(manifest_content).hexdigest()
                        manifest_path = (
                            f"workspaces/{request.workspace_id}/"
                            f"{TABLE_DATA.key.id}/"
                            f"v{TABLE_DATA.key.schema_version}/manifests/"
                            f"{manifest_sha256}.json"
                        )
                        (
                            stored_manifest,
                            created,
                        ) = await self._save_content_addressed_output(
                            SaveFileCommand(
                                bucket=self._bucket,
                                path=manifest_path,
                                stream=BytesIO(manifest_content),
                                content_type="application/json",
                                metadata={
                                    "artifact_kind": TABLE_DATA.key.id,
                                    "sha256": manifest_sha256,
                                },
                                allow_overwrite=False,
                            ),
                            expected_byte_size=len(manifest_content),
                            expected_sha256=manifest_sha256,
                        )
                        if created:
                            created_objects.append(
                                (stored_manifest.bucket, stored_manifest.path)
                            )
                        artifact_metadata.update(
                            {
                                "storage_format": table_manifest.format,
                                "row_count": table_manifest.row_count,
                                "column_count": len(table_manifest.columns),
                                "chunk_count": len(table_manifest.chunks),
                                "logical_byte_size": (
                                    bundle.manifest.logical_byte_size
                                ),
                                "storage_byte_size": (
                                    stored_byte_size + stored_manifest.byte_size
                                ),
                                "manifest_byte_size": stored_manifest.byte_size,
                                "manifest_sha256": stored_manifest.sha256,
                            }
                        )
                        artifact = ArtifactObject(
                            workspace_id=request.workspace_id,
                            artifact_type=key.id,
                            schema_version=key.schema_version,
                            content_type="application/json",
                            storage_backend=self._storage_backend,
                            bucket=stored_manifest.bucket,
                            object_key=stored_manifest.path,
                            byte_size=bundle.manifest.logical_byte_size,
                            sha256=bundle.manifest.logical_sha256,
                            metadata=artifact_metadata,
                        )
                    artifacts.append(artifact)
                artifacts_by_port[port.name] = artifacts

            async with self._unit_of_work as unit_of_work:
                for artifacts in artifacts_by_port.values():
                    for artifact in artifacts:
                        await unit_of_work.artifacts.add(artifact)
                await unit_of_work.commit()
        except Exception as exc:
            cleanup_failures: list[str] = []
            if self._storage is not None:
                for bucket, object_key in reversed(created_objects):
                    try:
                        await self._storage.delete(bucket, object_key)
                    except Exception as cleanup_exc:
                        cleanup_failures.append(
                            f"{bucket}/{object_key}: {type(cleanup_exc).__name__}"
                        )
            cleanup_context = ""
            if cleanup_failures:
                cleanup_context = "; partial object cleanup failed for " + ", ".join(
                    cleanup_failures
                )
            raise PluginInvocationError(
                f"Plugin {request.release.slug!r} revision "
                f"{request.release.revision} outputs could not be committed "
                f"atomically{cleanup_context}"
            ) from exc

        outputs: dict[str, ArtifactRef | ArtifactRefSequence] = {}
        for port in request.contract.outputs:
            output_artifacts = artifacts_by_port.get(port.name)
            if output_artifacts is None:
                continue
            refs = [artifact.ref() for artifact in output_artifacts]
            key = _resolved_artifact_type(port, request.artifact_type_bindings)
            if port.shape == "many":
                outputs[port.name] = ArtifactRefSequence.from_key(
                    key=key,
                    item_refs=refs,
                )
            else:
                outputs[port.name] = refs[0]
        return PluginInvocationResult(outputs=outputs)


__all__ = [
    "ArtifactBundlePluginInvoker",
    "PluginInvocationCapacityDiagnostics",
    "PluginGuestRunError",
    "PluginGuestRunner",
    "PluginInvocationScratch",
    "SubprocessPluginGuestRunner",
]
