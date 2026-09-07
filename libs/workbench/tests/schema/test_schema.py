import json
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from grafy_core.artifacts import ArtifactTypeKey, InMemoryUnitOfWork
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.materialization import (
    InputMaterializer,
    MaterializationProvenance,
)
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_core.schema_contracts import (
    JSON_SCHEMA,
    parse_json_schema,
    validate_json_schema_value,
)
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.schema.nodes import (
    JsonSchemaBuilderConfig,
    JsonSchemaBuilderInput,
    JsonSchemaBuilderNode,
    SchemaFieldKind,
    SchemaSequenceItemKind,
)


TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


def test_schema_plugin_declares_nominal_string_artifact_and_builder_contract() -> None:
    registry = PluginRegistry()
    registry.install(SCHEMAS)
    registry.freeze()

    assert SCHEMAS.slug == "schema"
    assert SCHEMAS.title == "Schema"
    assert [artifact.key for artifact in SCHEMAS.artifact_types] == [
        ArtifactTypeKey("json.schema", 1)
    ]
    assert [registration.key for registration in SCHEMAS.nodes] == [
        ("schema.builder", 1)
    ]

    schemas_input = JsonSchemaBuilderNode.input_contract.ports["schemas"]
    assert schemas_input.accepts == JSON_SCHEMA.key
    assert schemas_input.shape is PortShape.ONE
    assert schemas_input.accepted_shapes == (PortShape.ONE,)
    assert schemas_input.variadic is True
    assert schemas_input.instance_plugs is True
    assert schemas_input.target_type is str
    assert schemas_input.preserves_ref_container is False
    assert schemas_input.required is False

    schema_output = JsonSchemaBuilderNode.output_contract.ports["json_schema"]
    assert schema_output.produces == JSON_SCHEMA.key
    assert schema_output.shape is PortShape.ONE


def test_schema_builder_config_validates_ordered_field_identity_and_item_kinds() -> (
    None
):
    config = JsonSchemaBuilderConfig.model_validate(
        {
            "fields": [
                {
                    "id": "number",
                    "name": "invoice_number",
                    "kind": "string",
                    "required": True,
                },
                {
                    "id": "lines",
                    "name": "line_items",
                    "kind": "sequence",
                    "item_kind": "schema",
                },
            ]
        }
    )

    assert config.title == ""
    assert config.description == ""
    assert config.additional_properties is False
    assert config.fields[0].kind is SchemaFieldKind.STRING
    assert config.fields[1].item_kind is SchemaSequenceItemKind.SCHEMA

    with pytest.raises(ValidationError, match="field ids must be unique"):
        JsonSchemaBuilderConfig.model_validate(
            {
                "fields": [
                    {"id": "same", "name": "first", "kind": "string"},
                    {"id": "same", "name": "second", "kind": "integer"},
                ]
            }
        )
    with pytest.raises(ValidationError, match="field names must be unique"):
        JsonSchemaBuilderConfig.model_validate(
            {
                "fields": [
                    {"id": "first", "name": "same", "kind": "string"},
                    {"id": "second", "name": "same", "kind": "integer"},
                ]
            }
        )
    with pytest.raises(ValidationError, match="must declare item_kind"):
        JsonSchemaBuilderConfig.model_validate(
            {"fields": [{"id": "lines", "name": "lines", "kind": "sequence"}]}
        )
    with pytest.raises(ValidationError, match="Only sequence"):
        JsonSchemaBuilderConfig.model_validate(
            {
                "fields": [
                    {
                        "id": "number",
                        "name": "number",
                        "kind": "string",
                        "item_kind": "string",
                    }
                ]
            }
        )


@pytest.mark.asyncio
async def test_schema_builder_compiles_inline_fields_to_canonical_object_schema() -> (
    None
):
    output = await JsonSchemaBuilderNode().run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="invoice-schema"),
        JsonSchemaBuilderConfig.model_validate(
            {
                "title": "Invoice",
                "description": "Extracted invoice fields",
                "additional_properties": False,
                "fields": [
                    {
                        "id": "number",
                        "name": "number",
                        "kind": "string",
                        "required": True,
                        "description": "Invoice number",
                    },
                    {
                        "id": "page_count",
                        "name": "page_count",
                        "kind": "integer",
                    },
                    {
                        "id": "confidence",
                        "name": "confidence",
                        "kind": "number",
                    },
                    {
                        "id": "reviewed",
                        "name": "reviewed",
                        "kind": "boolean",
                    },
                    {
                        "id": "tags",
                        "name": "tags",
                        "kind": "sequence",
                        "item_kind": "string",
                    },
                ],
            }
        ),
        JsonSchemaBuilderInput(),
    )

    assert output.json_schema == json.dumps(
        json.loads(output.json_schema),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert json.loads(output.json_schema) == {
        "title": "Invoice",
        "description": "Extracted invoice fields",
        "type": "object",
        "properties": {
            "number": {
                "type": "string",
                "description": "Invoice number",
            },
            "page_count": {"type": ["integer", "null"]},
            "confidence": {"type": ["number", "null"]},
            "reviewed": {"type": ["boolean", "null"]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
        "required": ["number"],
    }
    assert list(json.loads(output.json_schema)["properties"]) == [
        "number",
        "page_count",
        "confidence",
        "reviewed",
        "tags",
    ]


@pytest.mark.asyncio
async def test_schema_builder_inserts_connected_object_and_sequence_item_schemas() -> (
    None
):
    customer_schema = (
        '{"type":"object","title":"Customer","properties":'
        '{"name":{"type":"string"}},"required":["name"]}'
    )
    line_schema = (
        '{"type":"object","title":"Line","properties":{"quantity":{"type":"integer"}}}'
    )
    config = JsonSchemaBuilderConfig.model_validate(
        {
            "title": "Invoice",
            "fields": [
                {
                    "id": "customer-plug",
                    "name": "customer",
                    "kind": "schema",
                    "required": True,
                },
                {
                    "id": "status",
                    "name": "status",
                    "kind": "string",
                },
                {
                    "id": "line-items-plug",
                    "name": "line_items",
                    "kind": "sequence",
                    "item_kind": "schema",
                    "description": "Invoice lines",
                },
            ],
        }
    )

    output = await JsonSchemaBuilderNode().run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="invoice-schema"),
        config,
        JsonSchemaBuilderInput(schemas=[customer_schema, line_schema]),
    )

    schema = json.loads(output.json_schema)
    assert schema["properties"] == {
        "customer": json.loads(customer_schema),
        "status": {"type": ["string", "null"]},
        "line_items": {
            "type": "array",
            "items": json.loads(line_schema),
            "description": "Invoice lines",
        },
    }
    assert schema["required"] == ["customer"]


@pytest.mark.asyncio
async def test_schema_builder_reports_missing_connected_schema_field_ids() -> None:
    config = JsonSchemaBuilderConfig.model_validate(
        {
            "fields": [
                {"id": "customer-plug", "name": "customer", "kind": "schema"},
                {
                    "id": "lines-plug",
                    "name": "lines",
                    "kind": "sequence",
                    "item_kind": "schema",
                },
            ]
        }
    )

    with pytest.raises(ValueError) as exc_info:
        await JsonSchemaBuilderNode().run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="schema"),
            config,
            JsonSchemaBuilderInput(schemas=['{"type":"object","properties":{}}']),
        )

    message = str(exc_info.value)
    assert "expected 2 connected schema(s)" in message
    assert "'customer' (customer-plug)" in message
    assert "'lines' (lines-plug)" in message
    assert "got 1" in message


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ("not JSON", "not valid JSON"),
        ("[]", "must be a JSON object"),
        ('{"type":"array"}', "must declare type='object'"),
        ('{"type":"object","required":"value"}', "Draft 2020-12"),
    ],
)
def test_parse_json_schema_rejects_invalid_object_schema(
    schema: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_json_schema(schema)


def test_validate_json_schema_value_returns_matching_object_with_error_path() -> None:
    schema = (
        '{"type":"object","properties":{"count":{"type":"integer"}},'
        '"required":["count"],"additionalProperties":false}'
    )
    value: dict[str, object] = {"count": 3}

    assert validate_json_schema_value(schema, value) is value
    with pytest.raises(ValueError) as exc_info:
        validate_json_schema_value(schema, {"count": "three"})

    message = str(exc_info.value)
    assert "$.count" in message
    assert "is not of type 'integer'" in message


@pytest.mark.asyncio
async def test_schema_artifact_factories_and_typed_instance_plugs_round_trip(
    tmp_path: Path,
) -> None:
    uow = InMemoryUnitOfWork()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        uploads_dir=tmp_path / "uploads",
        storage=cast(FileStoragePort, object()),
        uow=uow,
        bucket="artifacts",
    )
    registry = PluginRegistry()
    registry.install(SCHEMAS)
    registry.freeze()
    writer = registry.build_writers(context)[0]
    resolver = registry.build_resolvers(context)[0]
    write_context = ArtifactWriteContext(
        node_context=NodeExecutionContext(
            workspace_id=TEST_WORKSPACE_ID,
            node_id="child-schema",
        ),
        provenance=MaterializationProvenance(refs_by_input={}),
    )
    child_schema = '{ "properties": {}, "type": "object" }'
    canonical_child_schema = '{"properties":{},"type":"object"}'
    child_ref = await writer.write(child_schema, write_context)

    inputs, provenance = await InputMaterializer(
        ResolverRegistry([resolver])
    ).materialize(
        JsonSchemaBuilderNode.input_contract,
        {"schemas": [child_ref]},
        TEST_WORKSPACE_ID,
    )

    assert inputs.schemas == [canonical_child_schema]
    assert provenance.refs_for("schemas") == (child_ref,)
    output = await JsonSchemaBuilderNode().run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="parent-schema"),
        JsonSchemaBuilderConfig.model_validate(
            {"fields": [{"id": "child", "name": "child", "kind": "schema"}]}
        ),
        inputs,
    )
    parent_ref = await writer.write(
        output.json_schema,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=TEST_WORKSPACE_ID,
                node_id="parent-schema",
            ),
            provenance=provenance,
        ),
    )

    assert await resolver.resolve(parent_ref, TEST_WORKSPACE_ID) == output.json_schema
    async with uow as entered:
        artifact = await entered.artifacts.get(
            TEST_WORKSPACE_ID, parent_ref.artifact_id
        )
    assert artifact is not None
    assert artifact.inline_payload == {"value": output.json_schema}
    assert artifact.metadata["provenance"] == {
        "schemas": [
            {
                "artifact_id": str(child_ref.artifact_id),
                "artifact_type": JSON_SCHEMA.key.id,
                "schema_version": JSON_SCHEMA.key.schema_version,
            }
        ]
    }
