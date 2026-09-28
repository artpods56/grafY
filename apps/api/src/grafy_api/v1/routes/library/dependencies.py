from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources

from .folders import LibraryFoldersService
from .services import LibraryService


def library_service(request: Request) -> LibraryService:
    return get_resources(request.app).workbench.library


def library_folders_service(request: Request) -> LibraryFoldersService:
    return get_resources(request.app).workbench.library_folders


LibraryDependency = Annotated[LibraryService, Depends(library_service)]
LibraryFoldersDependency = Annotated[
    LibraryFoldersService,
    Depends(library_folders_service),
]


__all__ = [
    "LibraryDependency",
    "LibraryFoldersDependency",
    "library_folders_service",
    "library_service",
]
