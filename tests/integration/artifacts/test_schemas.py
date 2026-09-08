import json
from typing import cast

from fastapi.testclient import TestClient

from grafy_api.execution.requests import (
    RunEdgeRequest,
    RunInputPlugRequest,
    RunRequest,
)
from grafy_api.v1.routes.executions.models import RunResponse
from tests.support.system_plugins import selected_system_run_node as RunNodeRequest

from tests.support.clients import GrafyApi
from tests.support.identity import WORKSPACE_ID


def test_schema_builders_compose_nested_objects_and_sequence_items_by_plug(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    response = api.workspace(WORKSPACE_ID).executions.run(
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="supplier-schema",
                    operator_id="schema.builder",
                    operator_version=1,
                    config={
                        "title": "Supplier",
                        "fields": [
                            {
                                "id": "supplier-name",
                                "name": "name",
                                "kind": "string",
                                "required": True,
                                "description": "Legal supplier name",
                            }
                        ],
                    },
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="line-schema",
                    operator_id="schema.builder",
                    operator_version=1,
                    config={
                        "title": "Line item",
                        "fields": [
                            {
                                "id": "line-sku",
                                "name": "sku",
                                "kind": "string",
                                "required": True,
                                "description": "",
                            },
                            {
                                "id": "line-quantity",
                                "name": "quantity",
                                "kind": "integer",
                                "required": True,
                                "description": "",
                            },
                        ],
                    },
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="invoice-schema",
                    operator_id="schema.builder",
                    operator_version=1,
                    config={
                        "title": "Invoice",
                        "description": "Structured invoice extraction",
                        "additional_properties": False,
                        "fields": [
                            {
                                "id": "invoice-number",
                                "name": "number",
                                "kind": "string",
                                "required": True,
                                "description": "Invoice identifier",
                            },
                            {
                                "id": "line-items",
                                "name": "line_items",
                                "kind": "sequence",
                                "item_kind": "schema",
                                "required": True,
                                "description": "Ordered invoice lines",
                            },
                            {
                                "id": "supplier",
                                "name": "supplier",
                                "kind": "schema",
                                "required": True,
                                "description": "Invoice issuer",
                            },
                            {
                                "id": "tags",
                                "name": "tags",
                                "kind": "sequence",
                                "item_kind": "string",
                                "required": False,
                                "description": "",
                            },
                        ],
                    },
                    input_plugs=[
                        RunInputPlugRequest(id="line-items", port="schemas"),
                        RunInputPlugRequest(id="supplier", port="schemas"),
                    ],
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="supplier-schema",
                    from_port="json_schema",
                    to_node="invoice-schema",
                    to_port="schemas",
                    to_plug="supplier",
                ),
                RunEdgeRequest(
                    from_node="line-schema",
                    from_port="json_schema",
                    to_node="invoice-schema",
                    to_port="schemas",
                    to_plug="line-items",
                ),
            ],
        )
    )

    assert response.status_code == 200, response.text
    result = RunResponse.model_validate(response.json())
    assert result.status == "succeeded"
    invoice_run = next(
        node_run
        for node_run in result.node_runs
        if node_run.node_id == "invoice-schema"
    )
    schema_ref = invoice_run.outputs[0].artifacts[0]
    stored_payload = artifacts.content(schema_ref.artifact_id).json()
    schema = cast(dict[str, object], json.loads(stored_payload["value"]))

    assert schema["title"] == "Invoice"
    assert schema["description"] == "Structured invoice extraction"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["number", "line_items", "supplier"]
    properties = cast(dict[str, object], schema["properties"])
    assert properties["number"] == {
        "type": "string",
        "description": "Invoice identifier",
    }
    assert properties["tags"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    line_items = cast(dict[str, object], properties["line_items"])
    assert line_items["type"] == "array"
    assert line_items["description"] == "Ordered invoice lines"
    assert cast(dict[str, object], line_items["items"])["title"] == "Line item"
    supplier = cast(dict[str, object], properties["supplier"])
    assert supplier["title"] == "Supplier"
    assert supplier["description"] == "Invoice issuer"
    assert cast(dict[str, object], supplier["properties"])["name"] == {
        "type": "string",
        "description": "Legal supplier name",
    }


def test_schema_builder_requires_one_connection_for_each_nested_field_plug(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    response = api.workspace(WORKSPACE_ID).executions.run(
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="parent",
                    operator_id="schema.builder",
                    operator_version=1,
                    config={
                        "fields": [
                            {
                                "id": "nested",
                                "name": "nested",
                                "kind": "schema",
                                "required": False,
                                "description": "",
                            }
                        ]
                    },
                    input_plugs=[RunInputPlugRequest(id="nested", port="schemas")],
                )
            ],
            edges=[],
        )
    )

    assert response.status_code == 422
    assert "input plug 'nested' requires exactly one incoming edge" in response.text
