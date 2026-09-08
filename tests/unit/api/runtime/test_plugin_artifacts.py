import asyncio
from io import BytesIO
import json
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from collections.abc import Mapping
from typing import Annotated, Literal, override
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactBundleContract,
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeSpec,
    ArtifactTypeKey,
    InMemoryUnitOfWork,
    JsonObject,
    NoConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginPortContract,
    PluginRelease,
    PluginReleaseIdentity,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginExecutionPolicy,
    PluginSecretInputContract,
    PluginStagedUploadInputContract,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.node_secrets import JsonValue, node_secret_dependency_sha256
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    PortShape,
    UserFacingNodeError,
)
from grafy_core.plugins import Plugin, PluginUnitOfWorkPort
from grafy_core.prompt_contracts import (
    PROMPT_MESSAGE,
    PromptMessage,
    PromptMessageRole,
)
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableColumn,
    TableValueType,
)
from grafy_core.ports.storage import (
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.object_set_bundle import (
    PORTABLE_BUNDLE_METADATA_KEY,
    PortableArtifactBundleMetadata,
    PortableArtifactFile,
    PortableMetadataReference,
)
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.plugin_guest import execute_plugin_invocation
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginInvocationRequest,
)
from grafy_core.runtime.plugin_protocol import (
    PluginFailureCode,
    PluginFailureEnvelope,
    PluginInputBinding,
    PluginInvocationEnvelope,
    PluginInvocationLimits,
    PluginInvocationResultEnvelope,
    PluginOutputArtifactBundle,
    PluginOutputBinding,
    PluginProgressEvent,
)
from grafy_core.runtime.plugin_loader import PluginGuestLoaderManifest
from grafy_core.runtime.resolvers import InlineModelResolver
from grafy_core.runtime.table_bundle import (
    load_table_bundle,
    write_table_bundle,
)
from grafy_storage import LocalFileObjectStore
from grafy_workbench.table.persistence import TableArtifactResolver, TableArtifactWriter

from grafy_api.plugins.runtime.artifacts import (
    ArtifactBundlePluginInvoker,
    PluginGuestRunError,
    PluginGuestRunner,
    SubprocessPluginGuestRunner,
)


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000401")


REFERENCED_ARTIFACT_PLUGIN = Plugin(
    slug="test.referenced-artifact",
    title="Referenced artifact test Plugin",
)
REFERENCED_ARTIFACT_PLUGIN.register_artifact_type_dependency(PROMPT_MESSAGE)
REFERENCED_ARTIFACT_PLUGIN.register_artifact_type_dependency(RASTER_IMAGE)


class ReferencedArtifactInput(NodeInput):
    message: Annotated[PromptMessage, InPort(PROMPT_MESSAGE)]


class ReferencedArtifactOutput(NodeOutput):
    message: Annotated[PromptMessage, OutPort(PROMPT_MESSAGE)]


@REFERENCED_ARTIFACT_PLUGIN.node(
    operator_id="test.referenced-artifact.lookup",
    version=1,
    title="Look up referenced artifact",
    factory=lambda context: ReferencedArtifactNode(context.uow),
)
class ReferencedArtifactNode(
    Node[NoConfig, ReferencedArtifactInput, ReferencedArtifactOutput]
):
    def __init__(self, unit_of_work: PluginUnitOfWorkPort) -> None:
        self._unit_of_work = unit_of_work

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        inputs: ReferencedArtifactInput,
        /,
    ) -> ReferencedArtifactOutput:
        image_ref = inputs.message.image_refs[0]
        async with self._unit_of_work as entered:
            image = await entered.artifacts.get(WORKSPACE_ID, image_ref.artifact_id)
        if image is None:
            raise UserFacingNodeError(
                f"Prompt image artifact {image_ref.artifact_id} was not found"
            )
        return ReferencedArtifactOutput(message=inputs.message)


REFERENCED_ARTIFACT_PLUGIN.register_resolver(
    lambda context: InlineModelResolver(
        source=PROMPT_MESSAGE.key,
        target=PromptMessage,
        uow=context.uow,
    )
)
REFERENCED_ARTIFACT_PLUGIN.register_writer(
    lambda context: InlineModelOutputWriter(
        artifact_type=PROMPT_MESSAGE.key,
        model=PromptMessage,
        uow=context.uow,
    )
)


def _installed_workspace_release(release: PluginRelease) -> InstalledPluginRelease:
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=WORKSPACE_ID,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=WORKSPACE_ID,
            installed_by_platform_actor=None,
        ),
    )


OTHER_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000402")
SUMMARY = ArtifactTypeKey("notes.summary", 1)
TEXT = ArtifactTypeKey("scalar.text", 1)
TABLE = TABLE_DATA.key
RASTER = RASTER_IMAGE.key
GEO_FEATURE_COLLECTION = ArtifactTypeSpec(
    key=ArtifactTypeKey("geo.feature_collection", 1),
    title="GeoJSON feature collection",
    bundle=ArtifactBundleContract(format="object-set", version=1),
)
GEO_RASTER_SCAN = ArtifactTypeSpec(
    key=ArtifactTypeKey("geo.raster_scan", 1),
    title="Georeferenced raster scan",
    bundle=ArtifactBundleContract(format="object-set", version=1),
)


def _canonical(payload: JsonObject) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _port(
    name: str,
    direction: Literal["input", "output"],
    artifact_type: ArtifactTypeKey,
    shape: PortShape = PortShape.ONE,
) -> PluginPortContract:
    return PluginPortContract(
        name=name,
        direction=direction,
        artifact_type=PluginArtifactTypeKey.from_key(artifact_type),
        shape=shape,
        accepted_shapes=(shape,),
    )


def _release(
    *,
    two_outputs: bool = False,
    many_output: bool = False,
    two_inputs: bool = False,
    protocol_digest: str | None = None,
    with_secret: bool = False,
    with_upload: bool = False,
) -> InstalledPluginRelease:
    output_shape = PortShape.MANY if many_output else PortShape.ONE
    outputs = [_port("text", "output", TEXT, output_shape)]
    if two_outputs:
        outputs.append(_port("second", "output", TEXT))
    inputs = [_port("summary", "input", SUMMARY)]
    if two_inputs:
        inputs.append(_port("other_summary", "input", SUMMARY))
    catalog = PluginCatalogManifest(
        slug="notes",
        title="Notes",
        artifact_types=(
            PluginArtifactTypeContract(
                key=PluginArtifactTypeKey.from_key(SUMMARY),
                title="Summary",
                payload_schema={"type": "object"},
            ),
        ),
        artifact_type_dependencies=(PluginArtifactTypeContract.from_spec(TEXT_VALUE),),
        nodes=(
            PluginNodeContract(
                operator_id="notes.render",
                operator_version=1,
                title="Render",
                description="Render a summary",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=tuple(inputs),
                outputs=tuple(outputs),
                secret_inputs=(
                    PluginSecretInputContract(
                        name="api_key",
                        title="API key",
                        config_dependencies=("base_url",),
                    ),
                )
                if with_secret
                else (),
                staged_upload_inputs=(
                    PluginStagedUploadInputContract(config_field="uploads"),
                )
                if with_upload
                else (),
                required_capabilities=tuple(
                    capability
                    for capability, enabled in (
                        (PluginRuntimeCapability.NODE_SECRETS, with_secret),
                        (PluginRuntimeCapability.STAGED_UPLOADS, with_upload),
                    )
                    if enabled
                ),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest(
        capabilities=tuple(
            capability
            for capability, enabled in (
                (PluginRuntimeCapability.NODE_SECRETS, with_secret),
                (PluginRuntimeCapability.STAGED_UPLOADS, with_upload),
            )
            if enabled
        )
    )
    return _installed_workspace_release(
        PluginRelease(
            slug="notes",
            revision=4,
            catalog=catalog,
            contract_digest=plugin_contract_digest(catalog),
            capabilities=capabilities,
            capability_digest=capabilities.digest,
            protocol_digest=protocol_digest or plugin_protocol_digest(),
            profile_digest=plugin_profile_digest("python-uv"),
            source_object_key="plugin-releases/notes/source.tar.gz",
            source_digest="a" * 64,
            lock_digest="b" * 64,
            runtime_profile="python-uv",
            loader_target="grafy_plugin:PLUGIN",
            published_by_user_id=WORKSPACE_ID,
        )
    )


def _table_release() -> InstalledPluginRelease:
    catalog = PluginCatalogManifest(
        slug="tables",
        title="Tables",
        artifact_type_dependencies=(PluginArtifactTypeContract.from_spec(TABLE_DATA),),
        nodes=(
            PluginNodeContract(
                operator_id="tables.copy",
                operator_version=1,
                title="Copy Table",
                description="Copy one Table through the Plugin boundary",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(_port("source", "input", TABLE),),
                outputs=(_port("result", "output", TABLE),),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest()
    return _installed_workspace_release(
        PluginRelease(
            slug="tables",
            revision=1,
            catalog=catalog,
            contract_digest=plugin_contract_digest(catalog),
            capabilities=capabilities,
            capability_digest=capabilities.digest,
            protocol_digest=plugin_protocol_digest(),
            profile_digest=plugin_profile_digest("python-uv"),
            source_object_key="plugin-releases/tables/source.tar.gz",
            source_digest="c" * 64,
            lock_digest="d" * 64,
            runtime_profile="python-uv",
            loader_target="grafy_plugin:PLUGIN",
            published_by_user_id=WORKSPACE_ID,
        )
    )


def _binary_release() -> InstalledPluginRelease:
    catalog = PluginCatalogManifest(
        slug="binary",
        title="Binary",
        artifact_type_dependencies=(
            PluginArtifactTypeContract.from_spec(RASTER_IMAGE),
        ),
        nodes=(
            PluginNodeContract(
                operator_id="binary.copy",
                operator_version=1,
                title="Copy binary",
                description="Copy one binary artifact through the Plugin boundary",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(_port("source", "input", RASTER),),
                outputs=(_port("result", "output", RASTER),),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest()
    return _installed_workspace_release(
        PluginRelease(
            slug="binary",
            revision=1,
            catalog=catalog,
            contract_digest=plugin_contract_digest(catalog),
            capabilities=capabilities,
            capability_digest=capabilities.digest,
            protocol_digest=plugin_protocol_digest(),
            profile_digest=plugin_profile_digest("python-uv"),
            source_object_key="plugin-releases/binary/source.tar.gz",
            source_digest="e" * 64,
            lock_digest="f" * 64,
            runtime_profile="python-uv",
            loader_target="grafy_plugin:PLUGIN",
            published_by_user_id=WORKSPACE_ID,
        )
    )


def _referenced_artifact_release() -> InstalledPluginRelease:
    catalog = PluginCatalogManifest.from_plugin(REFERENCED_ARTIFACT_PLUGIN)
    capabilities = PluginCapabilityManifest()
    return _installed_workspace_release(
        PluginRelease(
            slug=REFERENCED_ARTIFACT_PLUGIN.slug,
            revision=1,
            catalog=catalog,
            contract_digest=plugin_contract_digest(catalog),
            capabilities=capabilities,
            capability_digest=capabilities.digest,
            protocol_digest=plugin_protocol_digest(),
            profile_digest=plugin_profile_digest("python-uv"),
            source_object_key="plugin-releases/referenced-artifact/source.tar.gz",
            source_digest="1" * 64,
            lock_digest="2" * 64,
            runtime_profile="python-uv",
            loader_target=(
                "tests.unit.api.runtime.test_plugin_artifacts:"
                "REFERENCED_ARTIFACT_PLUGIN"
            ),
            published_by_user_id=WORKSPACE_ID,
        )
    )


def _object_set_release(spec: ArtifactTypeSpec) -> InstalledPluginRelease:
    catalog = PluginCatalogManifest(
        slug="portable",
        title="Portable",
        artifact_type_dependencies=(PluginArtifactTypeContract.from_spec(spec),),
        nodes=(
            PluginNodeContract(
                operator_id="portable.copy",
                operator_version=1,
                title="Copy file set",
                description="Copy one portable file set",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(_port("source", "input", spec.key),),
                outputs=(_port("result", "output", spec.key),),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest()
    return _installed_workspace_release(
        PluginRelease(
            slug="portable",
            revision=1,
            catalog=catalog,
            contract_digest=plugin_contract_digest(catalog),
            capabilities=capabilities,
            capability_digest=capabilities.digest,
            protocol_digest=plugin_protocol_digest(),
            profile_digest=plugin_profile_digest("python-uv"),
            source_object_key="plugin-releases/portable/source.tar.gz",
            source_digest="6" * 64,
            lock_digest="7" * 64,
            runtime_profile="python-uv",
            loader_target="grafy_plugin:PLUGIN",
            published_by_user_id=WORKSPACE_ID,
        )
    )


async def _seed_inline_artifact(
    unit_of_work: InMemoryUnitOfWork,
    *,
    workspace_id: UUID = WORKSPACE_ID,
) -> ArtifactRef:
    payload: JsonObject = {
        "row_count": 2,
        "column_count": 1,
        "column_ids": ["name"],
    }
    content = _canonical(payload)
    artifact = ArtifactObject(
        workspace_id=workspace_id,
        artifact_type=SUMMARY.id,
        schema_version=SUMMARY.schema_version,
        content_type="application/json",
        storage_backend="inline",
        inline_payload=payload,
        byte_size=len(content),
        sha256=sha256(content).hexdigest(),
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


async def _seed_object_set_artifact(
    unit_of_work: InMemoryUnitOfWork,
    storage: LocalFileObjectStore,
    *,
    spec: ArtifactTypeSpec,
    files: Mapping[str, tuple[bytes, str]],
    primary_suffix: str,
    content_type: str,
    metadata: JsonObject,
    references: tuple[PortableMetadataReference, ...],
) -> ArtifactRef:
    root = f"workspaces/{WORKSPACE_ID}/{spec.key.id}/v{spec.key.schema_version}"
    portable_files: list[PortableArtifactFile] = []
    stored_primary: StoredFile | None = None
    for suffix, (content, file_content_type) in files.items():
        digest = sha256(content).hexdigest()
        stored = await storage.save(
            SaveFileCommand(
                bucket="artifacts",
                path=f"{root}/{suffix}",
                stream=BytesIO(content),
                content_type=file_content_type,
                metadata={"sha256": digest},
            )
        )
        portable_files.append(
            PortableArtifactFile(
                object_key=stored.path,
                byte_size=stored.byte_size,
                sha256=stored.sha256,
                content_type=file_content_type,
            )
        )
        if suffix == primary_suffix:
            stored_primary = stored
    assert stored_primary is not None
    logical_content = f"logical:{spec.key.id}:{primary_suffix}".encode()
    artifact_metadata = dict(metadata)
    artifact_metadata[PORTABLE_BUNDLE_METADATA_KEY] = PortableArtifactBundleMetadata(
        files=tuple(portable_files),
        references=references,
    ).as_metadata_value()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=spec.key.id,
        schema_version=spec.key.schema_version,
        content_type=content_type,
        storage_backend="local",
        bucket=stored_primary.bucket,
        object_key=stored_primary.path,
        byte_size=len(logical_content),
        sha256=sha256(logical_content).hexdigest(),
        metadata=artifact_metadata,
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


def _request(
    release: InstalledPluginRelease,
    ref: ArtifactRef,
    *,
    second_ref: ArtifactRef | None = None,
    config: JsonObject | None = None,
) -> PluginInvocationRequest:
    inputs: dict[str, object] = {"summary": ref}
    if second_ref is not None:
        inputs["other_summary"] = second_ref
    return PluginInvocationRequest(
        release=PluginReleaseIdentity.from_release(release),
        contract=release.catalog.nodes[0],
        artifact_type_bindings={},
        config=config or {},
        inputs=inputs,
        artifact_bundle_contracts={
            ArtifactTypeKey(contract.key.id, contract.key.schema_version): (
                contract.bundle
            )
            for contract in (
                *release.catalog.artifact_types,
                *release.catalog.artifact_type_dependencies,
            )
        },
        workspace_id=WORKSPACE_ID,
        node_id="render",
        secret_graph_id=UUID("00000000-0000-4000-8000-000000000403"),
        secret_graph_revision=2,
    )


RunnerMode = Literal[
    "valid",
    "bad_second_digest",
    "extra_file",
    "symlink",
    "wrong_type",
    "wrong_cardinality",
    "missing_required",
    "many_files",
    "mismatched_failure",
    "operator_failure",
]


class ManifestRunner(PluginGuestRunner):
    def __init__(
        self,
        mode: RunnerMode = "valid",
        *,
        payload_size: int = 0,
        progress: tuple[PluginProgressEvent, ...] = (),
    ) -> None:
        self.mode = mode
        self.payload_size = payload_size
        self.progress = progress
        self.calls = 0
        self.observed_inputs: tuple[PluginInputBinding, ...] = ()
        self.observed_limits: PluginInvocationLimits | None = None

    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        del request
        self.calls += 1
        self.observed_limits = limits
        protocol_request = PluginInvocationEnvelope.from_json_bytes(
            (invocation_root / "invocation.json").read_bytes()
        )
        self.observed_inputs = protocol_request.inputs
        if self.mode in {"mismatched_failure", "operator_failure"}:
            result = PluginInvocationResultEnvelope(
                invocation_id=protocol_request.invocation_id,
                status="failed",
                failure=PluginFailureEnvelope(
                    code=PluginFailureCode.OPERATOR_FAILURE,
                    message="Operator failed",
                    release_slug=(
                        "other"
                        if self.mode == "mismatched_failure"
                        else protocol_request.release.slug
                    ),
                    release_revision=protocol_request.release.revision,
                    operator_id=protocol_request.operator_id,
                    operator_version=protocol_request.operator_version,
                    node_id=protocol_request.node_id,
                    invocation_index=protocol_request.invocation_index,
                ),
                progress=self.progress,
            )
            (invocation_root / "result.json").write_bytes(result.canonical_json_bytes())
            return
        bindings: list[PluginOutputBinding] = []
        for output_index, declaration in enumerate(protocol_request.outputs):
            if self.mode == "missing_required" and output_index == 0:
                continue
            artifact_count = 2 if self.mode == "many_files" else 1
            bundles: list[PluginOutputArtifactBundle] = []
            for artifact_index in range(artifact_count):
                payload: JsonObject = {
                    "value": (
                        "x" * self.payload_size
                        if self.payload_size
                        else f"rendered-{artifact_index}"
                    )
                }
                content = _canonical(payload)
                relative_path = (
                    f"outputs/o{output_index:04d}/a{artifact_index:06d}.json"
                )
                path = invocation_root.joinpath(*relative_path.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                if self.mode == "symlink" and output_index == 0:
                    target = invocation_root / "symlink-target.json"
                    target.write_bytes(content)
                    path.symlink_to(target)
                else:
                    path.write_bytes(content)
                digest = sha256(content).hexdigest()
                if self.mode == "bad_second_digest" and output_index == 1:
                    digest = "0" * 64
                bundles.append(
                    PluginOutputArtifactBundle(
                        relative_path=relative_path,
                        byte_count=len(content),
                        content_sha256=digest,
                    )
                )
            artifact_type = declaration.artifact_type
            if self.mode == "wrong_type" and output_index == 0:
                artifact_type = PluginArtifactTypeKey(
                    id="scalar.integer",
                    schema_version=1,
                )
            shape = declaration.shape
            if self.mode == "wrong_cardinality" and output_index == 0:
                shape = "many"
            bindings.append(
                PluginOutputBinding(
                    port=declaration.port,
                    artifact_type=artifact_type,
                    shape=shape,
                    artifacts=tuple(bundles),
                )
            )
        if self.mode == "extra_file":
            (invocation_root / "outputs" / "undeclared.json").write_text("{}")
        result = PluginInvocationResultEnvelope(
            invocation_id=protocol_request.invocation_id,
            status="succeeded",
            outputs=tuple(bindings),
            progress=self.progress,
        )
        (invocation_root / "result.json").write_bytes(result.canonical_json_bytes())


@pytest.mark.asyncio
async def test_invocation_wall_time_override_is_scoped_to_exact_plugin_slug(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    runner = ManifestRunner()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path,
        wall_time_seconds_by_plugin_slug={"notes": 900},
    )

    await invoker.invoke(_request(_release(), input_ref))

    assert runner.observed_limits is not None
    assert runner.observed_limits.wall_time_seconds == 900


class ReferencedArtifactGuestRunner(PluginGuestRunner):
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        del limits, request
        loader_manifest = PluginGuestLoaderManifest(
            slug=REFERENCED_ARTIFACT_PLUGIN.slug,
            loader_target=(
                "tests.unit.api.runtime.test_plugin_artifacts:"
                "REFERENCED_ARTIFACT_PLUGIN"
            ),
        )
        manifest_path = invocation_root / "plugin-loader.json"
        manifest_path.write_bytes(loader_manifest.canonical_json_bytes())
        await execute_plugin_invocation(
            invocation_root,
            system_loader_manifest_path=manifest_path,
        )


class RecordingSecretResolver:
    def __init__(self, value: str) -> None:
        self._value = value
        self.dependencies: Mapping[str, JsonValue] | None = None

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
        assert workspace_id == WORKSPACE_ID
        assert graph_id == UUID("00000000-0000-4000-8000-000000000403")
        assert graph_revision == 2
        assert node_id == "render"
        assert name == "api_key"
        self.dependencies = dependencies
        return SecretStr(self._value)

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
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        raise AssertionError("Secret staging does not query cache revisions")


class SecretObservingRunner(ManifestRunner):
    def __init__(self, expected_secret: bytes) -> None:
        super().__init__()
        self._expected_secret = expected_secret
        self.observed_envelope: PluginInvocationEnvelope | None = None

    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        envelope_bytes = (invocation_root / "invocation.json").read_bytes()
        assert self._expected_secret not in envelope_bytes
        envelope = PluginInvocationEnvelope.from_json_bytes(envelope_bytes)
        binding = envelope.secrets[0]
        secret_path = invocation_root.joinpath(*binding.relative_path.split("/"))
        assert secret_path.read_bytes() == self._expected_secret
        assert secret_path.stat().st_mode & 0o777 == 0o400
        self.observed_envelope = envelope
        await super().run(invocation_root, limits, request)


class StagedUploadObservingRunner(ManifestRunner):
    def __init__(self, expected_content: bytes) -> None:
        super().__init__()
        self._expected_content = expected_content
        self.observed_envelope: PluginInvocationEnvelope | None = None

    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        envelope = PluginInvocationEnvelope.from_json_bytes(
            (invocation_root / "invocation.json").read_bytes()
        )
        binding = envelope.staged_uploads[0]
        path = invocation_root.joinpath(*binding.relative_path.split("/"))
        assert path.read_bytes() == self._expected_content
        assert path.stat().st_mode & 0o777 == 0o400
        assert binding.content_sha256 == sha256(self._expected_content).hexdigest()
        self.observed_envelope = envelope
        await super().run(invocation_root, limits, request)


class FailingGuestRunner(PluginGuestRunner):
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        del invocation_root, limits, request
        raise PluginGuestRunError(
            PluginFailureCode.TIMEOUT,
            "controlled timeout",
        )


class RecordingProgressReporter:
    def __init__(self) -> None:
        self.reports: list[
            tuple[NodeExecutionContext, str, int | None, int | None]
        ] = []

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        self.reports.append((context, message, current, total))


class FailingProgressReporter:
    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        del context, message, current, total
        raise RuntimeError("controlled progress reporter failure")


class BlockingGuestRunner(PluginGuestRunner):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        del invocation_root, limits, request
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class CapacityObservingRunner(PluginGuestRunner):
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.entered.set()
        try:
            await self.release.wait()
            await ManifestRunner().run(invocation_root, limits, request)
        finally:
            self.active -= 1


class TableCopyRunner(PluginGuestRunner):
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        del request
        protocol_request = PluginInvocationEnvelope.from_json_bytes(
            (invocation_root / "invocation.json").read_bytes()
        )
        input_bundle = protocol_request.inputs[0].groups[0].artifacts[0]
        input_path = invocation_root.joinpath(*input_bundle.relative_path.split("/"))
        table = load_table_bundle(
            input_path,
            max_bytes=limits.max_input_bytes,
            max_files=limits.max_files,
            max_rows=limits.max_table_rows,
            max_columns=limits.max_table_columns,
            max_chunks=limits.max_table_chunks,
        )
        table.rows.append({"name": "guest", "count": 999})
        relative_path = "outputs/o0000/a000000.table.tar"
        output_path = invocation_root.joinpath(*relative_path.split("/"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_table_bundle(output_path, table)
        content = output_path.read_bytes()
        result = PluginInvocationResultEnvelope(
            invocation_id=protocol_request.invocation_id,
            status="succeeded",
            outputs=(
                PluginOutputBinding(
                    port="result",
                    artifact_type=PluginArtifactTypeKey.from_key(TABLE),
                    bundle=protocol_request.outputs[0].bundle,
                    shape="one",
                    artifacts=(
                        PluginOutputArtifactBundle(
                            relative_path=relative_path,
                            byte_count=len(content),
                            content_sha256=sha256(content).hexdigest(),
                        ),
                    ),
                ),
            ),
        )
        (invocation_root / "result.json").write_bytes(result.canonical_json_bytes())


class BinaryCopyRunner(PluginGuestRunner):
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        del limits, request
        protocol_request = PluginInvocationEnvelope.from_json_bytes(
            (invocation_root / "invocation.json").read_bytes()
        )
        input_bundle = protocol_request.inputs[0].groups[0].artifacts[0]
        content = invocation_root.joinpath(
            *input_bundle.relative_path.split("/")
        ).read_bytes()
        relative_path = "outputs/o0000/a000000.bin"
        output_path = invocation_root.joinpath(*relative_path.split("/"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        declaration = protocol_request.outputs[0]
        result = PluginInvocationResultEnvelope(
            invocation_id=protocol_request.invocation_id,
            status="succeeded",
            outputs=(
                PluginOutputBinding(
                    port=declaration.port,
                    artifact_type=declaration.artifact_type,
                    bundle=declaration.bundle,
                    shape=declaration.shape,
                    artifacts=(
                        PluginOutputArtifactBundle(
                            relative_path=relative_path,
                            byte_count=len(content),
                            content_sha256=sha256(content).hexdigest(),
                            content_type=input_bundle.content_type,
                            metadata=input_bundle.metadata,
                        ),
                    ),
                ),
            ),
        )
        (invocation_root / "result.json").write_bytes(result.canonical_json_bytes())


class ObjectSetCopyRunner(PluginGuestRunner):
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        del limits, request
        protocol_request = PluginInvocationEnvelope.from_json_bytes(
            (invocation_root / "invocation.json").read_bytes()
        )
        input_bundle = protocol_request.inputs[0].groups[0].artifacts[0]
        content = invocation_root.joinpath(
            *input_bundle.relative_path.split("/")
        ).read_bytes()
        relative_path = "outputs/o0000/a000000.objects.tar"
        output_path = invocation_root.joinpath(*relative_path.split("/"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        declaration = protocol_request.outputs[0]
        result = PluginInvocationResultEnvelope(
            invocation_id=protocol_request.invocation_id,
            status="succeeded",
            outputs=(
                PluginOutputBinding(
                    port=declaration.port,
                    artifact_type=declaration.artifact_type,
                    bundle=declaration.bundle,
                    shape=declaration.shape,
                    artifacts=(
                        PluginOutputArtifactBundle(
                            relative_path=relative_path,
                            byte_count=len(content),
                            content_sha256=sha256(content).hexdigest(),
                            content_type="application/x-tar",
                        ),
                    ),
                ),
            ),
        )
        (invocation_root / "result.json").write_bytes(result.canonical_json_bytes())


@pytest.mark.asyncio
async def test_secret_is_staged_outside_ordinary_invocation_json(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    secret_value = "super-sensitive-token"
    secret_resolver = RecordingSecretResolver(secret_value)
    runner = SecretObservingRunner(secret_value.encode("utf-8"))
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path,
        node_secrets=secret_resolver,
    )
    base_url = "https://provider.example/v1"

    await invoker.invoke(
        _request(
            _release(with_secret=True),
            input_ref,
            config={"base_url": base_url},
        )
    )

    assert secret_resolver.dependencies == {"base_url": base_url}
    envelope = runner.observed_envelope
    assert envelope is not None
    assert envelope.secrets[0].name == "api_key"
    assert envelope.secrets[0].dependency_digest == node_secret_dependency_sha256(
        {"base_url": base_url}
    )
    assert secret_value not in envelope.model_dump_json()


@pytest.mark.asyncio
async def test_staged_upload_is_authorized_digest_bound_and_read_only(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    upload_key = "upload-01"
    filename = "source.csv"
    content = b"name\nAda\n"
    uploads_dir = tmp_path / "uploads"
    workspace_uploads = uploads_dir / str(WORKSPACE_ID)
    workspace_uploads.mkdir(parents=True)
    (workspace_uploads / upload_key).write_bytes(content)
    async with unit_of_work as entered:
        await entered.staged_uploads.add(
            StagedUpload(
                workspace_id=WORKSPACE_ID,
                upload_key=upload_key,
                original_filename=filename,
                byte_size=len(content),
            )
        )
        await entered.commit()
    runner = StagedUploadObservingRunner(content)
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path / "scratch",
        uploads_dir=uploads_dir,
    )

    await invoker.invoke(
        _request(
            _release(with_upload=True),
            input_ref,
            config={
                "uploads": [
                    {
                        "upload_key": upload_key,
                        "filename": filename,
                        "byte_size": len(content),
                    }
                ]
            },
        )
    )

    assert runner.observed_envelope is not None
    assert runner.observed_envelope.required_capabilities == (
        PluginRuntimeCapability.STAGED_UPLOADS,
    )


@pytest.mark.asyncio
async def test_plugin_invocation_capacity_is_process_wide_and_bounded(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    release = _release()
    runner = CapacityObservingRunner()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path / "scratch",
        max_concurrent_invocations=1,
    )
    request = _request(release, input_ref)

    first = asyncio.create_task(invoker.invoke(request))
    second = asyncio.create_task(invoker.invoke(request))
    await runner.entered.wait()
    await asyncio.sleep(0)

    assert runner.calls == 1
    assert runner.max_active == 1
    active_diagnostics = invoker.diagnostics()
    assert active_diagnostics.max_active_invocations == 1
    assert active_diagnostics.active_invocations == 1
    assert active_diagnostics.waiting_invocations == 1
    assert active_diagnostics.total_invocations == 2

    runner.release.set()
    await asyncio.gather(first, second)

    assert runner.calls == 2
    assert runner.max_active == 1
    terminal_diagnostics = invoker.diagnostics()
    assert terminal_diagnostics.active_invocations == 0
    assert terminal_diagnostics.waiting_invocations == 0
    assert terminal_diagnostics.completed_invocations == 2
    assert terminal_diagnostics.failed_invocations == 0


class FailingTableManifestStorage:
    def __init__(self, delegate: LocalFileObjectStore) -> None:
        self._delegate = delegate
        self.deleted: list[tuple[str, str]] = []

    async def save(self, command: SaveFileCommand) -> StoredFile:
        if "/manifests/" in command.path:
            raise OSError("controlled manifest save failure")
        return await self._delegate.save(command)

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        await self._delegate.move(bucket, source_path, destination_path)

    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        return await self._delegate.load(bucket, path)

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        return await self._delegate.stat(bucket, path)

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        return await self._delegate.load_range(bucket, path, start, end_exclusive)

    async def delete(self, bucket: str, path: str) -> None:
        self.deleted.append((bucket, path))
        await self._delegate.delete(bucket, path)


class FailingSecondOutputStorage:
    def __init__(self, delegate: LocalFileObjectStore) -> None:
        self._delegate = delegate
        self._save_count = 0
        self.deleted: list[tuple[str, str]] = []

    async def save(self, command: SaveFileCommand) -> StoredFile:
        self._save_count += 1
        if self._save_count == 2:
            raise OSError("controlled object-set save failure")
        return await self._delegate.save(command)

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        await self._delegate.move(bucket, source_path, destination_path)

    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        return await self._delegate.load(bucket, path)

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        return await self._delegate.stat(bucket, path)

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        return await self._delegate.load_range(bucket, path, start, end_exclusive)

    async def delete(self, bucket: str, path: str) -> None:
        self.deleted.append((bucket, path))
        await self._delegate.delete(bucket, path)


@pytest.mark.asyncio
async def test_table_input_and_output_cross_the_bundle_boundary(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    table = Table(
        columns=[
            TableColumn(
                id="name",
                title="Name",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="count",
                title="Count",
                value_type=TableValueType.INTEGER,
            ),
        ],
        rows=[{"name": f"row-{index}", "count": index} for index in range(101)],
    )
    input_ref = await TableArtifactWriter(
        storage=storage,
        uow=unit_of_work,
        bucket="artifacts",
        storage_backend="local",
    ).write(
        table,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="source",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    release = _table_release()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=TableCopyRunner(),
        scratch_root=tmp_path / "scratch",
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    request = PluginInvocationRequest(
        release=PluginReleaseIdentity.from_release(release),
        contract=release.catalog.nodes[0],
        artifact_type_bindings={},
        config={},
        inputs={"source": input_ref},
        artifact_bundle_contracts={
            TABLE: PluginArtifactTypeContract.from_spec(TABLE_DATA).bundle
        },
        workspace_id=WORKSPACE_ID,
        node_id="copy",
    )

    result = await invoker.invoke(request)

    output_ref = result.outputs["result"]
    assert isinstance(output_ref, ArtifactRef)
    resolved = await TableArtifactResolver(
        uow=unit_of_work,
        storage=storage,
    ).resolve(output_ref, WORKSPACE_ID)
    assert resolved.rows == [*table.rows, {"name": "guest", "count": 999}]
    async with unit_of_work as entered:
        output = await entered.artifacts.get(WORKSPACE_ID, output_ref.artifact_id)
    assert output is not None
    assert output.inline_payload is None
    assert output.metadata["row_count"] == 102
    assert output.metadata["chunk_count"] == 2
    assert output.metadata["plugin_release"] == {
        "scope": "workspace",
        "workspace_id": str(WORKSPACE_ID),
        "slug": "tables",
        "revision": 1,
        "source_digest": "c" * 64,
        "contract_digest": release.contract_digest,
        "protocol_digest": release.protocol_digest,
        "descriptor_digest": release.descriptor.digest,
    }
    assert list((tmp_path / "scratch").iterdir()) == []


@pytest.mark.asyncio
async def test_binary_input_and_output_use_exact_portable_file_contract(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    content = b"portable raster bytes"
    content_digest = sha256(content).hexdigest()
    stored = await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path=f"raster/{content_digest}.bin",
            stream=BytesIO(content),
            content_type="image/png",
            metadata={"sha256": content_digest},
        )
    )
    source = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=RASTER.id,
        schema_version=RASTER.schema_version,
        content_type="image/png",
        storage_backend="local",
        bucket=stored.bucket,
        object_key=stored.path,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        metadata={"filename": "source-map.png", "source_name": "Source map"},
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(source)
        await entered.commit()
    release = _binary_release()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=BinaryCopyRunner(),
        scratch_root=tmp_path / "scratch",
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    result = await invoker.invoke(
        PluginInvocationRequest(
            release=PluginReleaseIdentity.from_release(release),
            contract=release.catalog.nodes[0],
            artifact_type_bindings={},
            config={},
            inputs={"source": source.ref()},
            artifact_bundle_contracts={
                RASTER: PluginArtifactTypeContract.from_spec(RASTER_IMAGE).bundle
            },
            workspace_id=WORKSPACE_ID,
            node_id="copy",
        )
    )

    output_ref = result.outputs["result"]
    assert isinstance(output_ref, ArtifactRef)
    async with unit_of_work as entered:
        output = await entered.artifacts.get(WORKSPACE_ID, output_ref.artifact_id)
    assert output is not None
    assert output.inline_payload is None
    assert output.content_type == "image/png"
    assert output.sha256 == content_digest
    assert output.metadata["filename"] == "source-map.png"
    assert output.metadata["source_name"] == "Source map"
    assert output.bucket is not None and output.object_key is not None
    stream = await storage.load(output.bucket, output.object_key)
    try:
        assert stream.read() == content
    finally:
        stream.close()


@pytest.mark.asyncio
async def test_inline_input_references_are_available_inside_the_plugin_guest(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    image_content = b"referenced raster bytes"
    image_digest = sha256(image_content).hexdigest()
    stored_image = await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path=f"raster/{image_digest}.png",
            stream=BytesIO(image_content),
            content_type="image/png",
            metadata={"sha256": image_digest},
        )
    )
    image = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=RASTER.id,
        schema_version=RASTER.schema_version,
        content_type="image/png",
        storage_backend="local",
        bucket=stored_image.bucket,
        object_key=stored_image.path,
        byte_size=stored_image.byte_size,
        sha256=stored_image.sha256,
    )
    prompt = PromptMessage(
        role=PromptMessageRole.USER,
        text="Describe this image.",
        image_refs=[image.ref()],
    )
    prompt_payload = prompt.model_dump(mode="json")
    prompt_content = _canonical(prompt_payload)
    prompt_artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=PROMPT_MESSAGE.key.id,
        schema_version=PROMPT_MESSAGE.key.schema_version,
        content_type="application/json",
        storage_backend="inline",
        inline_payload=prompt_payload,
        byte_size=len(prompt_content),
        sha256=sha256(prompt_content).hexdigest(),
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(image)
        await entered.artifacts.add(prompt_artifact)
        await entered.commit()

    release = _referenced_artifact_release()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ReferencedArtifactGuestRunner(),
        scratch_root=tmp_path / "scratch",
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    result = await invoker.invoke(
        PluginInvocationRequest(
            release=PluginReleaseIdentity.from_release(release),
            contract=release.catalog.nodes[0],
            artifact_type_bindings={},
            config={},
            inputs={"message": prompt_artifact.ref()},
            artifact_bundle_contracts={
                ArtifactTypeKey(contract.key.id, contract.key.schema_version): (
                    contract.bundle
                )
                for contract in (
                    *release.catalog.artifact_types,
                    *release.catalog.artifact_type_dependencies,
                )
            },
            artifact_reference_contracts={
                ArtifactTypeKey(contract.key.id, contract.key.schema_version): (
                    contract.references
                )
                for contract in (
                    *release.catalog.artifact_types,
                    *release.catalog.artifact_type_dependencies,
                )
                if contract.references
            },
            workspace_id=WORKSPACE_ID,
            node_id="lookup",
        )
    )

    output_ref = result.outputs["message"]
    assert isinstance(output_ref, ArtifactRef)
    async with unit_of_work as entered:
        output = await entered.artifacts.get(WORKSPACE_ID, output_ref.artifact_id)
    assert output is not None
    assert output.inline_payload == prompt_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["features", "features_pmtiles", "raster_tiles"])
async def test_gis_object_sets_round_trip_exact_files_and_typed_metadata_references(
    tmp_path: Path,
    case: str,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    if case.startswith("features"):
        spec = GEO_FEATURE_COLLECTION
        primary_suffix = "manifests/features.json"
        content_type = "application/geo+json"
        files: dict[str, tuple[bytes, str]] = {
            primary_suffix: (b'{"collections":["features"]}', "application/json"),
            "chunks/features-0000.json": (
                b'[{"geometry":{"coordinates":[13.4,52.5],"type":"Point"}}]',
                "application/json",
            ),
        }
        metadata: JsonObject = {
            "source_name": "Survey features",
            "feature_count": 1,
        }
        references: tuple[PortableMetadataReference, ...] = ()
        if case == "features_pmtiles":
            projection_suffix = "projections/pmtiles/features.pmtiles"
            projection_content = b"exact pmtiles bytes"
            files[projection_suffix] = (
                projection_content,
                "application/vnd.pmtiles",
            )
            projection_key = (
                f"workspaces/{WORKSPACE_ID}/{spec.key.id}/"
                f"v{spec.key.schema_version}/{projection_suffix}"
            )
            metadata["vector_projection"] = {
                "bucket": "artifacts",
                "object_key": projection_key,
                "byte_size": len(projection_content),
                "sha256": sha256(projection_content).hexdigest(),
            }
            references = (
                PortableMetadataReference(
                    path=("vector_projection", "bucket"),
                    kind="bucket",
                ),
                PortableMetadataReference(
                    path=("vector_projection", "object_key"),
                    kind="object",
                ),
            )
    else:
        spec = GEO_RASTER_SCAN
        primary_suffix = "cog/raster.tif"
        content_type = "image/tiff; application=geotiff"
        files = {
            primary_suffix: (b"exact cloud optimized geotiff", "image/tiff"),
            "tiles/tilejson.json": (
                b'{"tiles":["{z}/{x}/{y}.png"]}',
                "application/json",
            ),
            "tiles/0/0/0.png": (b"exact raster tile", "image/png"),
        }
        tile_prefix = (
            f"workspaces/{WORKSPACE_ID}/{spec.key.id}/v{spec.key.schema_version}/tiles"
        )
        metadata = {
            "source_name": "Survey scan",
            "original_filename": "survey-scan.tif",
            "raster_projection": {
                "bucket": "artifacts",
                "prefix": tile_prefix,
            },
        }
        references = (
            PortableMetadataReference(
                path=("raster_projection", "bucket"),
                kind="bucket",
            ),
            PortableMetadataReference(
                path=("raster_projection", "prefix"),
                kind="prefix",
            ),
        )
    input_ref = await _seed_object_set_artifact(
        unit_of_work,
        storage,
        spec=spec,
        files=files,
        primary_suffix=primary_suffix,
        content_type=content_type,
        metadata=metadata,
        references=references,
    )
    release = _object_set_release(spec)
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ObjectSetCopyRunner(),
        scratch_root=tmp_path / "scratch",
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )

    result = await invoker.invoke(
        PluginInvocationRequest(
            release=PluginReleaseIdentity.from_release(release),
            contract=release.catalog.nodes[0],
            artifact_type_bindings={},
            config={},
            inputs={"source": input_ref},
            artifact_bundle_contracts={
                spec.key: release.catalog.artifact_type_dependencies[0].bundle
            },
            workspace_id=WORKSPACE_ID,
            node_id="copy",
        )
    )

    output_ref = result.outputs["result"]
    assert isinstance(output_ref, ArtifactRef)
    async with unit_of_work as entered:
        source = await entered.artifacts.get(WORKSPACE_ID, input_ref.artifact_id)
        output = await entered.artifacts.get(WORKSPACE_ID, output_ref.artifact_id)
    assert source is not None and output is not None
    assert output.content_type == source.content_type
    assert output.byte_size == source.byte_size
    assert output.sha256 == source.sha256
    assert output.metadata["source_name"] == source.metadata["source_name"]
    if case == "raster_tiles":
        assert output.metadata["original_filename"] == "survey-scan.tif"
    output_portable = PortableArtifactBundleMetadata.model_validate(
        output.metadata[PORTABLE_BUNDLE_METADATA_KEY]
    )
    assert len(output_portable.files) == len(files)
    assert output.bucket is not None and output.object_key is not None
    primary_stream = await storage.load(output.bucket, output.object_key)
    try:
        assert primary_stream.read() == files[primary_suffix][0]
    finally:
        primary_stream.close()
    for portable_file in output_portable.files:
        output_stream = await storage.load(output.bucket, portable_file.object_key)
        try:
            output_content = output_stream.read()
        finally:
            output_stream.close()
        assert len(output_content) == portable_file.byte_size
        assert sha256(output_content).hexdigest() == portable_file.sha256
    plugin_release = output.metadata["plugin_release"]
    assert isinstance(plugin_release, dict)
    assert plugin_release["descriptor_digest"] == release.descriptor.digest


@pytest.mark.asyncio
async def test_failed_object_set_import_removes_every_new_file_and_mints_no_ref(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    durable_storage = LocalFileObjectStore(tmp_path / "objects")
    spec = GEO_FEATURE_COLLECTION
    input_ref = await _seed_object_set_artifact(
        unit_of_work,
        durable_storage,
        spec=spec,
        files={
            "manifests/features.json": (
                b'{"collections":["features"]}',
                "application/json",
            ),
            "chunks/features-0000.json": (b"[]", "application/json"),
        },
        primary_suffix="manifests/features.json",
        content_type="application/geo+json",
        metadata={"source_name": "Cleanup fixture", "feature_count": 0},
        references=(),
    )
    release = _object_set_release(spec)
    failing_storage = FailingSecondOutputStorage(durable_storage)
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ObjectSetCopyRunner(),
        scratch_root=tmp_path / "scratch",
        storage=failing_storage,
        bucket="artifacts",
        storage_backend="local",
    )

    with pytest.raises(PluginInvocationError, match="committed atomically"):
        await invoker.invoke(
            PluginInvocationRequest(
                release=PluginReleaseIdentity.from_release(release),
                contract=release.catalog.nodes[0],
                artifact_type_bindings={},
                config={},
                inputs={"source": input_ref},
                artifact_bundle_contracts={
                    spec.key: release.catalog.artifact_type_dependencies[0].bundle
                },
                workspace_id=WORKSPACE_ID,
                node_id="copy",
            )
        )

    assert len(failing_storage.deleted) == 1
    for bucket, object_key in failing_storage.deleted:
        assert await durable_storage.stat(bucket, object_key) is None
    async with unit_of_work as entered:
        artifacts = await entered.artifacts.list_by_type(WORKSPACE_ID, spec.key)
    assert [artifact.id for artifact in artifacts] == [input_ref.artifact_id]


@pytest.mark.asyncio
async def test_table_from_another_workspace_fails_before_staging(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    foreign_ref = await TableArtifactWriter(
        storage=storage,
        uow=unit_of_work,
        bucket="artifacts",
        storage_backend="local",
    ).write(
        Table(
            columns=[
                TableColumn(
                    id="name",
                    title="Name",
                    value_type=TableValueType.TEXT,
                )
            ],
            rows=[{"name": "private"}],
        ),
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=OTHER_WORKSPACE_ID,
                node_id="foreign-source",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    runner = ManifestRunner()
    release = _table_release()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path / "scratch",
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )

    with pytest.raises(PluginInvocationError, match="inaccessible or missing"):
        await invoker.invoke(
            PluginInvocationRequest(
                release=PluginReleaseIdentity.from_release(release),
                contract=release.catalog.nodes[0],
                artifact_type_bindings={},
                config={},
                inputs={"source": foreign_ref},
                artifact_bundle_contracts={
                    TABLE: PluginArtifactTypeContract.from_spec(TABLE_DATA).bundle
                },
                workspace_id=WORKSPACE_ID,
                node_id="copy",
            )
        )

    assert runner.calls == 0


@pytest.mark.asyncio
async def test_failed_table_import_removes_new_objects_and_exposes_no_output(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    durable_storage = LocalFileObjectStore(tmp_path / "objects")
    table = Table(
        columns=[
            TableColumn(
                id="name",
                title="Name",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="count",
                title="Count",
                value_type=TableValueType.INTEGER,
            ),
        ],
        rows=[{"name": "host", "count": 1}],
    )
    input_ref = await TableArtifactWriter(
        storage=durable_storage,
        uow=unit_of_work,
        bucket="artifacts",
        storage_backend="local",
    ).write(
        table,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="source",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    failing_storage = FailingTableManifestStorage(durable_storage)
    release = _table_release()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=TableCopyRunner(),
        scratch_root=tmp_path / "scratch",
        storage=failing_storage,
        bucket="artifacts",
        storage_backend="local",
    )
    request = PluginInvocationRequest(
        release=PluginReleaseIdentity.from_release(release),
        contract=release.catalog.nodes[0],
        artifact_type_bindings={},
        config={},
        inputs={"source": input_ref},
        artifact_bundle_contracts={
            TABLE: PluginArtifactTypeContract.from_spec(TABLE_DATA).bundle
        },
        workspace_id=WORKSPACE_ID,
        node_id="copy",
    )

    with pytest.raises(PluginInvocationError, match="committed atomically"):
        await invoker.invoke(request)

    assert failing_storage.deleted
    for bucket, object_key in failing_storage.deleted:
        assert await durable_storage.stat(bucket, object_key) is None
    async with unit_of_work as entered:
        tables = await entered.artifacts.list_by_type(WORKSPACE_ID, TABLE)
    assert [artifact.id for artifact in tables] == [input_ref.artifact_id]
    assert (
        await TableArtifactResolver(
            uow=unit_of_work,
            storage=durable_storage,
        ).resolve(input_ref, WORKSPACE_ID)
        == table
    )


@pytest.mark.asyncio
async def test_host_authorizes_stages_and_atomically_mints_output_refs(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    release = _release()
    runner = ManifestRunner()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path,
    )

    result = await invoker.invoke(_request(release, input_ref))

    assert runner.calls == 1
    assert runner.observed_inputs[0].groups[0].artifacts[0].artifact_id == (
        input_ref.artifact_id
    )
    output_ref = result.outputs["text"]
    assert isinstance(output_ref, ArtifactRef)
    assert output_ref.artifact_id != input_ref.artifact_id
    async with unit_of_work as entered:
        output = await entered.artifacts.get(WORKSPACE_ID, output_ref.artifact_id)
        original = await entered.artifacts.get(WORKSPACE_ID, input_ref.artifact_id)
    assert output is not None
    assert output.inline_payload == {"value": "rendered-0"}
    assert output.object_key is None
    assert output.metadata["plugin_release"] == {
        "scope": "workspace",
        "workspace_id": str(WORKSPACE_ID),
        "slug": "notes",
        "revision": 4,
        "source_digest": "a" * 64,
        "contract_digest": release.contract_digest,
        "protocol_digest": release.protocol_digest,
        "descriptor_digest": release.descriptor.digest,
    }
    assert original is not None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_guest_progress_is_forwarded_to_the_original_context_in_order(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    reporter = RecordingProgressReporter()
    context = NodeExecutionContext(
        workspace_id=WORKSPACE_ID,
        node_id="render",
        invocation_index=3,
        progress_reporter=reporter,
    )
    events = (
        PluginProgressEvent(message="Starting"),
        PluginProgressEvent(message="Halfway", current=5, total=10),
        PluginProgressEvent(message="Complete", current=10, total=10),
    )
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ManifestRunner(progress=events),
        scratch_root=tmp_path,
    )

    await invoker.invoke(
        replace(
            _request(_release(), input_ref),
            invocation_index=3,
            progress_context=context,
        )
    )

    assert reporter.reports == [
        (context, "Starting", None, None),
        (context, "Halfway", 5, 10),
        (context, "Complete", 10, 10),
    ]


@pytest.mark.asyncio
async def test_progress_reporting_is_best_effort_and_guest_failure_is_unchanged(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    event = PluginProgressEvent(message="Working", current=1, total=2)
    success_invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ManifestRunner(progress=(event,)),
        scratch_root=tmp_path / "success",
    )
    failure_reporter = FailingProgressReporter()

    result = await success_invoker.invoke(
        replace(
            _request(_release(), input_ref),
            progress_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="render",
                progress_reporter=failure_reporter,
            ),
        )
    )

    assert "text" in result.outputs

    recording_reporter = RecordingProgressReporter()
    failure_context = NodeExecutionContext(
        workspace_id=WORKSPACE_ID,
        node_id="render",
        progress_reporter=recording_reporter,
    )
    failure_invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ManifestRunner("operator_failure", progress=(event,)),
        scratch_root=tmp_path / "failure",
    )

    with pytest.raises(PluginInvocationError, match="operator_failure"):
        await failure_invoker.invoke(
            replace(
                _request(_release(), input_ref),
                progress_context=failure_context,
            )
        )

    assert recording_reporter.reports == [(failure_context, "Working", 1, 2)]


@pytest.mark.asyncio
async def test_cancelling_plugin_invocation_still_cancels_the_guest(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    runner = BlockingGuestRunner()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path,
    )
    invocation = asyncio.create_task(invoker.invoke(_request(_release(), input_ref)))
    await runner.started.wait()

    invocation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await invocation
    await runner.cancelled.wait()
    assert invoker.diagnostics().failed_invocations == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_guest_failure_preserves_release_and_invocation_context(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    workflow_run_id = uuid4()
    request = replace(
        _request(_release(), input_ref),
        workflow_run_id=workflow_run_id,
        invocation_index=7,
    )
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=FailingGuestRunner(),
        scratch_root=tmp_path,
    )

    with pytest.raises(PluginInvocationError) as captured:
        await invoker.invoke(request)

    message = str(captured.value)
    assert "Plugin 'notes' revision 4 timeout" in message
    assert f"workflow {workflow_run_id}" in message
    assert "node 'render'" in message
    assert "MAP index 7" in message
    assert "controlled timeout" in message


@pytest.mark.asyncio
async def test_cross_workspace_and_stale_refs_fail_before_guest_execution(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    other_ref = await _seed_inline_artifact(
        unit_of_work,
        workspace_id=OTHER_WORKSPACE_ID,
    )
    runner = ManifestRunner()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path,
    )
    release = _release()

    with pytest.raises(PluginInvocationError, match="inaccessible or missing"):
        await invoker.invoke(_request(release, other_ref))

    own_ref = await _seed_inline_artifact(unit_of_work)
    stale = own_ref.model_copy(update={"content_hash": "f" * 64})
    with pytest.raises(PluginInvocationError, match="stale or type-mismatched"):
        await invoker.invoke(_request(release, stale))
    assert runner.calls == 0


@pytest.mark.asyncio
async def test_incompatible_release_protocol_fails_before_guest_execution(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    runner = ManifestRunner()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path,
    )

    with pytest.raises(PluginInvocationError, match="unsupported invocation protocol"):
        await invoker.invoke(_request(_release(protocol_digest="0" * 64), input_ref))

    assert runner.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["bytes", "files"])
async def test_input_limits_fail_before_guest_execution(
    tmp_path: Path,
    limit: str,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    second_ref = await _seed_inline_artifact(unit_of_work)
    runner = ManifestRunner()
    limits = (
        PluginInvocationLimits(max_input_bytes=1)
        if limit == "bytes"
        else PluginInvocationLimits(max_files=1)
    )
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        limits=limits,
        scratch_root=tmp_path,
    )

    with pytest.raises(
        PluginInvocationError,
        match=f"input {limit[:-1] if limit.endswith('s') else limit}",
    ):
        await invoker.invoke(
            _request(
                _release(two_inputs=True),
                input_ref,
                second_ref=second_ref,
            )
        )

    assert runner.calls == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("extra_file", "exactly the declared"),
        ("symlink", "must not contain symlinks"),
        ("wrong_type", "type or cardinality"),
        ("wrong_cardinality", "type or cardinality"),
        ("missing_required", "omitted required"),
    ],
)
async def test_untrusted_output_shape_and_files_fail_before_import(
    tmp_path: Path,
    mode: RunnerMode,
    message: str,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ManifestRunner(mode),
        scratch_root=tmp_path,
    )

    with pytest.raises(PluginInvocationError, match=message):
        await invoker.invoke(_request(_release(), input_ref))

    async with unit_of_work as entered:
        outputs = await entered.artifacts.list_by_type(WORKSPACE_ID, TEXT)
    assert outputs == []


@pytest.mark.asyncio
async def test_invalid_second_output_leaves_no_first_output_visible(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ManifestRunner("bad_second_digest"),
        scratch_root=tmp_path,
    )

    with pytest.raises(PluginInvocationError, match="digest validation"):
        await invoker.invoke(_request(_release(two_outputs=True), input_ref))

    async with unit_of_work as entered:
        outputs = await entered.artifacts.list_by_type(WORKSPACE_ID, TEXT)
    assert outputs == []


@pytest.mark.asyncio
async def test_guest_failure_context_must_match_request(tmp_path: Path) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ManifestRunner("mismatched_failure"),
        scratch_root=tmp_path,
    )

    with pytest.raises(PluginInvocationError, match="context does not match"):
        await invoker.invoke(_request(_release(), input_ref))


@pytest.mark.asyncio
async def test_output_byte_limit_fails_predictably_before_import(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ManifestRunner(payload_size=128),
        limits=PluginInvocationLimits(max_output_bytes=32),
        scratch_root=tmp_path,
    )

    with pytest.raises(PluginInvocationError, match="output byte limit"):
        await invoker.invoke(_request(_release(), input_ref))


@pytest.mark.asyncio
async def test_output_file_count_limit_fails_predictably_before_import(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_inline_artifact(unit_of_work)
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=ManifestRunner("many_files"),
        limits=PluginInvocationLimits(max_files=1),
        scratch_root=tmp_path,
    )

    with pytest.raises(PluginInvocationError, match="file-count limit"):
        await invoker.invoke(_request(_release(many_output=True), input_ref))


@pytest.mark.asyncio
async def test_subprocess_runner_bounds_logs_and_wall_time(tmp_path: Path) -> None:
    log_runner = SubprocessPluginGuestRunner(
        (sys.executable, "-c", "print('x' * 1000)"),
    )
    with pytest.raises(PluginGuestRunError, match="log exceeded") as log_error:
        await log_runner.run(
            tmp_path,
            PluginInvocationLimits(max_log_bytes=32),
        )
    assert log_error.value.code.value == "internal_adapter_failure"

    timeout_runner = SubprocessPluginGuestRunner(
        (sys.executable, "-c", "import time; time.sleep(5)"),
    )
    with pytest.raises(PluginGuestRunError, match="exceeded 1 seconds") as timeout:
        await timeout_runner.run(
            tmp_path,
            PluginInvocationLimits(wall_time_seconds=1),
        )
    assert timeout.value.code.value == "timeout"
