"""Guest-side execution of one scalar isolated Plugin artifact invocation."""

import asyncio
import json
import sys
from hashlib import sha256
from io import BytesIO
from importlib import import_module
from pathlib import Path
from pathlib import PurePosixPath
from collections.abc import Mapping
from typing import Any, cast, final, override
from uuid import UUID

from pydantic import BaseModel, SecretStr, TypeAdapter

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.domain.plugin_releases import (
    PLUGIN_INVOCATION_PROTOCOL,
    PluginCatalogManifest,
    plugin_contract_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.node_secrets import (
    JsonValue,
    node_secret_dependency_sha256,
)
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.nodes import (
    InputContract,
    Node,
    NodeExecutionContext,
    OutputContract,
    UserFacingNodeError,
    resolve_node_contracts,
)
from grafy_core.plugins import Plugin, PluginRuntimeContext, PluginUnitOfWorkPort
from grafy_core.ports.storage import (
    FileStoragePort,
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_core.runtime.materialization import InputMaterializer, MaterializationError
from grafy_core.runtime.plugin_loader import (
    PluginGuestLoaderManifest,
    split_plugin_loader_target,
)
from grafy_core.runtime.object_set_bundle import (
    ObjectSetBundleError,
    load_object_set_bundle,
    object_set_manifest,
    portable_metadata,
    write_object_set_bundle,
)
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriteContext,
    ArtifactWriterRegistry,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.plugin_protocol import (
    MAX_PLUGIN_PROGRESS_BYTES,
    MAX_PLUGIN_PROGRESS_EVENTS,
    PluginFailureCode,
    PluginFailureEnvelope,
    PluginInputArtifactGroup,
    PluginInputBinding,
    PluginInvocationEnvelope,
    PluginInvocationRelease,
    PluginInvocationResultEnvelope,
    PluginOutputArtifactBundle,
    PluginOutputBinding,
    PluginProgressEvent,
)
from grafy_core.runtime.resolvers import Resolver, ResolverRegistry
from grafy_core.runtime.table_bundle import (
    TableBundleError,
    file_identity,
    load_table_bundle_with_manifest,
    write_table_bundle,
)
from grafy_core.table_contracts import Table


class PluginGuestError(RuntimeError):
    """The staged invocation cannot be executed by the guest runtime."""


SYSTEM_PLUGIN_LOADER_MANIFEST_PATH = Path("/opt/grafy/plugin/plugin-loader.json")


def load_guest_plugin(
    release: PluginInvocationRelease,
    *,
    system_loader_manifest_path: Path = SYSTEM_PLUGIN_LOADER_MANIFEST_PATH,
) -> tuple[Plugin, PluginCatalogManifest]:
    """Load the exact image-owned Plugin and verify its release contract."""

    loader_manifest = PluginGuestLoaderManifest.from_json_bytes(
        system_loader_manifest_path.read_bytes()
    )
    if loader_manifest.slug != release.slug:
        raise PluginGuestError(
            "Plugin loader manifest does not match the exact release"
        )
    loader_target = loader_manifest.loader_target
    module_name, attribute_name = split_plugin_loader_target(loader_target)
    module = import_module(module_name)
    plugin = getattr(module, attribute_name, None)
    if not isinstance(plugin, Plugin):
        raise PluginGuestError(
            f"Installed project must export Plugin target {loader_target}"
        )
    catalog = PluginCatalogManifest.from_plugin(plugin)
    if (
        plugin.slug != release.slug
        or plugin_contract_digest(catalog) != release.contract_digest
    ):
        raise PluginGuestError(
            "Installed Plugin contract does not match the exact release"
        )
    return plugin, catalog


@final
class _GuestProgressReporter:
    """Retain a bounded ordered progress stream for the result envelope."""

    def __init__(self) -> None:
        self._events: list[PluginProgressEvent] = []
        self._byte_count = 0

    @property
    def events(self) -> tuple[PluginProgressEvent, ...]:
        return tuple(self._events)

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        del context
        if len(self._events) >= MAX_PLUGIN_PROGRESS_EVENTS:
            return
        event = PluginProgressEvent(
            message=message,
            current=current,
            total=total,
        )
        event_bytes = len(event.canonical_json_bytes())
        if self._byte_count + event_bytes > MAX_PLUGIN_PROGRESS_BYTES:
            return
        self._events.append(event)
        self._byte_count += event_bytes


@final
class _UnavailableGuestStorage(FileStoragePort):
    """Fail closed if an inline-only invocation asks for durable storage."""

    @override
    async def save(self, command: SaveFileCommand) -> StoredFile:
        del command
        raise PluginGuestError("Guest durable storage is unavailable")

    @override
    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        del bucket, source_path, destination_path
        raise PluginGuestError("Guest durable storage is unavailable")

    @override
    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        del bucket, path
        raise PluginGuestError("Guest durable storage is unavailable")

    @override
    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        del bucket, path
        raise PluginGuestError("Guest durable storage is unavailable")

    @override
    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        del bucket, path, start, end_exclusive
        raise PluginGuestError("Guest durable storage is unavailable")

    @override
    async def delete(self, bucket: str, path: str) -> None:
        del bucket, path
        raise PluginGuestError("Guest durable storage is unavailable")


@final
class _GuestBundleStorage(FileStoragePort):
    """Bounded input capabilities and invocation-local output object storage."""

    def __init__(
        self, invocation_root: Path, request: PluginInvocationEnvelope
    ) -> None:
        self._root = invocation_root
        self._bundles = {
            artifact.relative_path: artifact
            for binding in request.inputs
            if binding.bundle.format == "binary-file"
            for group in binding.groups
            for artifact in group.artifacts
        }
        self._bundles.update(
            {
                dependency.artifact.relative_path: dependency.artifact
                for dependency in request.input_artifact_dependencies
                if dependency.bundle.format == "binary-file"
            }
        )
        self._input_objects: dict[str, tuple[bytes, str]] = {}
        self._output_objects: dict[str, tuple[bytes, str]] = {}
        self._max_output_bytes = request.limits.max_output_bytes
        self._max_files = request.limits.max_files

    def install_input_objects(
        self,
        paths: Mapping[str, tuple[bytes, str]],
    ) -> None:
        overlap = set(paths) & set(self._input_objects)
        if overlap:
            raise PluginGuestError("Guest object-set input paths overlap")
        if len(self._input_objects) + len(paths) > self._max_files:
            raise PluginGuestError("Guest object-set input exceeds its file limit")
        self._input_objects.update(paths)

    @property
    def output_paths(self) -> frozenset[str]:
        return frozenset(self._output_objects)

    def output_content(self, path: str) -> tuple[bytes, str]:
        try:
            return self._output_objects[path]
        except KeyError as exc:
            raise PluginGuestError(
                f"Guest output object {path!r} was not written"
            ) from exc

    def _content(self, bucket: str, path: str) -> bytes:
        if bucket == "guest-inputs":
            installed = self._input_objects.get(path)
            if installed is not None:
                return installed[0]
            bundle = self._bundles.get(path)
            if bundle is not None:
                bundle_path = _bundle_path(self._root, path)
                content = bundle_path.read_bytes()
                if (
                    len(content) != bundle.byte_count
                    or sha256(content).hexdigest() != bundle.content_sha256
                ):
                    raise PluginGuestError(
                        "Guest binary bundle failed content validation"
                    )
                return content
        if bucket == "guest-outputs" and path in self._output_objects:
            return self._output_objects[path][0]
        raise PluginGuestError("Guest storage path is not an authorized bundle")

    @override
    async def save(self, command: SaveFileCommand) -> StoredFile:
        if command.bucket != "guest-outputs":
            raise PluginGuestError("Guest storage writes require guest-outputs")
        path = PurePosixPath(command.path)
        if (
            command.path == ""
            or path.is_absolute()
            or command.path != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise PluginGuestError("Guest output storage path is unsafe")
        existing = self._output_objects.get(command.path)
        if existing is not None and not command.allow_overwrite:
            raise PluginGuestError("Guest output storage object already exists")
        existing_bytes = 0 if existing is None else len(existing[0])
        total_before = sum(
            len(content) for content, _type in self._output_objects.values()
        )
        remaining = self._max_output_bytes - total_before + existing_bytes
        content = command.stream.read(remaining + 1)
        if len(content) > remaining:
            raise PluginGuestError("Guest output storage exceeds its byte limit")
        if existing is None and len(self._output_objects) >= self._max_files:
            raise PluginGuestError("Guest output storage exceeds its file limit")
        digest = sha256(content).hexdigest()
        self._output_objects[command.path] = (content, command.content_type)
        return StoredFile(
            bucket=command.bucket,
            path=command.path,
            etag=None,
            version_id=None,
            byte_size=len(content),
            sha256=digest,
        )

    @override
    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        if bucket != "guest-outputs":
            raise PluginGuestError("Guest storage move requires guest-outputs")
        destination = PurePosixPath(destination_path)
        if (
            destination_path == ""
            or destination.is_absolute()
            or destination_path != destination.as_posix()
            or any(part in {"", ".", ".."} for part in destination.parts)
        ):
            raise PluginGuestError("Guest output storage destination is unsafe")
        if destination_path in self._output_objects:
            raise PluginGuestError("Guest output storage destination exists")
        try:
            self._output_objects[destination_path] = self._output_objects.pop(
                source_path
            )
        except KeyError as exc:
            raise PluginGuestError(
                "Guest output storage source is unavailable"
            ) from exc

    @override
    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        return cast(FileStreamProtocol, BytesIO(self._content(bucket, path)))

    @override
    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        if bucket == "guest-inputs" and path in self._input_objects:
            return StoredObjectInfo(
                bucket=bucket,
                path=path,
                byte_size=len(self._input_objects[path][0]),
                etag=None,
                version_id=None,
            )
        if bucket == "guest-outputs" and path in self._output_objects:
            return StoredObjectInfo(
                bucket=bucket,
                path=path,
                byte_size=len(self._output_objects[path][0]),
                etag=None,
                version_id=None,
            )
        bundle = self._bundles.get(path)
        if bucket != "guest-inputs" or bundle is None:
            return None
        return StoredObjectInfo(
            bucket=bucket,
            path=path,
            byte_size=bundle.byte_count,
            etag=None,
            version_id=None,
        )

    @override
    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        return self._content(bucket, path)[start:end_exclusive]

    @override
    async def delete(self, bucket: str, path: str) -> None:
        if bucket != "guest-outputs":
            raise PluginGuestError("Guest storage delete requires guest-outputs")
        self._output_objects.pop(path, None)


@final
class _GuestNodeSecretResolver:
    """Read only exact host-staged credentials declared by the invocation."""

    def __init__(
        self,
        invocation_root: Path,
        request: PluginInvocationEnvelope,
    ) -> None:
        self._root = invocation_root
        self._request = request
        self._bindings = {binding.name: binding for binding in request.secrets}
        expected = {binding.relative_path for binding in request.secrets}
        actual: set[str] = set()
        total_bytes = 0
        secrets_dir = invocation_root / "secrets"
        for path in secrets_dir.rglob("*"):
            if path.is_symlink():
                raise PluginGuestError("Plugin secret staging must not use symlinks")
            if path.is_file():
                actual.add(path.relative_to(invocation_root).as_posix())
                total_bytes += path.stat().st_size
        if actual != expected:
            raise PluginGuestError(
                "Plugin secret directory must contain exactly declared files"
            )
        if total_bytes > request.limits.max_secret_bytes:
            raise PluginGuestError("Plugin staged secrets exceed their byte limit")

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        request = self._request
        if (
            workspace_id != request.workspace_id
            or graph_id != request.secret_graph_id
            or graph_revision != request.secret_graph_revision
            or node_id != request.node_id
        ):
            raise NodeSecretUnavailableError(
                "Guest secret request does not match its invocation identity"
            )
        binding = self._bindings.get(name)
        if binding is None:
            raise NodeSecretUnavailableError(
                f"Guest secret {name!r} was not declared for this invocation"
            )
        if set(dependencies) != set(binding.config_dependencies):
            raise NodeSecretUnavailableError(
                f"Guest secret {name!r} dependencies do not match its declaration"
            )
        if node_secret_dependency_sha256(dependencies) != binding.dependency_digest:
            raise NodeSecretUnavailableError(
                f"Guest secret {name!r} dependency values do not match"
            )
        path = _bundle_path(self._root, binding.relative_path)
        if path.is_symlink() or not path.is_file():
            raise NodeSecretUnavailableError(f"Guest secret {name!r} is unavailable")
        try:
            value = path.read_bytes().decode("utf-8")
        except UnicodeError as exc:
            raise NodeSecretUnavailableError(
                f"Guest secret {name!r} is not valid UTF-8"
            ) from exc
        if value == "":
            raise NodeSecretUnavailableError(f"Guest secret {name!r} is empty")
        return SecretStr(value)

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        await self.resolve_secret(
            workspace_id=workspace_id,
            graph_id=graph_id,
            graph_revision=graph_revision,
            node_id=node_id,
            name=name,
            dependencies=dependencies,
        )
        return self._bindings[name].dependency_digest


@final
class _GuestInlineResolver(Resolver[object]):
    def __init__(
        self,
        *,
        source: ArtifactTypeKey,
        target: type[object],
        unit_of_work: UnitOfWorkPort,
    ) -> None:
        self.source = source
        self.target = target
        self._unit_of_work = unit_of_work

    @override
    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> object:
        async with self._unit_of_work as unit_of_work:
            artifact = await unit_of_work.artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None or artifact.ref() != ref:
            raise PluginGuestError(
                f"Staged input artifact {ref.artifact_id} is unavailable"
            )
        payload = artifact.inline_payload
        if payload is None:
            raise PluginGuestError(
                f"Staged input artifact {ref.artifact_id} is not inline JSON"
            )
        if issubclass(self.target, BaseModel):
            return self.target.model_validate(payload)
        if set(payload) != {"value"}:
            raise PluginGuestError(
                f"Inline scalar {ref.artifact_type}@{ref.schema_version} must "
                "contain exactly one 'value' field"
            )
        return TypeAdapter(self.target).validate_python(payload["value"], strict=True)


@final
class _GuestInlineOutputWriter(ArtifactOutputWriter):
    def __init__(
        self,
        *,
        artifact_type: ArtifactTypeKey,
        unit_of_work: UnitOfWorkPort,
    ) -> None:
        self.artifact_type = artifact_type
        self._unit_of_work = unit_of_work

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        if isinstance(value, BaseModel):
            payload = cast(JsonObject, value.model_dump(mode="json", by_alias=True))
        elif isinstance(value, dict):
            raw_payload = cast(dict[object, object], value)
            if any(not isinstance(key, str) for key in raw_payload):
                raise PluginGuestError("Inline JSON output keys must be strings")
            payload = cast(JsonObject, dict(raw_payload))
        else:
            payload = {"value": value}
        payload_bytes = _canonical_payload_bytes(payload)
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type="application/json",
            storage_backend="inline",
            inline_payload=payload,
            byte_size=len(payload_bytes),
            sha256=sha256(payload_bytes).hexdigest(),
            metadata={"producer_node_id": context.node_context.node_id},
        )
        async with self._unit_of_work as unit_of_work:
            await unit_of_work.artifacts.add(artifact)
            await unit_of_work.commit()
        return artifact.ref()


def _canonical_payload_bytes(payload: JsonObject) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _bundle_path(invocation_root: Path, relative_path: str) -> Path:
    root = invocation_root.resolve()
    path = invocation_root.joinpath(*relative_path.split("/"))
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise PluginGuestError("Plugin bundle path escapes the invocation root")
    return path


def _read_bundle(
    invocation_root: Path,
    relative_path: str,
    expected_bytes: int,
    expected_sha256: str,
) -> JsonObject:
    path = _bundle_path(invocation_root, relative_path)
    if path.is_symlink() or not path.is_file():
        raise PluginGuestError(
            f"Plugin bundle {relative_path!r} must be a regular file"
        )
    content = path.read_bytes()
    if len(content) != expected_bytes:
        raise PluginGuestError(
            f"Plugin bundle {relative_path!r} byte count does not match its manifest"
        )
    if sha256(content).hexdigest() != expected_sha256:
        raise PluginGuestError(
            f"Plugin bundle {relative_path!r} digest does not match its manifest"
        )
    value = json.loads(content)
    if not isinstance(value, dict):
        raise PluginGuestError(
            f"Plugin bundle {relative_path!r} must contain one JSON object"
        )
    raw_payload = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw_payload):
        raise PluginGuestError(
            f"Plugin bundle {relative_path!r} must contain one JSON object"
        )
    payload = cast(JsonObject, dict(raw_payload))
    if _canonical_payload_bytes(payload) != content:
        raise PluginGuestError(
            f"Plugin bundle {relative_path!r} is not canonical inline JSON"
        )
    return payload


def _declared_input_files(request: PluginInvocationEnvelope) -> set[str]:
    paths = {
        artifact.relative_path
        for binding in request.inputs
        for group in binding.groups
        for artifact in group.artifacts
    }
    paths.update(
        dependency.artifact.relative_path
        for dependency in request.input_artifact_dependencies
    )
    return paths


def _require_exact_input_files(
    invocation_root: Path,
    request: PluginInvocationEnvelope,
) -> None:
    inputs_dir = invocation_root / "inputs"
    actual: set[str] = set()
    for path in inputs_dir.rglob("*"):
        if path.is_symlink():
            raise PluginGuestError("Plugin input bundles must not contain symlinks")
        if path.is_file():
            actual.add(path.relative_to(invocation_root).as_posix())
    if actual != _declared_input_files(request):
        raise PluginGuestError(
            "Plugin input directory must contain exactly the declared bundle files"
        )


async def _stage_input_artifacts(
    invocation_root: Path,
    request: PluginInvocationEnvelope,
    unit_of_work: InMemoryUnitOfWork,
    storage: _GuestBundleStorage,
    input_contract: InputContract[Any],
) -> dict[str, object]:
    _require_exact_input_files(invocation_root, request)
    artifacts_by_id: dict[UUID, ArtifactObject] = {}
    inputs: dict[str, object] = {}
    total_bytes = 0
    total_files = 0
    staged_bindings = list(request.inputs)
    staged_bindings.extend(
        PluginInputBinding(
            port=f"dependency-{index}",
            artifact_type=dependency.artifact_type,
            bundle=dependency.bundle,
            groups=(
                PluginInputArtifactGroup(
                    shape="one",
                    artifacts=(dependency.artifact,),
                ),
            ),
        )
        for index, dependency in enumerate(request.input_artifact_dependencies)
    )
    for binding_index, binding in enumerate(staged_bindings):
        groups: list[ArtifactRef | ArtifactRefSequence] = []
        key = ArtifactTypeKey(
            binding.artifact_type.id,
            binding.artifact_type.schema_version,
        )
        for group in binding.groups:
            refs: list[ArtifactRef] = []
            for bundle in group.artifacts:
                total_bytes += bundle.byte_count
                if total_bytes > request.limits.max_input_bytes:
                    raise PluginGuestError("Plugin input byte limit exceeded")
                if binding.bundle.format == "table-bundle":
                    path = _bundle_path(invocation_root, bundle.relative_path)
                    if path.is_symlink() or not path.is_file():
                        raise PluginGuestError(
                            f"Plugin Table bundle {bundle.relative_path!r} must be "
                            "a regular file"
                        )
                    identity = file_identity(path)
                    if (
                        identity.byte_size != bundle.byte_count
                        or identity.sha256 != bundle.content_sha256
                    ):
                        raise PluginGuestError(
                            f"Plugin Table bundle {bundle.relative_path!r} failed "
                            "size or digest validation"
                        )
                    try:
                        manifest, table = load_table_bundle_with_manifest(
                            path,
                            max_bytes=request.limits.max_input_bytes,
                            max_files=request.limits.max_files,
                            max_rows=request.limits.max_table_rows,
                            max_columns=request.limits.max_table_columns,
                            max_chunks=request.limits.max_table_chunks,
                        )
                    except TableBundleError as exc:
                        raise PluginGuestError(
                            f"Plugin Table bundle {bundle.relative_path!r} is invalid"
                        ) from exc
                    payload = cast(
                        JsonObject,
                        table.model_dump(mode="json", by_alias=True),
                    )
                    artifact_byte_size = manifest.logical_byte_size
                    artifact_sha256 = manifest.logical_sha256
                    total_files += 1 + len(manifest.chunks)
                    artifact = ArtifactObject(
                        workspace_id=request.workspace_id,
                        id=bundle.artifact_id,
                        artifact_type=key.id,
                        schema_version=key.schema_version,
                        content_type=bundle.content_type,
                        storage_backend="inline",
                        inline_payload=payload,
                        byte_size=artifact_byte_size,
                        sha256=artifact_sha256,
                    )
                elif binding.bundle.format == "binary-file":
                    path = _bundle_path(invocation_root, bundle.relative_path)
                    if path.is_symlink() or not path.is_file():
                        raise PluginGuestError(
                            f"Plugin binary bundle {bundle.relative_path!r} must "
                            "be a regular file"
                        )
                    identity = file_identity(path)
                    if (
                        identity.byte_size != bundle.byte_count
                        or identity.sha256 != bundle.content_sha256
                    ):
                        raise PluginGuestError(
                            f"Plugin binary bundle {bundle.relative_path!r} failed "
                            "size or digest validation"
                        )
                    total_files += 1
                    artifact = ArtifactObject(
                        workspace_id=request.workspace_id,
                        id=bundle.artifact_id,
                        artifact_type=key.id,
                        schema_version=key.schema_version,
                        content_type=bundle.content_type,
                        storage_backend="guest-bundle",
                        bucket="guest-inputs",
                        object_key=bundle.relative_path,
                        byte_size=bundle.byte_count,
                        sha256=bundle.content_sha256,
                        metadata=bundle.metadata,
                    )
                elif binding.bundle.format == "object-set":
                    path = _bundle_path(invocation_root, bundle.relative_path)
                    try:
                        manifest, contents = load_object_set_bundle(
                            path,
                            max_bytes=request.limits.max_input_bytes,
                            max_files=request.limits.max_files,
                        )
                    except ObjectSetBundleError as exc:
                        raise PluginGuestError(
                            f"Plugin object-set bundle {bundle.relative_path!r} "
                            "is invalid"
                        ) from exc
                    identity = file_identity(path)
                    if (
                        identity.byte_size != bundle.byte_count
                        or identity.sha256 != bundle.content_sha256
                    ):
                        raise PluginGuestError(
                            f"Plugin object-set bundle {bundle.relative_path!r} "
                            "failed size or digest validation"
                        )
                    guest_paths = {
                        relative_path: (
                            f"object-sets/{bundle.artifact_id}/{relative_path}"
                        )
                        for relative_path in contents
                    }
                    storage.install_input_objects(
                        {
                            guest_paths[descriptor.relative_path]: (
                                contents[descriptor.relative_path],
                                descriptor.content_type,
                            )
                            for descriptor in manifest.files
                        }
                    )
                    metadata = manifest.restored_metadata(
                        bucket="guest-inputs",
                        paths=guest_paths,
                    )
                    primary_path = guest_paths[manifest.primary_path]
                    total_files += 1 + len(manifest.files)
                    artifact = ArtifactObject(
                        workspace_id=request.workspace_id,
                        id=bundle.artifact_id,
                        artifact_type=key.id,
                        schema_version=key.schema_version,
                        content_type=manifest.content_type,
                        storage_backend="guest-bundle",
                        bucket="guest-inputs",
                        object_key=primary_path,
                        byte_size=manifest.logical_byte_size,
                        sha256=manifest.logical_sha256,
                        metadata=metadata,
                    )
                elif binding.bundle.format == "inline-json":
                    payload = _read_bundle(
                        invocation_root,
                        bundle.relative_path,
                        bundle.byte_count,
                        bundle.content_sha256,
                    )
                    artifact_byte_size = bundle.byte_count
                    artifact_sha256 = bundle.content_sha256
                    total_files += 1
                    artifact = ArtifactObject(
                        workspace_id=request.workspace_id,
                        id=bundle.artifact_id,
                        artifact_type=key.id,
                        schema_version=key.schema_version,
                        content_type=bundle.content_type,
                        storage_backend="inline",
                        inline_payload=payload,
                        byte_size=artifact_byte_size,
                        sha256=artifact_sha256,
                    )
                else:
                    raise PluginGuestError(
                        f"Unsupported Plugin input bundle adapter "
                        f"{binding.bundle.format!r}@{binding.bundle.version}"
                    )
                if total_files > request.limits.max_files:
                    raise PluginGuestError("Plugin input file-count limit exceeded")
                existing = artifacts_by_id.get(artifact.id)
                if existing is not None and existing != artifact:
                    raise PluginGuestError(
                        f"Input artifact {artifact.id} has conflicting bundles"
                    )
                artifacts_by_id[artifact.id] = artifact
                refs.append(artifact.ref())
            if group.shape == "one":
                groups.append(refs[0])
            else:
                groups.append(ArtifactRefSequence.from_key(key=key, item_refs=refs))
        if binding_index >= len(request.inputs):
            continue
        spec = input_contract.ports[binding.port]
        if spec.instance_plugs or spec.variadic:
            inputs[binding.port] = groups
        else:
            inputs[binding.port] = groups[0]
    async with unit_of_work as entered:
        for artifact in artifacts_by_id.values():
            await entered.artifacts.add(artifact)
        await entered.commit()
    return inputs


def _build_node(
    plugin: Plugin,
    request: PluginInvocationEnvelope,
    context: PluginRuntimeContext,
) -> Node[Any, Any, Any]:
    for registration in plugin.nodes:
        if registration.key != (request.operator_id, request.operator_version):
            continue
        expected_secrets = tuple(
            (secret.name, secret.config_dependencies)
            for secret in registration.secret_inputs
        )
        requested_secrets = tuple(
            (secret.name, secret.config_dependencies) for secret in request.secrets
        )
        if requested_secrets != expected_secrets:
            raise PluginGuestError(
                "Invocation secret declarations do not match the installed Plugin"
            )
        if request.required_capabilities != registration.required_capabilities:
            raise PluginGuestError(
                "Invocation capability profile does not match the installed Plugin"
            )
        expected_staged_upload_fields = tuple(
            declaration.config_field
            for declaration in registration.staged_upload_inputs
        )
        requested_staged_upload_fields = tuple(
            dict.fromkeys(binding.config_field for binding in request.staged_uploads)
        )
        if requested_staged_upload_fields != expected_staged_upload_fields:
            raise PluginGuestError(
                "Invocation staged-upload declarations do not match the installed "
                "Plugin"
            )
        if registration.factory is not None:
            return registration.factory(context)
        return registration.node_class()
    raise PluginGuestError(
        f"Installed Plugin does not declare {request.operator_id}@"
        f"{request.operator_version}"
    )


async def _stage_uploaded_files(
    root: Path,
    request: PluginInvocationEnvelope,
    unit_of_work: InMemoryUnitOfWork,
) -> None:
    total_bytes = 0
    for binding in request.staged_uploads:
        path = _bundle_path(root, binding.relative_path)
        if path.is_symlink() or not path.is_file():
            raise PluginGuestError(
                f"Staged upload {binding.upload_key!r} is not a regular file"
            )
        identity = file_identity(path)
        if (
            identity.byte_size != binding.byte_count
            or identity.sha256 != binding.content_sha256
        ):
            raise PluginGuestError(
                f"Staged upload {binding.upload_key!r} failed identity validation"
            )
        total_bytes += identity.byte_size
        if total_bytes > request.limits.max_input_bytes:
            raise PluginGuestError("Staged uploads exceed the input byte limit")
    async with unit_of_work as entered:
        for binding in request.staged_uploads:
            await entered.staged_uploads.add(
                StagedUpload(
                    workspace_id=request.workspace_id,
                    upload_key=binding.upload_key,
                    original_filename=binding.original_filename,
                    byte_size=binding.byte_count,
                )
            )
        await entered.commit()


def _artifact_type_bindings(
    request: PluginInvocationEnvelope,
) -> dict[str, ArtifactTypeKey]:
    return {
        binding.variable: ArtifactTypeKey(
            binding.artifact_type.id,
            binding.artifact_type.schema_version,
        )
        for binding in request.artifact_type_bindings
    }


def _validate_request_contract(
    request: PluginInvocationEnvelope,
    catalog: PluginCatalogManifest,
    node: Node[Any, Any, Any],
) -> tuple[InputContract[Any], OutputContract[Any]]:
    artifact_contracts = {
        (contract.key.id, contract.key.schema_version): contract
        for contract in (
            *catalog.artifact_types,
            *catalog.artifact_type_dependencies,
        )
    }
    resolved = resolve_node_contracts(node, _artifact_type_bindings(request))
    input_specs = resolved.input_contract.ports
    provided_input_names = {binding.port for binding in request.inputs}
    missing = sorted(
        name
        for name, spec in input_specs.items()
        if spec.required and name not in provided_input_names
    )
    if missing:
        raise PluginGuestError(
            f"Invocation is missing required input ports: {', '.join(missing)}"
        )
    extra = sorted(provided_input_names - set(input_specs))
    if extra:
        raise PluginGuestError(
            f"Invocation declares unknown input ports: {', '.join(extra)}"
        )
    for binding in request.inputs:
        spec = input_specs[binding.port]
        if not isinstance(spec.accepts, ArtifactTypeKey):
            raise PluginGuestError(
                f"Input port {binding.port!r} kept an unresolved artifact type"
            )
        if (
            binding.artifact_type.id != spec.accepts.id
            or binding.artifact_type.schema_version != spec.accepts.schema_version
        ):
            raise PluginGuestError(
                f"Input port {binding.port!r} artifact type does not match the "
                "installed Plugin"
            )
        artifact_contract = artifact_contracts.get(
            (binding.artifact_type.id, binding.artifact_type.schema_version)
        )
        if artifact_contract is None or binding.bundle != artifact_contract.bundle:
            raise PluginGuestError(
                f"Input port {binding.port!r} bundle contract does not match the "
                "installed Plugin"
            )
        expected_shape = spec.shape.value
        if any(group.shape != expected_shape for group in binding.groups):
            raise PluginGuestError(
                f"Input port {binding.port!r} cardinality does not match the "
                "installed Plugin"
            )
        if not spec.instance_plugs and not spec.variadic and len(binding.groups) != 1:
            raise PluginGuestError(
                f"Input port {binding.port!r} does not accept multiple groups"
            )

    output_specs = resolved.output_contract.ports
    if set(output_specs) != {declaration.port for declaration in request.outputs}:
        raise PluginGuestError(
            "Invocation output declarations do not match the installed Plugin"
        )
    for declaration in request.outputs:
        spec = output_specs[declaration.port]
        if not isinstance(spec.produces, ArtifactTypeKey):
            raise PluginGuestError(
                f"Output port {declaration.port!r} kept an unresolved artifact type"
            )
        if (
            declaration.artifact_type.id != spec.produces.id
            or declaration.artifact_type.schema_version != spec.produces.schema_version
            or declaration.shape != spec.shape.value
            or declaration.required != spec.required
        ):
            raise PluginGuestError(
                f"Output port {declaration.port!r} contract does not match the "
                "installed Plugin"
            )
        artifact_contract = artifact_contracts.get(
            (declaration.artifact_type.id, declaration.artifact_type.schema_version)
        )
        if artifact_contract is None or declaration.bundle != artifact_contract.bundle:
            raise PluginGuestError(
                f"Output port {declaration.port!r} bundle contract does not match "
                "the installed Plugin"
            )
    return resolved.input_contract, resolved.output_contract


def _plugin_runtime(
    plugin: Plugin,
    request: PluginInvocationEnvelope,
    input_contract: InputContract[Any],
    output_contract: OutputContract[Any],
    context: PluginRuntimeContext,
    unit_of_work: InMemoryUnitOfWork,
) -> tuple[InputMaterializer, OutputPersister]:
    resolvers = [factory(context) for factory in plugin.resolver_factories]
    resolver_keys = {(resolver.source, resolver.target) for resolver in resolvers}
    for spec in input_contract.ports.values():
        if not isinstance(spec.accepts, ArtifactTypeKey) or spec.target_type is None:
            continue
        key = (spec.accepts, spec.target_type)
        if key in resolver_keys:
            continue
        resolvers.append(
            _GuestInlineResolver(
                source=spec.accepts,
                target=spec.target_type,
                unit_of_work=unit_of_work,
            )
        )
        resolver_keys.add(key)

    inline_output_keys = {
        ArtifactTypeKey(
            declaration.artifact_type.id,
            declaration.artifact_type.schema_version,
        )
        for declaration in request.outputs
        if declaration.bundle.format in {"inline-json", "table-bundle"}
    }
    writers: list[ArtifactOutputWriter] = []
    for factory in plugin.writer_factories:
        writer = factory(context)
        if writer.artifact_type not in inline_output_keys:
            writers.append(writer)
    writer_keys = {writer.artifact_type for writer in writers}
    for spec in output_contract.ports.values():
        if not isinstance(spec.produces, ArtifactTypeKey):
            continue
        if spec.produces in writer_keys:
            continue
        writers.append(
            _GuestInlineOutputWriter(
                artifact_type=spec.produces,
                unit_of_work=unit_of_work,
            )
        )
        writer_keys.add(spec.produces)
    return (
        InputMaterializer(ResolverRegistry(resolvers)),
        OutputPersister(ArtifactWriterRegistry(writers)),
    )


async def _write_output_bundles(
    invocation_root: Path,
    request: PluginInvocationEnvelope,
    persisted: PersistedNodeOutput,
    unit_of_work: InMemoryUnitOfWork,
    storage: _GuestBundleStorage,
) -> tuple[PluginOutputBinding, ...]:
    output_dir = invocation_root / "outputs"
    if any(output_dir.iterdir()):
        raise PluginGuestError("Plugin output directory must be empty before execution")
    bindings: list[PluginOutputBinding] = []
    total_bytes = 0
    total_files = 0
    declared_output_objects: set[str] = set()
    for output_index, declaration in enumerate(request.outputs):
        value = persisted.values.get(declaration.port)
        if value is None:
            if declaration.required:
                raise PluginGuestError(
                    f"Plugin returned no value for output {declaration.port!r}"
                )
            continue
        refs = (
            value.item_refs
            if isinstance(value, ArtifactRefSequence)
            else [value]
            if isinstance(value, ArtifactRef)
            else []
        )
        if not refs:
            raise PluginGuestError(
                f"Plugin output {declaration.port!r} did not persist artifact refs"
            )
        bundles: list[PluginOutputArtifactBundle] = []
        for artifact_index, ref in enumerate(refs):
            async with unit_of_work as entered:
                artifact = await entered.artifacts.get(
                    request.workspace_id,
                    ref.artifact_id,
                )
            if artifact is None or artifact.ref() != ref:
                raise PluginGuestError(
                    f"Plugin output {declaration.port!r} returned an unknown artifact"
                )
            payload = artifact.inline_payload
            if declaration.bundle.format == "table-bundle":
                if payload is None:
                    raise PluginGuestError(
                        f"Plugin output {declaration.port!r} is not inline JSON"
                    )
                table = Table.model_validate(payload)
                if len(table.rows) > request.limits.max_table_rows:
                    raise PluginGuestError("Plugin Table output exceeds its row limit")
                if len(table.columns) > request.limits.max_table_columns:
                    raise PluginGuestError(
                        "Plugin Table output exceeds its column limit"
                    )
                relative_path = (
                    f"outputs/o{output_index:04d}/a{artifact_index:06d}.table.tar"
                )
                path = _bundle_path(invocation_root, relative_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                manifest = write_table_bundle(path, table)
                if len(manifest.chunks) > request.limits.max_table_chunks:
                    raise PluginGuestError(
                        "Plugin Table output exceeds its chunk limit"
                    )
                identity = file_identity(path)
                byte_count = identity.byte_size
                content_sha256 = identity.sha256
                file_count = 1 + len(manifest.chunks)
                bundle_metadata: JsonObject = {}
            elif declaration.bundle.format == "inline-json":
                if payload is None:
                    raise PluginGuestError(
                        f"Plugin output {declaration.port!r} is not inline JSON"
                    )
                content = _canonical_payload_bytes(payload)
                relative_path = (
                    f"outputs/o{output_index:04d}/a{artifact_index:06d}.json"
                )
                path = _bundle_path(invocation_root, relative_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                byte_count = len(content)
                content_sha256 = sha256(content).hexdigest()
                file_count = 1
                bundle_metadata = {}
            elif declaration.bundle.format == "binary-file":
                if (
                    artifact.bucket != "guest-outputs"
                    or artifact.object_key is None
                    or artifact.byte_size is None
                    or artifact.sha256 is None
                ):
                    raise PluginGuestError(
                        f"Plugin binary output {declaration.port!r} has no exact "
                        "guest object"
                    )
                content, stored_content_type = storage.output_content(
                    artifact.object_key
                )
                if (
                    len(content) != artifact.byte_size
                    or sha256(content).hexdigest() != artifact.sha256
                ):
                    raise PluginGuestError(
                        f"Plugin binary output {declaration.port!r} content identity "
                        "is stale"
                    )
                relative_path = f"outputs/o{output_index:04d}/a{artifact_index:06d}.bin"
                path = _bundle_path(invocation_root, relative_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                byte_count = len(content)
                content_sha256 = artifact.sha256
                file_count = 1
                bundle_metadata = artifact.metadata
                declared_output_objects.add(artifact.object_key)
                if stored_content_type != artifact.content_type:
                    raise PluginGuestError(
                        f"Plugin binary output {declaration.port!r} content type "
                        "does not match its stored object"
                    )
            elif declaration.bundle.format == "object-set":
                if (
                    artifact.bucket != "guest-outputs"
                    or artifact.object_key is None
                    or artifact.byte_size is None
                    or artifact.sha256 is None
                ):
                    raise PluginGuestError(
                        f"Plugin object-set output {declaration.port!r} has no exact "
                        "guest object"
                    )
                portable = portable_metadata(artifact.metadata)
                object_prefix = (
                    f"workspaces/{artifact.workspace_id}/{artifact.artifact_type}/"
                    f"v{artifact.schema_version}"
                )
                object_manifest = object_set_manifest(
                    content_type=artifact.content_type,
                    primary_object_key=artifact.object_key,
                    logical_byte_size=artifact.byte_size,
                    logical_sha256=artifact.sha256,
                    metadata=artifact.metadata,
                    portable=portable,
                    object_prefix=object_prefix,
                )
                contents: dict[str, bytes] = {}
                for source, descriptor in zip(
                    portable.files,
                    object_manifest.files,
                    strict=True,
                ):
                    content, content_type = storage.output_content(source.object_key)
                    if (
                        len(content) != source.byte_size
                        or sha256(content).hexdigest() != source.sha256
                        or content_type != source.content_type
                    ):
                        raise PluginGuestError(
                            f"Plugin object-set output {declaration.port!r} has a "
                            "stale file inventory"
                        )
                    contents[descriptor.relative_path] = content
                    declared_output_objects.add(source.object_key)
                relative_path = (
                    f"outputs/o{output_index:04d}/a{artifact_index:06d}.objects.tar"
                )
                path = _bundle_path(invocation_root, relative_path)
                write_object_set_bundle(path, object_manifest, contents)
                identity = file_identity(path)
                byte_count = identity.byte_size
                content_sha256 = identity.sha256
                file_count = 1 + len(object_manifest.files)
                bundle_metadata = {}
            else:
                raise PluginGuestError(
                    f"Unsupported Plugin output bundle adapter "
                    f"{declaration.bundle.format!r}@{declaration.bundle.version}"
                )
            total_bytes += byte_count
            total_files += file_count
            if total_bytes > request.limits.max_output_bytes:
                raise PluginGuestError("Plugin output byte limit exceeded")
            if total_files > request.limits.max_files:
                raise PluginGuestError("Plugin output file-count limit exceeded")
            bundles.append(
                PluginOutputArtifactBundle(
                    relative_path=relative_path,
                    byte_count=byte_count,
                    content_sha256=content_sha256,
                    content_type=artifact.content_type,
                    metadata=bundle_metadata,
                )
            )
        bindings.append(
            PluginOutputBinding(
                port=declaration.port,
                artifact_type=declaration.artifact_type,
                bundle=declaration.bundle,
                shape=declaration.shape,
                artifacts=tuple(bundles),
            )
        )
    if storage.output_paths != frozenset(declared_output_objects):
        raise PluginGuestError(
            "Plugin guest wrote output objects that no artifact declared"
        )
    return tuple(bindings)


def _failure(
    request: PluginInvocationEnvelope,
    code: PluginFailureCode,
    message: str,
    progress: tuple[PluginProgressEvent, ...] = (),
) -> PluginInvocationResultEnvelope:
    return PluginInvocationResultEnvelope(
        invocation_id=request.invocation_id,
        status="failed",
        failure=PluginFailureEnvelope(
            code=code,
            message=message,
            release_slug=request.release.slug,
            release_revision=request.release.revision,
            operator_id=request.operator_id,
            operator_version=request.operator_version,
            node_id=request.node_id,
            invocation_index=request.invocation_index,
        ),
        progress=progress,
    )


def _clear_output_directory(invocation_root: Path) -> None:
    output_dir = invocation_root / "outputs"
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()


async def execute_plugin_invocation(
    invocation_root: Path,
    *,
    system_loader_manifest_path: Path = SYSTEM_PLUGIN_LOADER_MANIFEST_PATH,
) -> None:
    root = invocation_root.resolve()
    request = PluginInvocationEnvelope.from_json_bytes(
        (root / "invocation.json").read_bytes()
    )
    result_path = root / "result.json"
    if result_path.exists():
        raise PluginGuestError("Plugin invocation result manifest already exists")
    if request.release.protocol_digest != plugin_protocol_digest():
        result = _failure(
            request,
            PluginFailureCode.CONTRACT_FAILURE,
            f"Release protocol is incompatible with {PLUGIN_INVOCATION_PROTOCOL}",
        )
        result_path.write_bytes(result.canonical_json_bytes())
        return

    try:
        plugin, catalog = load_guest_plugin(
            request.release,
            system_loader_manifest_path=system_loader_manifest_path,
        )
        unit_of_work = InMemoryUnitOfWork()
        await _stage_uploaded_files(root, request, unit_of_work)
        bundle_storage = _GuestBundleStorage(root, request)
        plugin_context = PluginRuntimeContext(
            workspace=root,
            uploads_dir=root / "uploads",
            storage=bundle_storage,
            uow=cast(PluginUnitOfWorkPort, unit_of_work),
            bucket="guest-outputs",
            storage_backend="guest-bundle",
            node_secrets=_GuestNodeSecretResolver(root, request),
        )
        node = _build_node(plugin, request, plugin_context)
        input_contract, output_contract = _validate_request_contract(
            request,
            catalog,
            node,
        )
    except Exception:
        result = _failure(
            request,
            PluginFailureCode.CONTRACT_FAILURE,
            f"Plugin contract validation failed for {request.operator_id}@"
            f"{request.operator_version}",
        )
        result_path.write_bytes(result.canonical_json_bytes())
        return

    try:
        inputs = await _stage_input_artifacts(
            root,
            request,
            unit_of_work,
            bundle_storage,
            input_contract,
        )
        materializer, persister = _plugin_runtime(
            plugin,
            request,
            input_contract,
            output_contract,
            plugin_context,
            unit_of_work,
        )
        materialized, provenance = await materializer.materialize(
            input_contract,
            inputs,
            request.workspace_id,
        )
    except MaterializationError as exc:
        result = _failure(
            request,
            PluginFailureCode.MATERIALIZATION_FAILURE,
            f"Input materialization failed for port {exc.port_name!r}",
        )
        result_path.write_bytes(result.canonical_json_bytes())
        return
    except Exception:
        result = _failure(
            request,
            PluginFailureCode.MATERIALIZATION_FAILURE,
            "Input artifact materialization failed",
        )
        result_path.write_bytes(result.canonical_json_bytes())
        return

    try:
        config = node.config_contract.model.model_validate(request.config)
    except Exception:
        result = _failure(
            request,
            PluginFailureCode.CONTRACT_FAILURE,
            f"Configuration validation failed for {request.operator_id}@"
            f"{request.operator_version}",
        )
        result_path.write_bytes(result.canonical_json_bytes())
        return

    progress_reporter = _GuestProgressReporter()
    node_context = NodeExecutionContext(
        workspace_id=request.workspace_id,
        workflow_run_id=request.workflow_run_id,
        secret_graph_id=request.secret_graph_id,
        secret_graph_revision=request.secret_graph_revision,
        node_id=request.node_id,
        invocation_index=request.invocation_index,
        progress_reporter=progress_reporter,
    )
    try:
        output = await node.run(node_context, config, materialized)
    except UserFacingNodeError as exc:
        result = _failure(
            request,
            PluginFailureCode.OPERATOR_FAILURE,
            str(exc),
            progress_reporter.events,
        )
        result_path.write_bytes(result.canonical_json_bytes())
        return
    except Exception:
        result = _failure(
            request,
            PluginFailureCode.OPERATOR_FAILURE,
            f"Operator {request.operator_id}@{request.operator_version} failed",
            progress_reporter.events,
        )
        result_path.write_bytes(result.canonical_json_bytes())
        return

    try:
        persisted = await persister.persist(
            output_contract,
            node_context,
            output,
            provenance,
        )
        if not isinstance(persisted, PersistedNodeOutput):
            raise PluginGuestError("Plugin operator produced no artifact output ports")
        bindings = await _write_output_bundles(
            root,
            request,
            persisted,
            unit_of_work,
            bundle_storage,
        )
        result = PluginInvocationResultEnvelope(
            invocation_id=request.invocation_id,
            status="succeeded",
            outputs=bindings,
            progress=progress_reporter.events,
        )
    except Exception:
        _clear_output_directory(root)
        result = _failure(
            request,
            PluginFailureCode.OUTPUT_VALIDATION,
            f"Output validation failed for {request.operator_id}@"
            f"{request.operator_version}",
            progress_reporter.events,
        )
    result_path.write_bytes(result.canonical_json_bytes())


def main() -> None:
    if len(sys.argv) not in (2, 3):
        raise SystemExit(
            "usage: python -m grafy_core.runtime.plugin_guest ROOT [LOADER_MANIFEST]"
        )
    loader_manifest_path = (
        SYSTEM_PLUGIN_LOADER_MANIFEST_PATH if len(sys.argv) == 2 else Path(sys.argv[2])
    )
    try:
        asyncio.run(
            execute_plugin_invocation(
                Path(sys.argv[1]),
                system_loader_manifest_path=loader_manifest_path,
            )
        )
    except Exception as exc:
        raise SystemExit(f"Plugin guest runtime failed: {type(exc).__name__}") from exc


if __name__ == "__main__":
    main()


__all__ = [
    "PluginGuestError",
    "execute_plugin_invocation",
    "load_guest_plugin",
]
