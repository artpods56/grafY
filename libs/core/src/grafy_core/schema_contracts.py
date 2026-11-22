import json
from collections.abc import Callable
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, StrictStr
from referencing.exceptions import Unresolvable

from grafy_core.artifacts import (
    ArtifactPreviewKind,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
)


class JsonSchemaPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictStr


JSON_SCHEMA = ArtifactTypeSpec(
    key=ArtifactTypeKey("json.schema", 1),
    title="Answer format",
    payload_schema=cast(JsonObject, JsonSchemaPayload.model_json_schema()),
    preview_kind=ArtifactPreviewKind.TEXT,
)


def parse_json_schema(
    value: str,
    *,
    context: str = "value",
) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"JSON Schema for {context} is not valid JSON at "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"JSON Schema for {context} must be a JSON object")
    schema_definition = cast(dict[str, object], parsed)
    if schema_definition.get("type") != "object":
        raise ValueError(f"JSON Schema for {context} must declare type='object' at $")
    try:
        Draft202012Validator.check_schema(schema_definition)
    except SchemaError as exc:
        raise ValueError(
            f"JSON Schema for {context} is not a valid Draft 2020-12 "
            f"schema at {exc.json_path}: {exc.message}"
        ) from exc
    return schema_definition


def validate_json_schema_value(schema: str, value: JsonObject) -> JsonObject:
    schema_definition = parse_json_schema(schema)
    validate = cast(
        Callable[[object], None],
        Draft202012Validator(schema_definition).validate,
    )
    try:
        validate(value)
    except Unresolvable as exc:
        raise ValueError(
            f"Value could not be validated against JSON Schema at reference "
            f"{exc.ref!r}: {exc}"
        ) from exc
    except JsonSchemaValidationError as exc:
        raise ValueError(
            f"Value does not match JSON Schema at {exc.json_path}: {exc.message}"
        ) from exc
    return value


__all__ = [
    "JSON_SCHEMA",
    "JsonSchemaPayload",
    "parse_json_schema",
    "validate_json_schema_value",
]
