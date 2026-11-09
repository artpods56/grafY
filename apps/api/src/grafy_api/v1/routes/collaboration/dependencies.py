"""Project room dependencies, including WebSocket-scoped resolvers.

WebSocket endpoints resolve through the same ``Depends()`` graph as HTTP routes, but
from the ``WebSocket`` parameter rather than a ``Request``; the ``*_ws`` resolvers
mirror their HTTP counterparts for those endpoints. The Run service the room reads
is the one the HTTP Run routes read, resolved from
:mod:`grafy_api.v1.routes.runs.dependencies`.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request, WebSocket

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.identity import IdentityService
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.app_state import get_identity, get_resources
from grafy_api.realtime.hub import ProjectRoomHub
from grafy_api.v1.routes.auth.services import AuthService
from grafy_api.v1.routes.runs.dependencies import (
    RunServiceWsDependency,
    run_service_ws,
)


def project_room_hub_ws(websocket: WebSocket) -> ProjectRoomHub:
    return get_resources(websocket.app).project_room_hub


def collaboration_service(request: Request) -> CollaborationService:
    return get_resources(request.app).collaboration


def collaboration_service_ws(websocket: WebSocket) -> CollaborationService:
    return get_resources(websocket.app).collaboration


def identity_service_ws(websocket: WebSocket) -> IdentityService:
    return get_identity(websocket.app).identity_service


def auth_service_ws(websocket: WebSocket) -> AuthService:
    return get_identity(websocket.app).auth_service


def identity_uow_factory_ws(
    websocket: WebSocket,
) -> Callable[[], SqlAlchemyUnitOfWork]:
    return get_identity(websocket.app).identity_uow_factory


ProjectRoomHubWsDependency = Annotated[
    ProjectRoomHub,
    Depends(project_room_hub_ws),
]
CollaborationDependency = Annotated[
    CollaborationService,
    Depends(collaboration_service),
]
CollaborationWsDependency = Annotated[
    CollaborationService,
    Depends(collaboration_service_ws),
]
IdentityServiceWsDependency = Annotated[
    IdentityService,
    Depends(identity_service_ws),
]
AuthServiceWsDependency = Annotated[AuthService, Depends(auth_service_ws)]
IdentityUnitOfWorkFactoryWsDependency = Annotated[
    Callable[[], SqlAlchemyUnitOfWork],
    Depends(identity_uow_factory_ws),
]


__all__ = [
    "AuthServiceWsDependency",
    "CollaborationDependency",
    "CollaborationWsDependency",
    "IdentityServiceWsDependency",
    "IdentityUnitOfWorkFactoryWsDependency",
    "ProjectRoomHubWsDependency",
    "RunServiceWsDependency",
    "auth_service_ws",
    "collaboration_service",
    "collaboration_service_ws",
    "identity_service_ws",
    "identity_uow_factory_ws",
    "project_room_hub_ws",
    "run_service_ws",
]
