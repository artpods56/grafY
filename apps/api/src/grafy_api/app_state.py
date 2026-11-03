"""Typed FastAPI application state for identity and workbench resources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import FastAPI
from grafy_core.application.identity import IdentityService
from grafy_core.ports.identity import IdentityUnitOfWorkPort

if TYPE_CHECKING:
    from grafy_core.application.collaboration import CollaborationService
    from grafy_core.application.projects import ProjectService
    from grafy_persistence.database import Database
    from grafy_api.node_secrets import NodeSecretService
    from grafy_api.realtime.hub import ProjectRoomHub
    from grafy_api.runs.service import RunService
    from grafy_api.services.composition import WorkbenchComponents
    from grafy_api.v1.routes.auth.services import AuthService


@dataclass(slots=True)
class AppIdentity:
    """Auth and workspace-identity services attached for the app lifetime."""

    identity_uow_factory: Callable[[], IdentityUnitOfWorkPort]
    identity_service: IdentityService
    auth_service: AuthService
    # The one AppConfig value a request handler needs: the Origin header of the
    # browser this deployment serves. Routes read this instead of app.state.settings.
    public_origin: str


@dataclass(slots=True)
class AppResources:
    """Application resources constructed during API lifespan and torn down once."""

    database: Database
    workbench: WorkbenchComponents
    projects: ProjectService
    runs: RunService
    collaboration: CollaborationService
    node_secrets: NodeSecretService
    project_room_hub: ProjectRoomHub

    async def cleanup(self) -> None:
        await self.project_room_hub.shutdown()
        await self.runs.close()
        await self.workbench.artifacts.close()


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
