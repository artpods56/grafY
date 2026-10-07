from typing import Annotated, TYPE_CHECKING

from fastapi import Depends, Request

from grafy_core.domain.identity import WorkspaceAccess, WorkspaceCapability

from grafy_api.v1.routes.auth.dependencies import require_workspace_capability
from grafy_api.app_state import get_resources
from grafy_api.python_nodes import PythonApplyService


def python_apply_service(request: Request) -> PythonApplyService | None:
    return get_resources(request.app).workbench.python_apply


PythonApplyDependency = Annotated[
    PythonApplyService | None,
    Depends(python_apply_service),
]


# The capability factory builds FastAPI Annotated metadata at runtime.
if TYPE_CHECKING:
    PythonEditGraphAccess = WorkspaceAccess
else:
    PythonEditGraphAccess = require_workspace_capability(WorkspaceCapability.EDIT_GRAPH)


__all__ = ["PythonApplyDependency", "PythonEditGraphAccess", "python_apply_service"]
