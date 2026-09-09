from typing import Annotated

from fastapi import Depends, Request

from grafy_core.application.modules import ModuleLibraryService

from grafy_api.app_state import get_resources


def module_library_service(request: Request) -> ModuleLibraryService:
    service = get_resources(request.app).workbench.module_library
    if service is None:
        raise RuntimeError("Module library is not initialized")
    return service


ModuleLibraryDependency = Annotated[
    ModuleLibraryService,
    Depends(module_library_service),
]


__all__ = ["ModuleLibraryDependency", "module_library_service"]
