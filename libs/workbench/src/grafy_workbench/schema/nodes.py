import json
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Self, cast, final, override
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    model_validator,
)

from grafy_core.artifacts import (
    Artifact,
    ArtifactObject,
    ArtifactRef,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.domain.errors import NotFoundError
from grafy_core.nodes import InPort, Node, NodeExecutionContext, OutPort
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.persistence import ArtifactOutputWriter, ArtifactWriteContext
from grafy_core.runtime.resolvers import (
    ArtifactContractError,
    ResolutionError,
    Resolver,
)
from grafy_core.schema_contracts import (
    JSON_SCHEMA,
    JsonSchemaPayload,
    parse_json_schema,
)

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


@final
class JsonSchemaOutputWriter(ArtifactOutputWriter):
    artifact_type = JSON_SCHEMA.key

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        try:
            payload = JsonSchemaPayload.model_validate({"value": value})
            schema_definition = parse_json_schema(
                payload.value,
                context="artifact output",
            )
            payload = JsonSchemaPayload(value=_canonical_schema_text(schema_definition))
        except (ValidationError, ValueError) as exc:
            message = (
                f"Failed to serialize {self.artifact_type.id}@"
                f"{self.artifact_type.schema_version} value produced by node "
                f"{context.node_context.node_id!r}"
            )
            raise RuntimeError(message) from exc

        payload_json = cast(JsonObject, payload.model_dump(mode="json"))
        payload_bytes = json.dumps(
            payload_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        provenance: dict[str, object] = {
            input_name: [
                {
                    "artifact_id": str(ref.artifact_id),
                    "artifact_type": ref.artifact_type,
                    "schema_version": ref.schema_version,
                }
                for ref in refs
            ]
            for input_name, refs in context.provenance.refs_by_input.items()
        }
        metadata: JsonObject = {
            "producer_node_id": context.node_context.node_id,
        }
        if provenance:
            metadata["provenance"] = provenance
        metadata.update(context.metadata)
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type="application/json",
            storage_backend="inline",
            inline_payload=payload_json,
            byte_size=len(payload_bytes),
            sha256=sha256(payload_bytes).hexdigest(),
            metadata=metadata,
        )
        try:
            async with self._uow as uow:
                await uow.artifacts.add(artifact)
                await uow.commit()
        except Exception as exc:
            message = (
                f"Failed to persist {self.artifact_type.id}@"
                f"{self.artifact_type.schema_version} produced by node "
                f"{context.node_context.node_id!r}"
            )
            raise RuntimeError(message) from exc
        return artifact.ref()


@final
class JsonSchemaResolver(Resolver[str]):
    source = JSON_SCHEMA.key
    target: type[object] = str

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    @override
    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> str:
        if ref.key() != self.source:
            message = (
                f"JSON Schema resolver expected {self.source.id}@"
                f"{self.source.schema_version}, got {ref.artifact_type}@"
                f"{ref.schema_version} for artifact {ref.artifact_id}"
            )
            raise ArtifactContractError(message)

        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact", str(ref.artifact_id))
        if artifact.ref() != ref:
            message = (
                "Artifact repository returned a different artifact ref for "
                f"JSON Schema artifact {ref.artifact_id}"
            )
            raise ArtifactContractError(message)
        if artifact.inline_payload is None:
            message = (
                f"JSON Schema artifact {ref.artifact_id} does not have an inline "
                "JSON payload"
            )
            raise ArtifactContractError(message)

        try:
            payload = JsonSchemaPayload.model_validate(artifact.inline_payload)
            parse_json_schema(payload.value, context=f"artifact {ref.artifact_id}")
            return payload.value
        except (ValidationError, ValueError) as exc:
            message = (
                f"Failed to resolve artifact {ref.artifact_id} as "
                f"{self.source.id}@{self.source.schema_version} JSON Schema"
            )
            raise ResolutionError(message) from exc


SCHEMAS.register(
    Artifact(
        spec=JSON_SCHEMA,
        resolver=lambda context: JsonSchemaResolver(uow=context.uow),
        writer=lambda context: JsonSchemaOutputWriter(uow=context.uow),
    )
)


__all__ = [
    "SCHEMAS",
    "JsonSchemaOutputWriter",
    "JsonSchemaResolver",
    "JsonSchemaBuilderConfig",
    "JsonSchemaBuilderField",
    "JsonSchemaBuilderInput",
    "JsonSchemaBuilderNode",
    "JsonSchemaBuilderOutput",
    "SchemaFieldKind",
    "SchemaSequenceItemKind",
]
