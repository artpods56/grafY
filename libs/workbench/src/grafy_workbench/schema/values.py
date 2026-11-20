"""JSON Schema value class and its one artifact declaration."""

import json

from pydantic import BaseModel, ConfigDict, StrictStr

from grafy_core.runtime.artifact_values import (
    Artifact,
    ArtifactFiles,
    EncodedArtifact,
    StoredArtifact,
    encode_inline_model,
)
from grafy_core.runtime.resolvers import ArtifactContractError, ResolutionError
from grafy_core.schema_contracts import (
    JSON_SCHEMA,
    JsonSchemaPayload,
    parse_json_schema,
)


class JsonSchemaText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictStr


def canonical_schema_text(schema_definition: dict[str, object]) -> str:
    return json.dumps(
        schema_definition,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def canonicalize_json_schema(value: str) -> str:
    return canonical_schema_text(parse_json_schema(value, context="artifact output"))


def json_schema_artifact() -> Artifact[JsonSchemaText]:
    async def resolve(stored: StoredArtifact) -> JsonSchemaText:
        if stored.row.inline_payload is None:
            raise ArtifactContractError(
                f"Artifact {stored.row.id} does not have an inline JSON payload"
            )
        try:
            payload = JsonSchemaPayload.model_validate(stored.row.inline_payload)
        except Exception as exc:
            raise ResolutionError(
                f"Failed to resolve artifact {stored.row.id} as "
                f"{JsonSchemaPayload.__module__}.{JsonSchemaPayload.__qualname__}"
            ) from exc
        try:
            _ = parse_json_schema(
                payload.value,
                context=f"artifact {stored.row.id}",
            )
        except ValueError as exc:
            raise ResolutionError(
                f"Failed to resolve artifact {stored.row.id} as "
                "json.schema@1 scalar value"
            ) from exc
        return JsonSchemaText(value=payload.value)

    async def write(value: JsonSchemaText, _files: ArtifactFiles) -> EncodedArtifact:
        canonical = canonicalize_json_schema(value.value)
        return encode_inline_model(JsonSchemaPayload(value=canonical))

    return Artifact(
        spec=JSON_SCHEMA,
        value_type=JsonSchemaText,
        resolve=resolve,
        write=write,
    )
