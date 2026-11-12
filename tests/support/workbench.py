"""Workbench dependency-override helpers shared across API tests."""

from grafy_api.services.composition import WorkbenchComponents
from grafy_api.v1.routes.artifacts.dependencies import (
    artifact_content_service,
    artifact_geo_service,
    artifact_geo_tile_service,
    artifact_table_service,
)
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.catalog.dependencies import plugin_registry
from grafy_api.v1.routes.library.dependencies import (
    library_folders_service,
    library_service,
)
from grafy_api.v1.routes.uploads.dependencies import upload_config, upload_service

from tests.support.identity import browser_actor_override
from tests.testkit import AppDependency, DependencyOverride


def workbench_dependency_overrides(
    components: WorkbenchComponents,
) -> dict[AppDependency, DependencyOverride]:
    """Map every workbench endpoint to one cohesive component graph."""

    return {
        plugin_registry: lambda: components.plugin_registry,
        upload_service: lambda: components.uploads,
        upload_config: lambda: components.upload_config,
        artifact_content_service: lambda: components.artifact_content,
        artifact_table_service: lambda: components.artifact_tables,
        artifact_geo_service: lambda: components.artifact_geo,
        artifact_geo_tile_service: lambda: components.artifact_geo_tiles,
        library_service: lambda: components.library,
        library_folders_service: lambda: components.library_folders,
        browser_actor: browser_actor_override,
        workspace_actor: browser_actor_override,
    }


__all__ = ["workbench_dependency_overrides"]
