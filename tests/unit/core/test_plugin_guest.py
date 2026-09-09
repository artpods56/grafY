from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
from uuid import UUID

import pytest

from grafy_core.domain.plugin_releases import (
    PluginArtifactBundleContract,
    PluginArtifactTypeKey,
    PluginCatalogManifest,
    plugin_contract_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.artifacts import ArtifactObject, ArtifactRef, ArtifactTypeKey, NodeInput
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.nodes import InputContract, InputPortSpec
from grafy_core.ports.storage import SaveFileCommand
from grafy_core.runtime.plugin_guest import (
    PluginGuestError,
    _GuestBundleStorage,
    _stage_input_artifacts,
    _stage_uploaded_files,
    _write_output_bundles,
    load_guest_plugin,
)
from grafy_core.runtime.plugin_loader import PluginGuestLoaderManifest
from grafy_core.runtime.object_set_bundle import (
    PORTABLE_BUNDLE_METADATA_KEY,
    PortableArtifactBundleMetadata,
    PortableArtifactFile,
    PortableMetadataReference,
    load_object_set_bundle,
    object_set_manifest,
    write_object_set_bundle,
)
from grafy_core.runtime.persistence import PersistedNodeOutput
from grafy_core.runtime.plugin_protocol import (
    PluginInputArtifactBundle,
    PluginInputArtifactDependency,
    PluginInputArtifactGroup,
    PluginInputBinding,
    PluginInvocationEnvelope,
    PluginInvocationLimits,
    PluginInvocationRelease,
    PluginOutputDeclaration,
    PluginStagedUploadBinding,
)
from grafy_core.staged_upload_paths import resolve_persisted_staged_upload_path
from grafy_workbench.text import TEXT

import grafy_core.runtime.plugin_guest as plugin_guest_module


class _GuestObjectInput(NodeInput):
    source: ArtifactRef


def _loader_release(
    *,
    scope: PluginReleaseScope = PluginReleaseScope.SYSTEM,
    workspace_id: UUID | None = None,
    slug: str = "text",
    contract_digest: str | None = None,
) -> PluginInvocationRelease:
    return PluginInvocationRelease(
        scope=scope,
        workspace_id=workspace_id,
        slug=slug,
        revision=1,
        source_digest="a" * 64,
        contract_digest=contract_digest
        or plugin_contract_digest(PluginCatalogManifest.from_plugin(TEXT)),
        protocol_digest=plugin_protocol_digest(),
        descriptor_digest="d" * 64,
    )


def test_system_guest_loads_the_image_owned_family_target(tmp_path: Path) -> None:
    manifest_path = tmp_path / "plugin-loader.json"
    manifest_path.write_bytes(
        PluginGuestLoaderManifest(
            slug="text",
            loader_target="grafy_workbench.text.plugin:TEXT",
        ).canonical_json_bytes()
    )

    plugin, catalog = load_guest_plugin(
        _loader_release(),
        system_loader_manifest_path=manifest_path,
    )

    assert plugin is TEXT
    assert catalog == PluginCatalogManifest.from_plugin(TEXT)


def test_system_guest_rejects_manifest_and_contract_identity_drift(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "plugin-loader.json"
    manifest_path.write_bytes(
        PluginGuestLoaderManifest(
            slug="arithmetic",
            loader_target="grafy_workbench.text.plugin:TEXT",
        ).canonical_json_bytes()
    )

    with pytest.raises(PluginGuestError, match="manifest does not match"):
        load_guest_plugin(
            _loader_release(),
            system_loader_manifest_path=manifest_path,
        )

    manifest_path.write_bytes(
        PluginGuestLoaderManifest(
            slug="text",
            loader_target="grafy_workbench.text.plugin:TEXT",
        ).canonical_json_bytes()
    )
    with pytest.raises(PluginGuestError, match="contract does not match"):
        load_guest_plugin(
            _loader_release(contract_digest="f" * 64),
            system_loader_manifest_path=manifest_path,
        )


def test_workspace_guest_uses_the_same_image_owned_loader_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "plugin-loader.json"
    manifest_path.write_bytes(
        PluginGuestLoaderManifest(
            slug="text",
            loader_target="workspace_plugin:CUSTOM_PLUGIN",
        ).canonical_json_bytes()
    )
    module = ModuleType("workspace_plugin")
    module.CUSTOM_PLUGIN = TEXT  # type: ignore[attr-defined]
    importer = Mock(return_value=module)
    monkeypatch.setattr(plugin_guest_module, "import_module", importer)
    workspace_id = UUID("00000000-0000-4000-8000-000000000503")

    plugin, _ = load_guest_plugin(
        _loader_release(
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=workspace_id,
        ),
        system_loader_manifest_path=manifest_path,
    )

    assert plugin is TEXT
    importer.assert_called_once_with("workspace_plugin")


@pytest.mark.asyncio
async def test_guest_binary_bundle_storage_loads_only_declared_content(
    tmp_path: Path,
) -> None:
    content = b"exact portable binary payload"
    relative_path = "inputs/p0000/g0000/a000000.bin"
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    request = PluginInvocationEnvelope(
        invocation_id=UUID("00000000-0000-4000-8000-000000000501"),
        execution_scope_id=UUID("00000000-0000-4000-8000-000000000502"),
        workspace_id=UUID("00000000-0000-4000-8000-000000000503"),
        release=PluginInvocationRelease(
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=UUID("00000000-0000-4000-8000-000000000503"),
            slug="binary",
            revision=1,
            source_digest="a" * 64,
            contract_digest="b" * 64,
            protocol_digest=plugin_protocol_digest(),
            descriptor_digest="d" * 64,
        ),
        operator_id="binary.read",
        operator_version=1,
        config={},
        inputs=(
            PluginInputBinding(
                port="source",
                artifact_type=PluginArtifactTypeKey(
                    id="binary.payload",
                    schema_version=1,
                ),
                bundle=PluginArtifactBundleContract(
                    format="binary-file",
                    version=1,
                ),
                groups=(
                    PluginInputArtifactGroup(
                        shape="one",
                        artifacts=(
                            PluginInputArtifactBundle(
                                artifact_id=UUID(
                                    "00000000-0000-4000-8000-000000000504"
                                ),
                                relative_path=relative_path,
                                byte_count=len(content),
                                content_sha256=sha256(content).hexdigest(),
                                content_type="application/octet-stream",
                            ),
                        ),
                    ),
                ),
            ),
        ),
        outputs=(),
        limits=PluginInvocationLimits(),
    )
    storage = _GuestBundleStorage(tmp_path, request)

    stream = await storage.load("guest-inputs", relative_path)
    info = await storage.stat("guest-inputs", relative_path)

    assert stream.read() == content
    assert info is not None
    assert info.byte_size == len(content)
    assert await storage.load_range("guest-inputs", relative_path, 6, 14) == b"portable"


@pytest.mark.asyncio
async def test_guest_binary_dependency_bundle_storage_loads_declared_content(
    tmp_path: Path,
) -> None:
    content = b"referenced prompt image"
    relative_path = "inputs/references/r000000.bin"
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    workspace_id = UUID("00000000-0000-4000-8000-000000000503")
    request = PluginInvocationEnvelope(
        invocation_id=UUID("00000000-0000-4000-8000-000000000501"),
        execution_scope_id=UUID("00000000-0000-4000-8000-000000000502"),
        workspace_id=workspace_id,
        release=PluginInvocationRelease(
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=workspace_id,
            slug="binary",
            revision=1,
            source_digest="a" * 64,
            contract_digest="b" * 64,
            protocol_digest=plugin_protocol_digest(),
            descriptor_digest="d" * 64,
        ),
        operator_id="binary.read",
        operator_version=1,
        config={},
        inputs=(),
        input_artifact_dependencies=(
            PluginInputArtifactDependency(
                artifact_type=PluginArtifactTypeKey(
                    id="image.raster",
                    schema_version=1,
                ),
                bundle=PluginArtifactBundleContract(
                    format="binary-file",
                    version=1,
                ),
                artifact=PluginInputArtifactBundle(
                    artifact_id=UUID("00000000-0000-4000-8000-000000000504"),
                    relative_path=relative_path,
                    byte_count=len(content),
                    content_sha256=sha256(content).hexdigest(),
                    content_type="image/png",
                ),
            ),
        ),
        outputs=(),
        limits=PluginInvocationLimits(),
    )
    storage = _GuestBundleStorage(tmp_path, request)

    stream = await storage.load("guest-inputs", relative_path)

    assert stream.read() == content


@pytest.mark.asyncio
async def test_guest_bundle_storage_writes_bounded_invocation_local_outputs(
    tmp_path: Path,
) -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000503")
    request = PluginInvocationEnvelope(
        invocation_id=UUID("00000000-0000-4000-8000-000000000501"),
        execution_scope_id=UUID("00000000-0000-4000-8000-000000000502"),
        workspace_id=workspace_id,
        release=PluginInvocationRelease(
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=workspace_id,
            slug="outputs",
            revision=1,
            source_digest="a" * 64,
            contract_digest="b" * 64,
            protocol_digest=plugin_protocol_digest(),
            descriptor_digest="d" * 64,
        ),
        operator_id="outputs.write",
        operator_version=1,
        config={},
        inputs=(),
        outputs=(),
        limits=PluginInvocationLimits(max_output_bytes=8, max_files=1),
    )
    storage = _GuestBundleStorage(tmp_path, request)

    stored = await storage.save(
        SaveFileCommand(
            bucket="guest-outputs",
            path="objects/result.bin",
            stream=BytesIO(b"portable"),
            content_type="application/octet-stream",
            metadata={},
        )
    )

    assert stored.byte_size == 8
    assert (await storage.load("guest-outputs", stored.path)).read() == b"portable"
    with pytest.raises(PluginGuestError, match="destination is unsafe"):
        await storage.move("guest-outputs", stored.path, "../escaped.bin")
    with pytest.raises(PluginGuestError, match="byte limit"):
        await storage.save(
            SaveFileCommand(
                bucket="guest-outputs",
                path="objects/oversized.bin",
                stream=BytesIO(b"x"),
                content_type="application/octet-stream",
                metadata={},
            )
        )


@pytest.mark.asyncio
async def test_guest_object_set_codec_restores_and_rewrites_exact_file_set(
    tmp_path: Path,
) -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000503")
    artifact_id = UUID("00000000-0000-4000-8000-000000000504")
    key = ArtifactTypeKey("geo.raster_scan", 1)
    source_root = f"workspaces/{workspace_id}/{key.id}/v1"
    source_contents = {
        f"{source_root}/source.tif": b"exact cog",
        f"{source_root}/tiles/0/0/0.png": b"exact tile",
    }
    source_portable = PortableArtifactBundleMetadata(
        files=tuple(
            PortableArtifactFile(
                object_key=object_key,
                byte_size=len(content),
                sha256=sha256(content).hexdigest(),
                content_type=(
                    "image/tiff" if object_key.endswith(".tif") else "image/png"
                ),
            )
            for object_key, content in source_contents.items()
        ),
        references=(
            PortableMetadataReference(
                path=("raster_projection", "bucket"),
                kind="bucket",
            ),
            PortableMetadataReference(
                path=("raster_projection", "prefix"),
                kind="prefix",
            ),
        ),
    )
    source_metadata = {
        "original_filename": "scan.tif",
        "raster_projection": {
            "bucket": "artifacts",
            "prefix": f"{source_root}/tiles",
        },
        PORTABLE_BUNDLE_METADATA_KEY: source_portable.as_metadata_value(),
    }
    manifest = object_set_manifest(
        content_type="image/tiff",
        primary_object_key=f"{source_root}/source.tif",
        logical_byte_size=len(b"exact cog"),
        logical_sha256=sha256(b"exact cog").hexdigest(),
        metadata=source_metadata,
        portable=source_portable,
        object_prefix=source_root,
    )
    input_relative_path = "inputs/p0000/g0000/a000000.objects.tar"
    input_path = tmp_path / input_relative_path
    write_object_set_bundle(
        input_path,
        manifest,
        {
            descriptor.relative_path: source_contents[source.object_key]
            for source, descriptor in zip(
                source_portable.files,
                manifest.files,
                strict=True,
            )
        },
    )
    input_content = input_path.read_bytes()
    request = PluginInvocationEnvelope(
        invocation_id=UUID("00000000-0000-4000-8000-000000000501"),
        execution_scope_id=UUID("00000000-0000-4000-8000-000000000502"),
        workspace_id=workspace_id,
        release=PluginInvocationRelease(
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=workspace_id,
            slug="gis",
            revision=1,
            source_digest="a" * 64,
            contract_digest="b" * 64,
            protocol_digest=plugin_protocol_digest(),
            descriptor_digest="d" * 64,
        ),
        operator_id="gis.copy",
        operator_version=1,
        config={},
        inputs=(
            PluginInputBinding(
                port="source",
                artifact_type=PluginArtifactTypeKey.from_key(key),
                bundle=PluginArtifactBundleContract(format="object-set", version=1),
                groups=(
                    PluginInputArtifactGroup(
                        shape="one",
                        artifacts=(
                            PluginInputArtifactBundle(
                                artifact_id=artifact_id,
                                relative_path=input_relative_path,
                                byte_count=len(input_content),
                                content_sha256=sha256(input_content).hexdigest(),
                                content_type="application/x-tar",
                            ),
                        ),
                    ),
                ),
            ),
        ),
        outputs=(
            PluginOutputDeclaration(
                port="result",
                artifact_type=PluginArtifactTypeKey.from_key(key),
                bundle=PluginArtifactBundleContract(format="object-set", version=1),
                shape="one",
            ),
        ),
        limits=PluginInvocationLimits(),
    )
    unit_of_work = InMemoryUnitOfWork()
    storage = _GuestBundleStorage(tmp_path, request)
    staged_inputs = await _stage_input_artifacts(
        tmp_path,
        request,
        unit_of_work,
        storage,
        InputContract(
            model=_GuestObjectInput,
            ports={
                "source": InputPortSpec(
                    name="source",
                    accepts=key,
                    target_type=ArtifactRef,
                    preserves_ref_container=True,
                )
            },
        ),
    )

    staged_ref = staged_inputs["source"]
    assert isinstance(staged_ref, ArtifactRef)
    async with unit_of_work as entered:
        staged_artifact = await entered.artifacts.get(workspace_id, artifact_id)
    assert staged_artifact is not None
    projection = staged_artifact.metadata["raster_projection"]
    assert isinstance(projection, dict)
    assert projection["bucket"] == "guest-inputs"
    assert str(projection["prefix"]).startswith(f"object-sets/{artifact_id}/files/")

    output_root = f"workspaces/{workspace_id}/{key.id}/v1"
    output_files: list[PortableArtifactFile] = []
    for suffix, content_type in (
        ("source.tif", "image/tiff"),
        ("tiles/0/0/0.png", "image/png"),
    ):
        content = source_contents[f"{source_root}/{suffix}"]
        stored = await storage.save(
            SaveFileCommand(
                bucket="guest-outputs",
                path=f"{output_root}/{suffix}",
                stream=BytesIO(content),
                content_type=content_type,
                metadata={},
            )
        )
        output_files.append(
            PortableArtifactFile(
                object_key=stored.path,
                byte_size=stored.byte_size,
                sha256=stored.sha256,
                content_type=content_type,
            )
        )
    output_artifact = ArtifactObject(
        workspace_id=workspace_id,
        artifact_type=key.id,
        schema_version=key.schema_version,
        content_type="image/tiff",
        storage_backend="guest-bundle",
        bucket="guest-outputs",
        object_key=f"{output_root}/source.tif",
        byte_size=len(b"exact cog"),
        sha256=sha256(b"exact cog").hexdigest(),
        metadata={
            "original_filename": "scan.tif",
            "raster_projection": {
                "bucket": "guest-outputs",
                "prefix": f"{output_root}/tiles",
            },
            PORTABLE_BUNDLE_METADATA_KEY: PortableArtifactBundleMetadata(
                files=tuple(output_files),
                references=source_portable.references,
            ).as_metadata_value(),
        },
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(output_artifact)
        await entered.commit()
    (tmp_path / "outputs").mkdir()

    bindings = await _write_output_bundles(
        tmp_path,
        request,
        PersistedNodeOutput(values={"result": output_artifact.ref()}),
        unit_of_work,
        storage,
    )

    bundle = bindings[0].artifacts[0]
    output_manifest, output_contents = load_object_set_bundle(
        tmp_path / bundle.relative_path,
        max_bytes=request.limits.max_output_bytes,
        max_files=request.limits.max_files,
    )
    assert output_manifest.logical_sha256 == output_artifact.sha256
    assert output_manifest.metadata["original_filename"] == "scan.tif"
    assert set(output_contents.values()) == {b"exact cog", b"exact tile"}


@pytest.mark.asyncio
async def test_guest_staged_upload_repository_exposes_only_digest_bound_file(
    tmp_path: Path,
) -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000503")
    content = b"authorized upload"
    relative_path = f"uploads/{workspace_id}/upload-01"
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    request = PluginInvocationEnvelope(
        invocation_id=UUID("00000000-0000-4000-8000-000000000501"),
        execution_scope_id=UUID("00000000-0000-4000-8000-000000000502"),
        workspace_id=workspace_id,
        release=PluginInvocationRelease(
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=workspace_id,
            slug="uploads",
            revision=1,
            source_digest="a" * 64,
            contract_digest="b" * 64,
            protocol_digest=plugin_protocol_digest(),
            descriptor_digest="d" * 64,
        ),
        operator_id="uploads.read",
        operator_version=1,
        config={},
        inputs=(),
        outputs=(),
        staged_uploads=(
            PluginStagedUploadBinding(
                config_field="uploads",
                upload_key="upload-01",
                original_filename="source.csv",
                byte_count=len(content),
                content_sha256=sha256(content).hexdigest(),
                relative_path=relative_path,
            ),
        ),
        limits=PluginInvocationLimits(),
    )
    unit_of_work = InMemoryUnitOfWork()

    await _stage_uploaded_files(tmp_path, request, unit_of_work)
    resolved = await resolve_persisted_staged_upload_path(
        tmp_path / "uploads",
        unit_of_work,
        workspace_id=workspace_id,
        upload_key="upload-01",
    )

    assert resolved.read_bytes() == content
