"""Old import paths are gone: nothing re-binds names for a former owner."""

import importlib.util

import pytest
from grafy_api.v1.routes.auth import models as auth_models


@pytest.mark.parametrize(
    "module",
    [
        "grafy_api.v1.routes.saved_graphs",
        "grafy_api.v1.routes.executions",
        "grafy_api.v1.routes.modules",
        "grafy_api.graph_contracts",
        "grafy_api.execution",
    ],
)
def test_retired_modules_are_removed(module: str) -> None:
    assert importlib.util.find_spec(module) is None


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
