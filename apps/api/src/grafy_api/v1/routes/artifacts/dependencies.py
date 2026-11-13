from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources
from grafy_api.artifacts.content import ArtifactContentService
from grafy_api.artifacts.geo import ArtifactGeoService
from grafy_api.artifacts.geo_tiles import ArtifactGeoTileService
from grafy_api.artifacts.tables import ArtifactTableService


def artifact_content_service(request: Request) -> ArtifactContentService:
    return get_resources(request.app).workbench.artifact_content


def artifact_table_service(request: Request) -> ArtifactTableService:
    return get_resources(request.app).workbench.artifact_tables


def artifact_geo_service(request: Request) -> ArtifactGeoService:
    return get_resources(request.app).workbench.artifact_geo


def artifact_geo_tile_service(request: Request) -> ArtifactGeoTileService:
    return get_resources(request.app).workbench.artifact_geo_tiles


ArtifactContentDependency = Annotated[
    ArtifactContentService,
    Depends(artifact_content_service),
]
ArtifactTableDependency = Annotated[
    ArtifactTableService,
    Depends(artifact_table_service),
]
ArtifactGeoDependency = Annotated[
    ArtifactGeoService,
    Depends(artifact_geo_service),
]
ArtifactGeoTileDependency = Annotated[
    ArtifactGeoTileService,
    Depends(artifact_geo_tile_service),
]

__all__ = [
    "ArtifactContentDependency",
    "ArtifactGeoDependency",
    "ArtifactGeoTileDependency",
    "ArtifactTableDependency",
    "artifact_content_service",
    "artifact_geo_service",
    "artifact_geo_tile_service",
    "artifact_table_service",
]
