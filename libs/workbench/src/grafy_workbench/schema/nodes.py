import json
from enum import StrEnum
from typing import Annotated, Self, final, override

from jsonschema import Draft202012Validator
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    model_validator,
)

from grafy_core.artifacts import (
    Artifact,
    ArtifactRef,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import InPort, Node, NodeExecutionContext, OutPort
from grafy_core.plugins import NodeCachePolicy
from grafy_core.schema_contracts import (
    JSON_SCHEMA,
    JsonSchemaPayload,
    parse_json_schema,
)

from grafy_workbench.scalar_persistence import ScalarOutputWriter, ScalarResolver
from grafy_workbench.schema.declaration import SCHEMAS


class SchemaFieldKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SEQUENCE = "sequence"
    SCHEMA = "schema"


class SchemaSequenceItemKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SCHEMA = "schema"


class JsonSchemaBuilderField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(
        min_length=1,
        max_length=255,
        description="Stable field identifier and instance-plug identifier.",
    )
    name: StrictStr = Field(
        min_length=1,
        description="Property name emitted in the object schema.",
    )
    kind: SchemaFieldKind
    required: bool = False
    description: StrictStr = ""
    item_kind: SchemaSequenceItemKind | None = None

    @model_validator(mode="after")
    def validate_field(self) -> Self:
        if self.id != self.id.strip():
            raise ValueError("Schema field id must not have surrounding whitespace")
        if self.kind is SchemaFieldKind.SEQUENCE and self.item_kind is None:
            raise ValueError("Sequence schema fields must declare item_kind")
        if self.kind is not SchemaFieldKind.SEQUENCE and self.item_kind is not None:
            raise ValueError("Only sequence schema fields may declare item_kind")
        return self


class JsonSchemaBuilderConfig(NodeConfig):
    title: StrictStr = Field(
        default="",
        description="Optional title included in the generated object schema.",
    )
    description: StrictStr = Field(
        default="",
        description="Optional description included in the generated object schema.",
    )
    additional_properties: bool = Field(
        default=False,
        description="Whether properties not declared by the builder are allowed.",
    )
    fields: list[JsonSchemaBuilderField] = Field(
        default_factory=list,
        description="Ordered fields in the generated object schema.",
    )

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        field_ids = [field.id for field in self.fields]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("Schema field ids must be unique")

        field_names = [field.name for field in self.fields]
        if len(field_names) != len(set(field_names)):
            raise ValueError("Schema field names must be unique")
        return self


class JsonSchemaBuilderInput(NodeInput):
    schemas: Annotated[
        list[str],
        InPort(JSON_SCHEMA, variadic=True, instance_plugs=True),
    ] = Field(
        default_factory=list,
        description=(
            "Connected child schemas in the order of schema-consuming fields."
        ),
    )


class JsonSchemaBuilderOutput(NodeOutput):
    json_schema: Annotated[
        str,
        OutPort(JSON_SCHEMA),
        Field(
            title="JSON Schema",
            description="Canonical Draft 2020-12 object JSON Schema text.",
        ),
    ]


@SCHEMAS.node(
    operator_id="schema.builder",
    version=1,
    title="Schema Builder",
    cache_policy=NodeCachePolicy.EXACT,
)
@final
class JsonSchemaBuilderNode(
    Node[JsonSchemaBuilderConfig, JsonSchemaBuilderInput, JsonSchemaBuilderOutput]
):
    """Builds one object JSON Schema with optional connected child schemas."""

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        config: JsonSchemaBuilderConfig,
        inputs: JsonSchemaBuilderInput,
        /,
    ) -> JsonSchemaBuilderOutput:
        schema_fields = [
            field
            for field in config.fields
            if field.kind is SchemaFieldKind.SCHEMA
            or (
                field.kind is SchemaFieldKind.SEQUENCE
                and field.item_kind is SchemaSequenceItemKind.SCHEMA
            )
        ]
        if len(inputs.schemas) != len(schema_fields):
            expected_fields = ", ".join(
                f"{field.name!r} ({field.id})" for field in schema_fields
            )
            raise ValueError(
                "Schema Builder expected "
                f"{len(schema_fields)} connected schema(s) for fields "
                f"[{expected_fields}], got {len(inputs.schemas)}"
            )

        primitive_types = {
            SchemaFieldKind.STRING: "string",
            SchemaFieldKind.INTEGER: "integer",
            SchemaFieldKind.NUMBER: "number",
            SchemaFieldKind.BOOLEAN: "boolean",
        }
        sequence_primitive_types = {
            SchemaSequenceItemKind.STRING: "string",
            SchemaSequenceItemKind.INTEGER: "integer",
            SchemaSequenceItemKind.NUMBER: "number",
            SchemaSequenceItemKind.BOOLEAN: "boolean",
        }
        properties: dict[str, object] = {}
        required: list[str] = []
        child_index = 0
        for field in config.fields:
            if field.kind in primitive_types:
                json_type = primitive_types[field.kind]
                definition = (
                    {"type": json_type}
                    if field.required
                    else {"type": [json_type, "null"]}
                )
            elif field.kind is SchemaFieldKind.SCHEMA:
                definition = parse_json_schema(
                    inputs.schemas[child_index],
                    context=f"field {field.name!r} ({field.id})",
                )
                child_index += 1
            else:
                item_kind = field.item_kind
                if item_kind is None:
                    raise ValueError(
                        f"Sequence field {field.name!r} ({field.id}) does not "
                        "declare an item kind"
                    )
                if item_kind is not SchemaSequenceItemKind.SCHEMA:
                    items: dict[str, object] = {
                        "type": sequence_primitive_types[item_kind]
                    }
                else:
                    items = parse_json_schema(
                        inputs.schemas[child_index],
                        context=(
                            f"sequence items for field {field.name!r} ({field.id})"
                        ),
                    )
                    child_index += 1
                definition = {"type": "array", "items": items}

            if field.description:
                definition["description"] = field.description
            properties[field.name] = definition
            if field.required:
                required.append(field.name)

        schema_definition: dict[str, object] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": config.additional_properties,
        }
        if config.title:
            schema_definition["title"] = config.title
        if config.description:
            schema_definition["description"] = config.description
        if required:
            schema_definition["required"] = required
        Draft202012Validator.check_schema(schema_definition)
        return JsonSchemaBuilderOutput(
            json_schema=_canonical_schema_text(schema_definition)
        )


def _canonical_schema_text(schema_definition: dict[str, object]) -> str:
    return json.dumps(
        schema_definition,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _normalize_schema_value(value: object) -> str:
    payload = JsonSchemaPayload.model_validate({"value": value})
    schema_definition = parse_json_schema(payload.value, context="artifact output")
    return _canonical_schema_text(schema_definition)


def _check_schema_value(value: str, ref: ArtifactRef) -> None:
    _ = parse_json_schema(value, context=f"artifact {ref.artifact_id}")


SCHEMAS.register(
    Artifact(
        spec=JSON_SCHEMA,
        resolver=lambda context: ScalarResolver(
            source=JSON_SCHEMA.key,
            target=str,
            model=JsonSchemaPayload,
            uow=context.uow,
            check=_check_schema_value,
        ),
        writer=lambda context: ScalarOutputWriter(
            artifact_type=JSON_SCHEMA.key,
            model=JsonSchemaPayload,
            uow=context.uow,
            normalize=_normalize_schema_value,
        ),
    )
)


__all__ = [
    "SCHEMAS",
    "JsonSchemaBuilderConfig",
    "JsonSchemaBuilderField",
    "JsonSchemaBuilderInput",
    "JsonSchemaBuilderNode",
    "JsonSchemaBuilderOutput",
    "SchemaFieldKind",
    "SchemaSequenceItemKind",
]
