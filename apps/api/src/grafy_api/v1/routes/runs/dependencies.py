"""Run route dependencies: the Run service and Project tenancy (ADR 0020).

Every Run route resolves through here, which is what makes the two rules a Run
route cannot forget impossible to skip: the Project is read under the Workspace in
the URL before the Run service is asked anything, and the Run service is the one
this API owner composed at startup — the same instance the Project room reads, so a
Run started over HTTP is the Run the room announces.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, WebSocket

from grafy_core.domain.projects import Project

from grafy_api.app_state import get_resources
from grafy_api.runs.service import RunService


def run_service(request: Request) -> RunService:
    return get_resources(request.app).runs


def run_service_ws(websocket: WebSocket) -> RunService:
    return get_resources(websocket.app).runs


async def project_in_workspace(
    workspace_id: UUID,
    project_id: UUID,
    request: Request,
) -> Project:
    """Tenancy before anything else: a Project of another Workspace is not here.

    ``ProjectService.get`` answers ``NotFoundError`` outside its own Workspace, which
    the HTTP error map renders as 404 — the same answer as for a Project that was
    never opened, so no route can tell a caller what another Workspace holds.
    """

    return await get_resources(request.app).projects.get(
        workspace_id=workspace_id,
        project_id=project_id,
    )


RunServiceDependency = Annotated[RunService, Depends(run_service)]
RunServiceWsDependency = Annotated[RunService, Depends(run_service_ws)]
ProjectScopeDependency = Annotated[Project, Depends(project_in_workspace)]


__all__ = [
    "ProjectScopeDependency",
    "RunServiceDependency",
    "RunServiceWsDependency",
    "project_in_workspace",
    "run_service",
    "run_service_ws",
]
