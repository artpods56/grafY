from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources

from .services import LibraryService


def library_service(request: Request) -> LibraryService:
    return get_resources(request.app).workbench.library


LibraryDependency = Annotated[LibraryService, Depends(library_service)]


__all__ = ["LibraryDependency", "library_service"]
