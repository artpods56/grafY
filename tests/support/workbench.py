"""Workbench dependency-override helpers shared across API tests."""

from grafy_api.services.composition import WorkbenchComponents
from grafy_api.v1.routes.artifacts.dependencies import artifact_service
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.catalog.dependencies import (
    graph_module_executor,
    plugin_release_service,
    plugin_registry,
)
from grafy_api.v1.routes.executions.dependencies import (
    execution_admission_limiter,
    execution_history_service,
    materialization_service,
    run_execution_manager,
    run_graph_service,
    run_result_presenter,
)
from grafy_api.v1.routes.uploads.dependencies import staged_upload_service

from grafy_api.v1.routes.modules.dependencies import module_library_service

from tests.support.identity import browser_actor_override
from tests.testkit import AppDependency, DependencyOverride


def workbench_dependency_overrides(
    components: WorkbenchComponents,
) -> dict[AppDependency, DependencyOverride]:
    """Map every workbench endpoint to one cohesive component graph."""

    overrides: dict[AppDependency, DependencyOverride] = {
        plugin_registry: lambda: components.plugin_registry,
        staged_upload_service: lambda: components.uploads,
        run_graph_service: lambda: components.run_graph,
        execution_admission_limiter: lambda: components.execution_admission,
        run_execution_manager: lambda: components.execution_manager,
        execution_history_service: lambda: components.execution_history,
        materialization_service: lambda: components.materializations,
        run_result_presenter: lambda: components.presenter,
        artifact_service: lambda: components.artifacts,
        plugin_release_service: lambda: components.plugin_releases,
        graph_module_executor: lambda: components.run_graph,
        browser_actor: browser_actor_override,
        workspace_actor: browser_actor_override,
    }
    if components.module_library is not None:
        overrides[module_library_service] = lambda: components.module_library
    return overrides


__all__ = ["workbench_dependency_overrides"]
