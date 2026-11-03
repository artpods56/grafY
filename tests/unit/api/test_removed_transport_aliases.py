"""Old import paths are gone: nothing re-binds names for a former owner.

The Project replaced the saved graph, and the Run replaced graph execution. A route
or contract that still answered to the old name would let two vocabularies describe
one thing, so this is the test that fails when someone adds an alias back.
"""

import importlib.util

import pytest
from grafy_api import project_contracts
from grafy_api.v1.routes import node_secrets as node_secret_routes
from grafy_api.v1.routes.projects import views as project_views
from grafy_core.application import projects as project_application

REMOVED_MODULES = (
    # The saved graph, and the graph-keyed surfaces that hung off it.
    "grafy_api.graph_contracts",
    "grafy_api.v1.routes.saved_graphs",
    "grafy_api.v1.routes.saved_graphs.views",
    "grafy_api.v1.routes.collaboration.models",
    "grafy_core.application.saved_graphs",
    "grafy_core.application.graph_creation",
    # Graph execution, Modules and the materialization cache: a Run reads a
    # checkpoint now, so none of these own a route or a request model any more.
    "grafy_api.execution.requests",
    "grafy_api.v1.routes.executions",
    "grafy_api.v1.routes.executions.models",
    "grafy_api.v1.routes.modules",
    "grafy_api.v1.routes.modules.models",
)


def _spec(module: str) -> object | None:
    """The spec of a module whose parents may themselves be gone."""

    try:
        return importlib.util.find_spec(module)
    except ModuleNotFoundError:
        return None


@pytest.mark.parametrize("module", REMOVED_MODULES)
def test_retired_import_paths_are_not_rebonded(module: str) -> None:
    assert _spec(module) is None


def test_the_project_contracts_and_routes_are_the_only_owners() -> None:
    assert project_contracts.ProjectResponse.__name__ == "ProjectResponse"
    assert project_application.ProjectService.__name__ == "ProjectService"
    assert node_secret_routes.__name__ == "grafy_api.v1.routes.node_secrets"


def test_no_saved_graph_name_survives_in_the_project_surface() -> None:
    """The vocabulary is renamed, not aliased: no `graph` field in a Project contract.

    A Graph is still a thing a Project holds — ``AddGraphCommand`` and the ``graphs``
    of a document keep those names — but no Project contract carries a *saved graph*.
    """

    contract_names = set(vars(project_contracts))
    assert not [name for name in contract_names if "SavedGraph" in name]
    route_names = set(vars(project_views))
    assert not [name for name in route_names if "Saved" in name]
    assert "saved_graph" not in project_views.router.prefix


def test_the_project_router_is_the_only_door_to_a_project_document() -> None:
    paths = {route.path for route in project_views.router.routes}

    assert all("/graphs/{graph_id}/head" not in path for path in paths)
    assert "/workspaces/{workspace_id}/projects/{project_id}/head" in paths
