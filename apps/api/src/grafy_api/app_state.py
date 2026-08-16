"""Typed FastAPI application state for identity and workbench resources."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.agent_authoring import AgentAuthoringService
from grafy_core.application.identity import IdentityService
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.application.templates import TemplateService
from grafy_core.plugins import PluginRegistry
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.settings import Settings
from grafy_api.v1.routes.agent_authoring.services import BuildReviewService
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.auth.services import AuthService
from grafy_api.v1.routes.catalog.services import GraphModuleCatalog
from grafy_api.v1.routes.collaboration.hub import GraphRoomHub
from grafy_api.v1.routes.executions.runtime.admission import (
    ExecutionAdmissionLimiter,
)
from grafy_api.v1.routes.executions.runtime.manager import RunExecutionManager
from grafy_api.v1.routes.executions.runtime.generated_executor import (
    GeneratedNodeExecutorClient,
)
from grafy_api.v1.routes.executions.runtime.run_graph import RunGraph
from grafy_api.v1.routes.executions.services import (
    ExecutionHistoryService,
    MaterializationService,
    RunResultPresenter,
)
from grafy_api.v1.routes.node_secrets.services import NodeSecretService
from grafy_api.v1.routes.uploads.services import ImageUploadService


@dataclass(slots=True)
class AppIdentity:
    """Auth and workspace-identity services attached for the app lifetime."""

    identity_uow_factory: Callable[[], SqlAlchemyUnitOfWork]
    identity_service: IdentityService
    auth_service: AuthService


@dataclass(slots=True)
class AppResources:
    """Application resources constructed during API lifespan and torn down once."""

    database: Database
    agent_authoring: AgentAuthoringService
    build_review: BuildReviewService
    plugin_registry: PluginRegistry
    uploads: ImageUploadService
    graph_modules: GraphModuleCatalog
    module_library: ModuleLibraryService
    templates: TemplateService
    run_graph: RunGraph
    execution_admission: ExecutionAdmissionLimiter
    execution_manager: RunExecutionManager
    execution_history: ExecutionHistoryService
    materializations: MaterializationService
    presenter: RunResultPresenter
    artifacts: ArtifactService
    saved_graphs: SavedGraphService
    collaboration: CollaborationService
    node_secrets: NodeSecretService
    graph_room_hub: GraphRoomHub
    generated_executor: GeneratedNodeExecutorClient | None

    async def cleanup(self) -> None:
        await self.graph_room_hub.shutdown()
        await self.execution_manager.shutdown()
        await self.artifacts.close()
        if self.generated_executor is not None:
            await self.generated_executor.close()


def get_identity(app: FastAPI) -> AppIdentity:
    identity = getattr(app.state, "identity", None)
    if not isinstance(identity, AppIdentity):
        raise RuntimeError("Application identity services are not initialized")
    return identity


def get_resources(app: FastAPI) -> AppResources:
    resources = getattr(app.state, "resources", None)
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are not initialized")
    return resources


def get_app_settings(app: FastAPI) -> Settings:
    settings = getattr(app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings are not initialized")
    return settings
