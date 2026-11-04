from typing import Annotated

from fastapi import Depends, Request

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.projects import ProjectService

from grafy_api.app_state import get_resources


def project_service(request: Request) -> ProjectService:
    return get_resources(request.app).projects


def collaboration_service(request: Request) -> CollaborationService:
    return get_resources(request.app).collaboration


ProjectDependency = Annotated[ProjectService, Depends(project_service)]

CollaborationDependency = Annotated[
    CollaborationService,
    Depends(collaboration_service),
]


__all__ = [
    "CollaborationDependency",
    "ProjectDependency",
    "collaboration_service",
    "project_service",
]
