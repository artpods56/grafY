from difflib import unified_diff
from hashlib import sha256
import json
from pathlib import Path
from typing import cast

from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginPortContract,
)
from grafy_core.plugins import Plugin
from grafy_workbench.arithmetic import ARITHMETIC
from grafy_plugin_gis import GIS
from grafy_workbench.file import FILES
from grafy_workbench.image import IMAGES
from grafy_plugin_llm import LLM
from grafy_plugin_ocr import OCR
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.sequence import SEQUENCES
from grafy_plugin_sql import SQL
from grafy_workbench.table import TABLES
from grafy_workbench.text import TEXT


SNAPSHOT_PATH = Path(__file__).with_name("system_plugin_catalog_identity.json")
SYSTEM_PLUGINS = (
    ARITHMETIC,
    IMAGES,
    SEQUENCES,
    TEXT,
    SCHEMAS,
    TABLES,
    FILES,
    GIS,
    LLM,
    OCR,
    SQL,
)
EXPECTED_SYSTEM_PLUGIN_SLUGS = (
    "arithmetic",
    "image",
    "sequence",
    "text",
    "schema",
    "table",
    "file",
    "external.gis",
    "external.llm",
    "external.ocr",
    "external.sql",
)


def _schema_identity(schema: dict[str, object]) -> dict[str, object]:
    properties_value = schema.get("properties", {})
    required_value = schema.get("required", [])
    if not isinstance(properties_value, dict):
        raise TypeError("JSON Schema properties must be an object")
    if not isinstance(required_value, list):
        raise TypeError("JSON Schema required must be an array of field names")
    required_items = cast(list[object], required_value)
    if not all(isinstance(field, str) for field in required_items):
        raise TypeError("JSON Schema required must be an array of field names")
    properties = cast(dict[str, object], properties_value)
    required = cast(list[str], required_items)
    payload = json.dumps(
        schema,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "fields": list(properties),
        "required": required,
        "sha256": sha256(payload).hexdigest(),
    }


def _port_identity(port: PluginPortContract) -> dict[str, object]:
    artifact_type = port.artifact_type
    artifact = (
        f"{artifact_type.id}@{artifact_type.schema_version}"
        if artifact_type is not None
        else f"${port.artifact_type_variable}"
    )
    return {
        "accepted_shapes": [shape.value for shape in port.accepted_shapes],
        "artifact": artifact,
        "description": port.description,
        "instance_plugs": port.instance_plugs,
        "name": port.name,
        "required": port.required,
        "shape": port.shape.value,
        "title": port.title,
        "variadic": port.variadic,
    }


def _artifact_identity(
    artifact: PluginArtifactTypeContract,
) -> dict[str, object]:
    return {
        "bundle": f"{artifact.bundle.format}@{artifact.bundle.version}",
        "exports": [
            {
                "content_type": export.content_type,
                "filename": export.filename,
                "format": export.format,
            }
            for export in artifact.export_formats
        ],
        "key": f"{artifact.key.id}@{artifact.key.schema_version}",
        "materialized_json_type": artifact.materialized_json_type,
        "projections": [
            {
                "path": list(projection.path),
                "target": (
                    f"{projection.target.id}@{projection.target.schema_version}"
                ),
                "title": projection.title,
            }
            for projection in artifact.field_projections
        ],
        "references": [
            {
                "path": list(reference.path),
                "shape": reference.shape,
                "target": (
                    f"{reference.target.id}@{reference.target.schema_version}"
                ),
            }
            for reference in artifact.references
        ],
        "schema": _schema_identity(artifact.payload_schema),
        "title": artifact.title,
    }


def _node_identity(node: PluginNodeContract) -> dict[str, object]:
    return {
        "cache_policy": node.cache_policy.value,
        "config": _schema_identity(node.config_schema),
        "description": node.description,
        "input_schema": _schema_identity(node.input_schema),
        "inputs": [_port_identity(port) for port in node.inputs],
        "key": f"{node.operator_id}@{node.operator_version}",
        "output_schema": _schema_identity(node.output_schema),
        "outputs": [_port_identity(port) for port in node.outputs],
        "required_capabilities": [
            capability.value for capability in node.required_capabilities
        ],
        "secret_inputs": [
            {
                "config_dependencies": list(secret.config_dependencies),
                "description": secret.description,
                "name": secret.name,
                "title": secret.title,
            }
            for secret in node.secret_inputs
        ],
        "staged_upload_inputs": [
            staged.config_field for staged in node.staged_upload_inputs
        ],
        "title": node.title,
    }


def _plugin_identity(plugin: Plugin) -> dict[str, object]:
    catalog = PluginCatalogManifest.from_plugin(plugin)
    return {
        "artifact_dependencies": [
            _artifact_identity(artifact)
            for artifact in catalog.artifact_type_dependencies
        ],
        "artifact_types": [
            _artifact_identity(artifact) for artifact in catalog.artifact_types
        ],
        "capabilities": sorted(capability.value for capability in plugin.capabilities),
        "conversions": [
            {
                "key": f"{conversion.key.id}@{conversion.key.version}",
                "source": (
                    f"{conversion.source.id}@{conversion.source.schema_version}"
                ),
                "target": (
                    f"{conversion.target.id}@{conversion.target.schema_version}"
                ),
                "title": conversion.title,
            }
            for conversion in catalog.artifact_conversions
        ],
        "nodes": [_node_identity(node) for node in catalog.nodes],
        "title": catalog.title,
    }


def _system_catalog_identity() -> dict[str, object]:
    return {
        "plugins": {plugin.slug: _plugin_identity(plugin) for plugin in SYSTEM_PLUGINS},
        "schema_version": 1,
    }


def test_system_plugin_catalog_identity_matches_checked_in_contract() -> None:
    assert (
        tuple(plugin.slug for plugin in SYSTEM_PLUGINS) == EXPECTED_SYSTEM_PLUGIN_SLUGS
    )

    expected_text = SNAPSHOT_PATH.read_text()
    expected = json.loads(expected_text)
    actual = _system_catalog_identity()
    actual_text = (
        json.dumps(
            actual,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    assert actual == expected, "".join(
        unified_diff(
            expected_text.splitlines(keepends=True),
            actual_text.splitlines(keepends=True),
            fromfile=SNAPSHOT_PATH.name,
            tofile="current System Plugin declarations",
        )
    )
