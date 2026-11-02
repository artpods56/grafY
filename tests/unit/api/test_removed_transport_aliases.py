"""Old import paths are gone: nothing re-binds names for a former owner."""

import importlib.util

import pytest
from grafy_api.execution.requests import RunEdgeRequest, RunRequest
from grafy_api.v1.routes.auth import models as auth_models
from grafy_api.v1.routes.executions import models as execution_route_models


@pytest.mark.parametrize(
    "module",
    [
        "grafy_api.v1.routes.saved_graphs.models",
        "grafy_api.v1.routes.collaboration.models",
    ],
)
def test_compatibility_export_modules_are_removed(module: str) -> None:
    assert importlib.util.find_spec(module) is None


@pytest.mark.parametrize(
    "name",
    [
        "RunRequest",
        "RunNodeRequest",
        "RunEdgeRequest",
        "RunOriginRequest",
        "RunExecutionEvent",
        "NodeStatusEvent",
        "RunExecutionStatus",
    ],
)
def test_http_models_do_not_re_export_execution_owners(name: str) -> None:
    assert not hasattr(execution_route_models, name)
    assert name not in execution_route_models.__all__


@pytest.mark.parametrize(
    "name",
    [
        "WorkspaceResponse",
        "WorkspaceMemberResponse",
        "PersonalAccessTokenResponse",
        "PersonalAccessTokenScope",
        "UserResponse",
    ],
)
def test_auth_models_do_not_re_export_workspace_owners(name: str) -> None:
    assert not hasattr(auth_models, name)


def test_run_edge_has_no_singular_conversion_field() -> None:
    assert "conversion" not in RunEdgeRequest.model_fields


def test_run_node_has_no_plugin_identity_field() -> None:
    assert "plugin_release" not in RunRequest.model_fields
    assert "plugin_release_pin" not in RunRequest.model_fields
