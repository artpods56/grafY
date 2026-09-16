import json
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from grafy_client import (
    CatalogConversion,
    CatalogConversionKey,
    CatalogNode,
    CatalogPort,
    ExecutionArtifact,
    ExecutionNodeResult,
    ExecutionOutput,
    ExecutionResult,
    ExecutionState,
    NodeCatalog,
    NodeSecretStatus,
    SavedGraph,
    UploadItem,
)


def _resolve_schema_ref(
    document: dict[str, object],
    reference: str,
) -> dict[str, object]:
    if not reference.startswith("#/"):
        raise AssertionError(f"Unsupported external schema reference {reference!r}")
    components = reference.removeprefix("#/").split("/")
    resolved_mapping = document
    for index, component in enumerate(components):
        resolved = resolved_mapping[component]
        if index == len(components) - 1:
            return cast(dict[str, object], resolved)
        resolved_mapping = cast(dict[str, object], resolved)
    raise AssertionError(f"Empty schema reference {reference!r}")


def _wire_shape(
    fragment: dict[str, object],
    document: dict[str, object],
) -> tuple[object, ...]:
    reference = fragment.get("$ref")
    if isinstance(reference, str):
        return _wire_shape(_resolve_schema_ref(document, reference), document)

    any_of = fragment.get("anyOf")
    if isinstance(any_of, list):
        alternatives = {
            _wire_shape(cast(dict[str, object], alternative), document)
            for alternative in cast(list[object], any_of)
        }
        return ("union", *sorted(alternatives, key=repr))

    schema_type = fragment.get("type")
    if schema_type == "array":
        items = cast(dict[str, object], fragment["items"])
        return ("array", _wire_shape(items, document))
    if schema_type == "string":
        return ("string", fragment.get("format"))
    if isinstance(schema_type, str):
        return (schema_type,)
    return ("any",)


def _operation_json_schema_ref(
    operation: dict[str, object],
    *,
    status: str,
) -> str:
    responses = cast(dict[str, object], operation["responses"])
    response = cast(dict[str, object], responses[status])
    content = cast(dict[str, object], response["content"])
    media_type = cast(dict[str, object], content["application/json"])
    response_schema = cast(dict[str, object], media_type["schema"])
    return cast(str, response_schema["$ref"])


def _operation_request_schema_ref(
    operation: dict[str, object],
    *,
    media_type: str,
) -> str:
    request_body = cast(dict[str, object], operation["requestBody"])
    content = cast(dict[str, object], request_body["content"])
    media = cast(dict[str, object], content[media_type])
    request_schema = cast(dict[str, object], media["schema"])
    return cast(str, request_schema["$ref"])


def test_python_client_operations_match_checked_in_openapi() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    schema = cast(
        dict[str, object],
        json.loads((repo_root / "apps/web/openapi/grafy.json").read_text()),
    )
    paths = cast(dict[str, dict[str, object]], schema["paths"])

    operations = (
        (
            "/v1/workspaces/{workspace_id}/nodes",
            "get",
            None,
            "200",
            "NodeRegistryResponse",
        ),
        (
            "/v1/workspaces/{workspace_id}/uploads",
            "post",
            ("application/json", "CreateUploadRequest"),
            "201",
            "UploadTargetResponse",
        ),
        (
            "/v1/workspaces/{workspace_id}/graphs",
            "post",
            ("application/json", "CreateSavedGraphRequest"),
            "201",
            "SavedGraphResponse",
        ),
        (
            "/v1/workspaces/{workspace_id}/graphs/{graph_id}/nodes/{node_id}/"
            "secrets/{name}",
            "put",
            ("application/json", "ConfigureNodeSecretRequest"),
            "200",
            "NodeSecretStatusResponse",
        ),
        (
            "/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions",
            "post",
            ("application/json", "SavedGraphExecutionRequest"),
            "202",
            "RunExecutionResponse",
        ),
        (
            "/v1/workspaces/{workspace_id}/executions/{execution_id}",
            "get",
            None,
            "200",
            "RunExecutionResponse",
        ),
    )
    for path, method, request_contract, status, response_model in operations:
        operation = cast(dict[str, object], paths[path][method])
        security = cast(list[dict[str, object]], operation["security"])
        assert {"HTTPBearer": []} in security
        assert _operation_json_schema_ref(operation, status=status) == (
            f"#/components/schemas/{response_model}"
        )
        if request_contract is not None:
            media_type, request_model = request_contract
            assert _operation_request_schema_ref(
                operation,
                media_type=media_type,
            ) == f"#/components/schemas/{request_model}"

    components = cast(dict[str, object], schema["components"])
    models = cast(dict[str, dict[str, object]], components["schemas"])
    request_models: tuple[
        tuple[str, dict[str, tuple[object, ...]], frozenset[str]],
        ...,
    ] = (
        (
            "CreateUploadRequest",
            {
                "filename": ("string", None),
                "byte_size": ("integer",),
                "content_type": ("union", ("null",), ("string", None)),
            },
            frozenset({"filename", "byte_size"}),
        ),
        (
            "CreateSavedGraphRequest",
            {"name": ("string", None), "document": ("object",)},
            frozenset({"name", "document"}),
        ),
        (
            "ConfigureNodeSecretRequest",
            {
                "value": ("string", "password"),
                "expected_graph_revision": ("integer",),
            },
            frozenset({"value", "expected_graph_revision"}),
        ),
        (
            "SavedGraphExecutionRequest",
            {"expected_revision": ("integer",)},
            frozenset({"expected_revision"}),
        ),
    )
    for model_name, expected_properties, expected_required in request_models:
        request_schema = models[model_name]
        request_properties = cast(
            dict[str, dict[str, object]],
            request_schema["properties"],
        )
        assert set(request_properties) == set(expected_properties), model_name
        assert set(cast(list[str], request_schema.get("required", []))) == set(
            expected_required
        ), model_name
        for field_name, expected_shape in expected_properties.items():
            assert _wire_shape(request_properties[field_name], schema) == (
                expected_shape
            ), f"{model_name}.{field_name}"

    execute_operation = cast(
        dict[str, object],
        paths[
            "/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions"
        ]["post"],
    )
    execute_parameters = cast(
        list[dict[str, object]],
        execute_operation["parameters"],
    )
    idempotency_parameters = [
        parameter
        for parameter in execute_parameters
        if parameter.get("name") == "Idempotency-Key"
        and parameter.get("in") == "header"
    ]
    assert len(idempotency_parameters) == 1
    assert idempotency_parameters[0].get("required") is False
    idempotency_schema = cast(
        dict[str, object],
        idempotency_parameters[0]["schema"],
    )
    assert _wire_shape(idempotency_schema, schema) == (
        "union",
        ("null",),
        ("string", None),
    )

    wire_models: tuple[
        tuple[type[BaseModel], str, frozenset[str]],
        ...,
    ] = (
        (NodeCatalog, "NodeRegistryResponse", frozenset()),
        (CatalogNode, "NodeSpecResponse", frozenset()),
        (CatalogPort, "PortResponse", frozenset()),
        (CatalogConversion, "ArtifactConversionSpecResponse", frozenset()),
        (CatalogConversionKey, "ArtifactConversionKeyResponse", frozenset()),
        (SavedGraph, "SavedGraphResponse", frozenset()),
        (UploadItem, "ImageUploadItemResponse", frozenset()),
        (NodeSecretStatus, "NodeSecretStatusResponse", frozenset()),
        (ExecutionArtifact, "ArtifactSummaryResponse", frozenset()),
        (ExecutionOutput, "RunPortOutputResponse", frozenset({"value"})),
        (ExecutionNodeResult, "RunNodeResponse", frozenset()),
        (ExecutionResult, "RunResponse", frozenset()),
        (ExecutionState, "RunExecutionResponse", frozenset()),
    )
    for client_model, openapi_name, opaque_fields in wire_models:
        client_schema = cast(
            dict[str, object],
            client_model.model_json_schema(),
        )
        openapi_schema = models[openapi_name]
        client_properties = cast(
            dict[str, dict[str, object]],
            client_schema["properties"],
        )
        openapi_properties = cast(
            dict[str, dict[str, object]],
            openapi_schema["properties"],
        )
        assert set(client_properties) == set(openapi_properties), openapi_name
        assert set(cast(list[str], client_schema.get("required", []))) == set(
            cast(list[str], openapi_schema.get("required", []))
        ), openapi_name
        for field_name in client_properties.keys() - opaque_fields:
            assert _wire_shape(
                client_properties[field_name],
                client_schema,
            ) == _wire_shape(
                openapi_properties[field_name],
                schema,
            ), f"{openapi_name}.{field_name}"
