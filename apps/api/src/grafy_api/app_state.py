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
    from grafy_api.agents.conversations import AgentConversationService
    from grafy_api.agents.keys import AgentKeyService
    from grafy_api.agents.models import AgentModelResolver
    from grafy_api.agents.turns import AgentService
    from grafy_api.node_secrets import NodeSecretService
    from grafy_api.realtime.hub import ProjectRoomHub
    from grafy_api.runs.service import RunService
    from grafy_api.services.composition import WorkbenchComponents
    from grafy_api.auth import AuthService


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
    # Agent history, its write-only key, and the model its next turn will dial. The
    # send/cancel routes and the room frames own everything above these three.
    agent_keys: AgentKeyService
    agent_conversations: AgentConversationService
    agent_models: AgentModelResolver
    # The turn runtime is the one Agent owner that holds tasks and open model clients, so
    # it is the one with something to stop, and it is what startup recovery marks interrupted.
    agent_turns: AgentService
    project_room_hub: ProjectRoomHub

    async def cleanup(self) -> None:
        # Turns first, while the room still exists: a turn's last act is to publish the
        # text it finished with, and a hub that has already shut down cannot carry it.
        await self.agent_turns.close()
        await self.project_room_hub.shutdown()
        await self.runs.close()
        await self.workbench.wms.close()


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
