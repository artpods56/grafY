from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from grafy_api.main import app


def test_public_routes_are_registered_once() -> None:
    operations = [
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/v1")
        for method in route.methods
    ]

    assert len(operations) == len(set(operations))


def test_openapi_contains_exact_public_routes() -> None:
    schema = app.openapi()

    assert set(schema["paths"]) == {
        "/v1/me/graphs",
        "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/content",
        "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/download",
        "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/geo/query",
        "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/geo/render",
        "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/table/cell",
        "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/table/page",
        "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/table/query",
        "/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/table/schema",
        "/v1/workspaces/{workspace_id}/artifacts/{source_id}/geo/features/{feature_index}",
        "/v1/workspaces/{workspace_id}/artifacts/{source_id}/geo/raster/tilejson.json",
        "/v1/workspaces/{workspace_id}/artifacts/{source_id}/geo/raster/{z}/{x}/{y}.png",
        "/v1/workspaces/{workspace_id}/artifacts/{source_id}/geo/vector.pmtiles",
        "/v1/workspaces/{workspace_id}/agent-authoring/builds/{build_attempt_id}/approval",
        "/v1/workspaces/{workspace_id}/agent-authoring/builds/{build_attempt_id}/publish",
        "/v1/workspaces/{workspace_id}/agent-authoring/builds/{build_attempt_id}/review",
        "/v1/workspaces/{workspace_id}/agent-authoring/builds/{build_attempt_id}/review/files/{file_path}",
        "/v1/workspaces/{workspace_id}/agent-authoring/drafts/{draft_node_id}",
        "/v1/workspaces/{workspace_id}/agent-authoring/environments",
        "/v1/workspaces/{workspace_id}/agent-authoring/graphs/{graph_id}/drafts",
        "/v1/workspaces/{workspace_id}/agent-authoring/runs/{run_id}",
        "/v1/workspaces/{workspace_id}/agent-authoring/runs/{run_id}/events",
        "/v1/workspaces/{workspace_id}/agent-authoring/threads/{thread_id}/runs",
        "/v1/workspaces/{workspace_id}/executions",
        "/v1/workspaces/{workspace_id}/executions/{execution_id}",
        "/v1/workspaces/{workspace_id}/executions/{execution_id}/events",
        "/v1/workspaces/{workspace_id}/graph-folders",
        "/v1/workspaces/{workspace_id}/graph-folders/{folder_id}",
        "/v1/workspaces/{workspace_id}/graphs",
        "/v1/workspaces/{workspace_id}/graphs/copies",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/archive",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/checkpoint",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/commands",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions/{execution_id}",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/folder",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/head",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/materializations",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/node-secrets",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/nodes/{node_id}/secrets/{name}",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/opened",
        "/v1/workspaces/{workspace_id}/graphs/{graph_id}/star",
        "/v1/workspaces/{workspace_id}/modules",
        "/v1/workspaces/{workspace_id}/modules/import",
        "/v1/workspaces/{workspace_id}/modules/publish",
        "/v1/workspaces/{workspace_id}/modules/{module_id}",
        "/v1/workspaces/{workspace_id}/modules/{module_id}/deprecate",
        "/v1/workspaces/{workspace_id}/modules/{module_id}/withdraw",
        "/v1/workspaces/{workspace_id}/templates",
        "/v1/workspaces/{workspace_id}/templates/{template_id}",
        "/v1/workspaces/{workspace_id}/templates/{template_id}/archive",
        "/v1/workspaces/{workspace_id}/templates/{template_id}/instantiate",
        "/v1/workspaces/{workspace_id}/nodes",
        "/v1/workspaces/{workspace_id}/runs",
        "/v1/workspaces/{workspace_id}/samples",
        "/v1/workspaces/{workspace_id}/uploads",
        "/v1/auth/oidc/login",
        "/v1/auth/oidc/callback",
        "/v1/auth/session",
        "/v1/auth/sessions",
        "/v1/auth/sessions/{session_id}",
        "/v1/workspaces",
        "/v1/workspaces/{workspace_id}/members",
        "/v1/workspaces/{workspace_id}/members/{user_id}",
        "/v1/workspaces/{workspace_id}/personal-access-tokens",
        "/v1/workspaces/{workspace_id}/personal-access-tokens/{token_id}",
    }
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/graphs"]) == {"get", "post"}
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/graphs/copies"]) == {"post"}
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}/head"]) == {
        "get"
    }
    assert set(
        schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}/commands"]
    ) == {"post"}
    assert set(
        schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}/checkpoint"]
    ) == {"post"}
    assert set(
        schema["paths"][
            "/v1/workspaces/{workspace_id}/agent-authoring/environments"
        ]
    ) == {"get", "post"}
    assert set(
        schema["paths"][
            "/v1/workspaces/{workspace_id}/agent-authoring/graphs/{graph_id}/drafts"
        ]
    ) == {"post"}
    assert set(
        schema["paths"][
            "/v1/workspaces/{workspace_id}/agent-authoring/runs/{run_id}"
        ]
    ) == {"delete", "get"}
    event_stream_response = schema["paths"][
        "/v1/workspaces/{workspace_id}/agent-authoring/runs/{run_id}/events"
    ]["get"]["responses"]["200"]
    assert event_stream_response["content"] == {
        "text/event-stream": {"schema": {"type": "string"}}
    }
    event_stream_parameters = schema["paths"][
        "/v1/workspaces/{workspace_id}/agent-authoring/runs/{run_id}/events"
    ]["get"]["parameters"]
    assert any(
        parameter["in"] == "query" and parameter["name"] == "after_sequence"
        for parameter in event_stream_parameters
    )
    assert schema["paths"][
        "/v1/workspaces/{workspace_id}/agent-authoring/drafts/{draft_node_id}"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgentDraftDetailResponse"
    }
    assert schema["paths"][
        "/v1/workspaces/{workspace_id}/agent-authoring/threads/{thread_id}/runs"
    ]["post"]["responses"]["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgentFollowUpRunResponse"
    }
    assert schema["paths"][
        "/v1/workspaces/{workspace_id}/agent-authoring/builds/{build_attempt_id}/review"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BuildReviewResponse"
    }
    assert schema["components"]["schemas"]["PublishBuildRequest"][
        "required"
    ] == ["capability_approval_id"]
    assert schema["components"]["schemas"]["PublishBuildRequest"]["properties"][
        "graph_promotion"
    ]["anyOf"][0] == {"$ref": "#/components/schemas/PublishGraphPromotionRequest"}
    assert {"head", "receipt"}.issubset(
        schema["components"]["schemas"]["PublishBuildResponse"]["properties"]
    )
    assert "capability_approval_id" in schema["components"]["schemas"][
        "NodeReleaseResponse"
    ]["required"]
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/executions"]) == {"post"}
    synchronous_run_responses = schema["paths"][
        "/v1/workspaces/{workspace_id}/runs"
    ]["post"]["responses"]
    assert synchronous_run_responses["429"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/RunExecutionCapacityErrorResponse"}
    assert "Retry-After" in synchronous_run_responses["429"]["headers"]
    execution_start_responses = schema["paths"][
        "/v1/workspaces/{workspace_id}/executions"
    ]["post"]["responses"]
    assert execution_start_responses["429"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/RunExecutionCapacityErrorResponse"}
    assert "Retry-After" in execution_start_responses["429"]["headers"]
    security_schemes = schema["components"]["securitySchemes"]
    session_scheme_name = next(
        name
        for name, scheme in security_schemes.items()
        if scheme
        == {
            "type": "apiKey",
            "in": "cookie",
            "name": "grafy_session",
            "description": "Opaque host-only browser session cookie.",
        }
    )
    assert schema["paths"]["/v1/auth/oidc/login"]["get"].get("security") is None
    assert schema["paths"]["/v1/auth/oidc/callback"]["get"].get("security") is None
    assert schema["paths"]["/v1/auth/session"]["get"]["security"] == [
        {session_scheme_name: []}
    ]
    assert schema["paths"]["/v1/workspaces"]["get"]["security"] == [
        {session_scheme_name: []}
    ]
    pat_schema = schema["components"]["schemas"]["PersonalAccessTokenCreatedResponse"]
    assert "returned once" in pat_schema["properties"]["token"]["description"]
    pat_request_schema = schema["components"]["schemas"][
        "PersonalAccessTokenCreateRequest"
    ]
    pat_scope_schema = schema["components"]["schemas"]["PersonalAccessTokenScope"]
    assert set(pat_scope_schema["enum"]) == {
        "view_graph",
        "view_artifacts",
        "view_materializations",
        "view_history",
        "view_execution",
        "create_graph",
        "edit_graph",
        "checkpoint_graph",
        "execute_graph",
        "cancel_execution",
        "publish_module",
    }
    assert pat_request_schema["properties"]["scopes"]["items"] == {
        "$ref": "#/components/schemas/PersonalAccessTokenScope"
    }
    assert "manage_members" not in pat_scope_schema["enum"]
    assert "manage_secrets" not in pat_scope_schema["enum"]
    assert "manage_module_library" not in pat_scope_schema["enum"]
    assert "rename_workspace" not in pat_scope_schema["enum"]

    assert "GeoPageResponse" not in schema["components"]["schemas"]
    geo_render_schema = schema["components"]["schemas"]["GeoRenderResponse"]
    assert set(geo_render_schema["properties"]) == {
        "artifact_id",
        "kind",
        "basemap",
        "initial_bounds",
        "layers",
    }
    assert geo_render_schema["properties"]["layers"]["items"] == {
        "$ref": "#/components/schemas/GeoRenderLayerResponse"
    }
    raster_tilejson_schema = schema["components"]["schemas"][
        "GeoRasterTileJsonResponse"
    ]
    assert set(raster_tilejson_schema["properties"]) == {
        "tilejson",
        "name",
        "tiles",
        "bounds",
        "minzoom",
        "maxzoom",
        "attribution",
        "scheme",
    }
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/executions/{execution_id}"]) == {
        "delete",
        "get",
    }
    execution_schema = schema["components"]["schemas"]["RunExecutionResponse"]
    assert set(execution_schema["properties"]) == {
        "execution_id",
        "status",
        "active_node_id",
        "result",
        "error",
    }
    assert execution_schema["properties"]["status"]["enum"] == [
        "queued",
        "running",
        "cancelling",
        "cancelled",
        "succeeded",
        "failed",
    ]
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}"]) == {
        "delete",
        "get",
        "put",
    }
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}/materializations"]) == {"get"}
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions"]) == {"get"}
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions/{execution_id}"]) == {
        "get"
    }
    history_summary = schema["components"]["schemas"]["GraphExecutionSummaryResponse"]
    assert set(history_summary["properties"]) == {
        "execution_id",
        "graph_id",
        "graph_revision",
        "scope",
        "status",
        "requested_node_ids",
        "node_count",
        "artifact_count",
        "created_at",
        "started_at",
        "finished_at",
        "workflow_run_id",
        "error",
    }
    assert set(schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}/node-secrets"]) == {"get"}
    assert set(
        schema["paths"]["/v1/workspaces/{workspace_id}/graphs/{graph_id}/nodes/{node_id}/secrets/{name}"]
    ) == {"delete", "put"}
    node_schema = schema["components"]["schemas"]["NodeSpecResponse"]
    assert "config_schema" in node_schema["properties"]
    assert "supported_invocation_modes" not in node_schema["properties"]
    assert "map_inputs" not in node_schema["properties"]

    plugin_schema = schema["components"]["schemas"]["PluginSpecResponse"]
    assert plugin_schema["properties"]["origin"] == {
        "$ref": "#/components/schemas/PluginOrigin"
    }
    assert set(plugin_schema["required"]) == {"slug", "title", "origin"}
    assert schema["components"]["schemas"]["PluginOrigin"] == {
        "enum": ["agent", "builtin", "external", "module"],
        "title": "PluginOrigin",
        "type": "string",
    }
    assert "module_graph_id" in node_schema["properties"]
    assert "module_graph_revision" in node_schema["properties"]
    assert node_schema["properties"]["catalog_visible"] == {
        "default": True,
        "title": "Catalog Visible",
        "type": "boolean",
    }
    assert schema["components"]["schemas"]["ImageUploadItemResponse"] == {
        "properties": {
            "upload_key": {
                "title": "Upload Key",
                "type": "string",
            },
            "filename": {
                "title": "Filename",
                "type": "string",
            },
            "byte_size": {
                "title": "Byte Size",
                "type": "integer",
            },
        },
        "required": ["upload_key", "filename", "byte_size"],
        "title": "ImageUploadItemResponse",
        "type": "object",
    }

    port_schema = schema["components"]["schemas"]["PortResponse"]
    assert "title" in port_schema["properties"]
    assert "description" in port_schema["properties"]
    assert port_schema["properties"]["accepted_shapes"]["items"] == {
        "$ref": "#/components/schemas/PortShape"
    }
    assert port_schema["properties"]["instance_plugs"] == {
        "default": False,
        "title": "Instance Plugs",
        "type": "boolean",
    }
    assert port_schema["properties"]["artifact_type"]["anyOf"] == [
        {"$ref": "#/components/schemas/ArtifactTypeKeyResponse"},
        {"type": "null"},
    ]
    assert port_schema["properties"]["artifact_type_variable"]["anyOf"] == [
        {"type": "string", "minLength": 1, "maxLength": 255},
        {"type": "null"},
    ]

    run_node_schema = schema["components"]["schemas"]["RunNodeRequest"]
    assert set(run_node_schema["required"]) == {
        "id",
        "operator_id",
        "operator_version",
    }
    assert run_node_schema["properties"]["input_plugs"]["items"] == {
        "$ref": "#/components/schemas/RunInputPlugRequest"
    }
    assert run_node_schema["properties"]["artifact_type_bindings"]["items"] == {
        "$ref": "#/components/schemas/ArtifactTypeBindingModel"
    }
    run_edge_schema = schema["components"]["schemas"]["RunEdgeRequest"]
    assert "enabled" not in run_edge_schema["properties"]
    assert run_edge_schema["properties"]["collection_mode"] == {
        "default": "direct",
        "enum": ["direct", "map"],
        "title": "Collection Mode",
        "type": "string",
    }
    assert run_edge_schema["properties"]["to_plug"]["anyOf"] == [
        {"type": "string", "minLength": 1, "maxLength": 255},
        {"type": "null"},
    ]

    saved_node_schema = schema["components"]["schemas"]["SavedGraphNodeModel"]
    assert saved_node_schema["properties"]["input_plugs"]["items"] == {
        "$ref": "#/components/schemas/SavedGraphInputPlugModel"
    }
    assert saved_node_schema["properties"]["artifact_type_bindings"]["items"] == {
        "$ref": "#/components/schemas/ArtifactTypeBindingModel"
    }
    saved_edge_schema = schema["components"]["schemas"]["SavedGraphEdgeModel"]
    assert "to_plug" in saved_edge_schema["properties"]
    assert saved_edge_schema["properties"]["enabled"]["default"] is True


def test_app_health_is_ok() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_allows_local_web_origin() -> None:
    response = TestClient(app).options(
        "/v1/workspaces/{workspace_id}/nodes",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ("http://localhost:3000")


def test_framework_documentation_routes_are_disabled_but_openapi_is_callable() -> None:
    assert {
        route.path for route in app.routes if isinstance(route, APIRoute)
    }.isdisjoint({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})
    schema = app.openapi()
    assert schema["openapi"].startswith("3.")
