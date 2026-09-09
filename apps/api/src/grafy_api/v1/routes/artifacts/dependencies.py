from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources

from .services import ArtifactService


def artifact_service(request: Request) -> ArtifactService:
    return get_resources(request.app).workbench.artifacts


ArtifactDependency = Annotated[
    ArtifactService,
    Depends(artifact_service),
]


__all__ = ["ArtifactDependency", "artifact_service"]
