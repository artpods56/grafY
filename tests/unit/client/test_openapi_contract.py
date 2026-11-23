import json
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from grafy_client import (
    CatalogConversion,
    CatalogConversionKey,
    CatalogNode,
    CatalogPack,
    CatalogPort,
    CommandReceipt,
    GeoFeatureMatch,
    GeoRender,
    InstanceKey,
    InstanceResult,
    InstanceState,
    NodeCatalog,
    NodeSecretStatus,
    Project,
    ProjectHead,
    ProjectSummary,
    Run,
    TableCell,
    TableColumn,
    TablePage,
    TableSchema,
    UploadItem,
    UploadTarget,
    Workspace,
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

    base = "/v1/workspaces/{workspace_id}/projects"
    run_base = base + "/{project_id}/runs"
    artifacts = "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}"
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
            base,
            "post",
            ("application/json", "CreateProjectRequest"),
            "201",
            "ProjectResponse",
        ),
        (base, "get", None, "200", "ProjectListResponse"),
        (
            "/v1/workspaces/{workspace_id}/uploads/{upload_id}/complete",
            "post",
            None,
            "200",
            "ImageUploadItemResponse",
        ),
        (artifacts + "/table/schema", "get", None, "200", "TableSchemaResponse"),
        (artifacts + "/table/page", "get", None, "200", "TablePageResponse"),
        (
            artifacts + "/table/query",
            "post",
            ("application/json", "TableQueryRequest"),
            "200",
            "TablePageResponse",
        ),
        (artifacts + "/geo/render", "get", None, "200", "GeoRenderResponse"),
        (
            artifacts + "/geo/query",
            "post",
            ("application/json", "GeoFeatureQueryRequest"),
            "200",
            "GeoFeatureQueryResponse",
        ),
        (
            "/v1/workspaces/{workspace_id}/library/artifacts",
            "get",
            None,
            "200",
            "LibraryListResponse",
        ),
        (base + "/{project_id}", "get", None, "200", "ProjectResponse"),
        (base + "/{project_id}/head", "get", None, "200", "ProjectHeadResponse"),
        (
            base + "/{project_id}/commands",
            "post",
            ("application/json", "SubmitProjectCommandRequest"),
            "200",
            "SubmitProjectCommandResponse",
        ),
        (
            base + "/{project_id}/checkpoints",
            "post",
            ("application/json", "CheckpointProjectRequest"),
            "200",
            "CheckpointProjectResponse",
        ),
        (
            base + "/{project_id}/graphs/{graph_id}/nodes/{node_id}/secrets/{name}",
            "put",
            ("application/json", "ConfigureNodeSecretRequest"),
            "200",
            "ConfigureNodeSecretResponse",
        ),
        (
            run_base,
            "post",
            ("application/json", "StartRunRequest"),
            "201",
            "RunResponse",
        ),
        (run_base + "/{run_id}", "get", None, "200", "RunResponse"),
        (run_base + "/{run_id}/cancel", "post", None, "200", "RunResponse"),
        (run_base, "get", None, "200", "RunListResponse"),
        (
            base + "/{project_id}/graphs/{graph_id}/instances",
            "get",
            None,
            "200",
            "InstanceStateListResponse",
        ),
        (
            base + "/{project_id}/instance-result",
            "get",
            None,
            "200",
            "InstanceResultResponse",
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
            assert (
                _operation_request_schema_ref(
                    operation,
                    media_type=media_type,
                )
                == f"#/components/schemas/{request_model}"
            )

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
            "ConfigureNodeSecretRequest",
            {"value": ("string", "password"), "expected_head_sequence": ("integer",)},
            frozenset({"value", "expected_head_sequence"}),
        ),
        (
            "StartRunRequest",
            {"graph_id": ("string", None), "targets": ("array", ("object",))},
            frozenset({"graph_id"}),
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

    wire_models: tuple[
        tuple[type[BaseModel], str, frozenset[str]],
        ...,
    ] = (
        (NodeCatalog, "NodeRegistryResponse", frozenset()),
        (CatalogNode, "NodeSpecResponse", frozenset()),
        (CatalogPack, "CatalogPackResponse", frozenset()),
        (CatalogPort, "PortResponse", frozenset()),
        (CatalogConversion, "ArtifactConversionSpecResponse", frozenset()),
        (CatalogConversionKey, "ArtifactConversionKeyResponse", frozenset()),
        (Project, "ProjectResponse", frozenset()),
        (ProjectHead, "ProjectHeadResponse", frozenset({"document"})),
        (CommandReceipt, "ProjectCommandReceiptResponse", frozenset()),
        (UploadItem, "ImageUploadItemResponse", frozenset()),
        (NodeSecretStatus, "ConfigureNodeSecretResponse", frozenset()),
        (Run, "RunResponse", frozenset()),
        (InstanceKey, "InstanceKeyResponse", frozenset()),
        (InstanceState, "InstanceStateResponse", frozenset()),
        (InstanceResult, "InstanceResultResponse", frozenset({"outputs"})),
        (Workspace, "WorkspaceResponse", frozenset()),
        (ProjectSummary, "ProjectSummaryResponse", frozenset()),
        # One client model reads both target kinds; the storage kind only makes
        # `headers` required, which the client defaults to empty.
        (UploadTarget, "ApiUploadTargetResponse", frozenset()),
        (TableColumn, "TableColumnResponse", frozenset()),
        (TableSchema, "TableSchemaResponse", frozenset()),
        (TableCell, "TableCellPreviewResponse", frozenset()),
        (TablePage, "TablePageResponse", frozenset({"rows"})),
        (GeoRender, "GeoRenderResponse", frozenset({"initial_bounds", "layers"})),
        (GeoFeatureMatch, "GeoFeatureQueryResponse", frozenset({"bounds"})),
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



def test_client_decodes_the_catalogs_ocr_feature_contracts() -> None:
    from grafy_api.catalog import CatalogSnapshot
    from grafy_api.catalog_packs import CatalogPolicy
    from grafy_shared.config.catalog import CatalogOverrides
    from grafy_api.services.families import build_application_registry
    from grafy_api.v1.routes.catalog.models import NodeRegistryResponse

    registry = build_application_registry()
    snapshot = CatalogSnapshot.from_registry(registry)
    policy = CatalogPolicy(registry, CatalogOverrides())
    response = NodeRegistryResponse.from_snapshot(
        snapshot, policy, frozenset(policy.default_workspace_pack_slugs)
    )
    catalog = NodeCatalog.model_validate_json(response.model_dump_json())
    nodes = {node.operator_id: node for node in catalog.nodes}
    ocr = nodes["ocr.read_document"]
    assert ocr.role == "operator"
    assert ocr.pack_slugs == ("document_ocr",)
    assert catalog.packs[1].slug == "document_ocr"
    assert catalog.packs[1].provider_count == 2
    engine = next(port for port in ocr.inputs if port.name == "engine")
    (contract,) = engine.service_contracts
    assert (contract.id, contract.version) == ("ocr.document", 1)

    regions = next(port for port in ocr.outputs if port.name == "regions")
    requirement = regions.requires_service_feature
    assert requirement is not None
    assert (requirement.input_port, requirement.feature) == ("engine", "regions")

    reducto = nodes["reducto.ocr.provider"]
    assert reducto.role == "provider"
    (output,) = reducto.outputs
    assert output.name == "engine"
    (declaration,) = output.service_features
    assert declaration.contract == contract
    assert declaration.features == ("blocks",)
