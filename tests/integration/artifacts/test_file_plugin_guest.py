"""File interpretation operators run through the published Plugin wire contract."""

import base64
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.domain.plugin_releases import (
    PluginArtifactBundleContract,
    PluginArtifactTypeKey,
    PluginCatalogManifest,
    PluginReleaseScope,
    plugin_contract_digest,
    plugin_protocol_digest,
)
from grafy_core.file_contracts import CSV_FILE, PNG_FILE
from grafy_core.runtime.plugin_guest import execute_plugin_invocation
from grafy_core.runtime.plugin_loader import PluginGuestLoaderManifest
from grafy_core.runtime.plugin_protocol import (
    PluginInputArtifactBundle,
    PluginInputArtifactGroup,
    PluginInputBinding,
    PluginInvocationEnvelope,
    PluginInvocationLimits,
    PluginInvocationRelease,
    PluginInvocationResultEnvelope,
    PluginOutputDeclaration,
)
from grafy_core.runtime.table_bundle import load_table_bundle
from grafy_core.table_contracts import TABLE_DATA
from grafy_plugin_image import IMAGES
from grafy_plugin_table import TABLES


@pytest.mark.parametrize("family", ["image", "table"])
async def test_file_operator_exports_exact_portable_output(
    tmp_path: Path,
    family: str,
) -> None:
    if family == "image":
        plugin = IMAGES
        loader_target = "grafy_plugin_image.plugin:IMAGES"
        file_type = PNG_FILE
        value_type = RASTER_IMAGE
        content = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1cAAAAASUVORK5CYII="
        )
        input_port, output_port, shape = "files", "images", "many"
        content_type = "image/png"
    else:
        plugin = TABLES
        loader_target = "grafy_plugin_table.plugin:TABLES"
        file_type = CSV_FILE
        value_type = TABLE_DATA
        content = b"Name,Count\nLodz,2\nWarsaw,3\n"
        input_port, output_port, shape = "file", "table", "one"
        content_type = "text/csv"
    catalog = PluginCatalogManifest.from_plugin(plugin)
    operator = catalog.nodes[0]
    input_path = tmp_path / "inputs/source.bin"
    input_path.parent.mkdir()
    _ = input_path.write_bytes(content)
    (tmp_path / "outputs").mkdir()
    loader_path = tmp_path / "plugin-loader.json"
    _ = loader_path.write_bytes(
        PluginGuestLoaderManifest(
            slug=plugin.slug,
            loader_target=loader_target,
        ).canonical_json_bytes()
    )
    request = PluginInvocationEnvelope(
        invocation_id=uuid4(),
        execution_scope_id=uuid4(),
        workspace_id=uuid4(),
        release=PluginInvocationRelease(
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
            slug=plugin.slug,
            revision=1,
            source_digest="a" * 64,
            contract_digest=plugin_contract_digest(catalog),
            protocol_digest=plugin_protocol_digest(),
            descriptor_digest="d" * 64,
        ),
        operator_id=operator.operator_id,
        operator_version=operator.operator_version,
        config={},
        inputs=(
            PluginInputBinding(
                port=input_port,
                artifact_type=PluginArtifactTypeKey.from_key(file_type.key),
                bundle=PluginArtifactBundleContract.from_contract(file_type.bundle),
                groups=(
                    PluginInputArtifactGroup(
                        shape=shape,
                        artifacts=(
                            PluginInputArtifactBundle(
                                artifact_id=uuid4(),
                                relative_path="inputs/source.bin",
                                byte_count=len(content),
                                content_sha256=sha256(content).hexdigest(),
                                content_type=content_type,
                                metadata={"original_filename": f"source.{family}"},
                            ),
                        ),
                    ),
                ),
            ),
        ),
        outputs=(
            PluginOutputDeclaration(
                port=output_port,
                artifact_type=PluginArtifactTypeKey.from_key(value_type.key),
                bundle=PluginArtifactBundleContract.from_contract(value_type.bundle),
                shape=shape,
            ),
        ),
        limits=PluginInvocationLimits(),
    )
    _ = (tmp_path / "invocation.json").write_bytes(request.canonical_json_bytes())

    await execute_plugin_invocation(tmp_path, system_loader_manifest_path=loader_path)

    result = PluginInvocationResultEnvelope.model_validate_json(
        (tmp_path / "result.json").read_bytes()
    )
    assert result.status == "succeeded", result.failure
    assert len(result.outputs) == 1
    output = result.outputs[0]
    assert output.artifact_type == PluginArtifactTypeKey.from_key(value_type.key)
    assert output.bundle.format == (
        "binary-file" if family == "image" else "table-bundle"
    )
    assert len(output.artifacts) == 1
    artifact = output.artifacts[0]
    assert artifact.byte_count > 0
    if family == "image":
        assert (tmp_path / artifact.relative_path).read_bytes() == content
        assert artifact.content_type == "image/png"
    else:
        table = load_table_bundle(
            tmp_path / artifact.relative_path,
            max_bytes=1_000_000,
            max_files=100,
            max_rows=100,
            max_columns=100,
            max_chunks=100,
        )
        assert [column.title for column in table.columns] == ["Name", "Count"]
        assert table.rows == [
            {"column_1": "Lodz", "column_2": "2"},
            {"column_1": "Warsaw", "column_2": "3"},
        ]
