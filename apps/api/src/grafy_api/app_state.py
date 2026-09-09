"""Typed FastAPI application state for identity and workbench resources."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.identity import IdentityService
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.application.templates import TemplateService
from grafy_core.plugins import PluginRegistry
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.plugins.runtime.admission import ReleaseExecutionAdmission
from grafy_api.settings import Settings
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.auth.services import AuthService
from grafy_api.realtime.hub import GraphRoomHub
from grafy_api.execution.admission import (
    ExecutionAdmissionDiagnostics,
    ExecutionAdmissionLimiter,
)
from grafy_api.execution.manager import (
    RunExecutionManager,
    RunExecutionQueueDiagnostics,
)
from grafy_api.plugins.runtime.artifacts import (
    ArtifactBundlePluginInvoker,
    PluginInvocationCapacityDiagnostics,
)
from grafy_api.plugins.runtime.docker import (
    DockerPluginRuntime,
    PluginSandboxCapacityDiagnostics,
)
from grafy_api.execution.run_graph import RunGraph
from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.materializations import MaterializationService
from grafy_api.v1.routes.executions.services import RunResultPresenter
from grafy_api.node_secrets import NodeSecretService
from grafy_api.staged_uploads import StagedUploadService


@dataclass(slots=True)
class AppIdentity:
    """Auth and workspace-identity services attached for the app lifetime."""

    identity_uow_factory: Callable[[], SqlAlchemyUnitOfWork]
    identity_service: IdentityService
    auth_service: AuthService


@dataclass(frozen=True, slots=True)
class CapacityDiagnostics:
    captured_at: datetime
    execution_admission: ExecutionAdmissionDiagnostics
    execution_queue: RunExecutionQueueDiagnostics
    plugin_invocations: PluginInvocationCapacityDiagnostics | None
    plugin_sandboxes: PluginSandboxCapacityDiagnostics | None


@dataclass(slots=True)
class AppResources:
    """Application resources constructed during API lifespan and torn down once."""

    database: Database
    plugin_registry: PluginRegistry
    uploads: StagedUploadService
    plugin_releases: PluginReleaseService | None
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
    plugin_invoker: ArtifactBundlePluginInvoker | None
    plugin_runtime: DockerPluginRuntime | None
    release_admission: ReleaseExecutionAdmission | None

    async def capacity_diagnostics(self) -> CapacityDiagnostics:
        return CapacityDiagnostics(
            captured_at=datetime.now(UTC),
            execution_admission=self.execution_admission.diagnostics(),
            execution_queue=await self.execution_manager.diagnostics(),
            plugin_invocations=(
                None
                if self.plugin_invoker is None
                else self.plugin_invoker.diagnostics()
            ),
            plugin_sandboxes=(
                None
                if self.plugin_runtime is None
                else await self.plugin_runtime.diagnostics()
            ),
        )

    async def cleanup(self) -> None:
        await self.graph_room_hub.shutdown()
        await self.execution_manager.shutdown()
        if self.plugin_runtime is not None:
            await self.plugin_runtime.shutdown()
        await self.artifacts.close()


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
