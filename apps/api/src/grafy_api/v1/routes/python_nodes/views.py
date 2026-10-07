from fastapi import APIRouter, HTTPException, status

from grafy_api.python_nodes import PythonApplyUnavailableError
from grafy_api.v1.routes.python_nodes.dependencies import (
    PythonApplyDependency,
    PythonEditGraphAccess,
)
from grafy_api.v1.routes.python_nodes.models import (
    ApplyPythonCodeRequest,
    ApplyPythonCodeResponse,
)


router = APIRouter(prefix="/workspaces/{workspace_id}/python", tags=["python nodes"])


@router.post("/apply", response_model=ApplyPythonCodeResponse)
async def apply_python_code(
    request: ApplyPythonCodeRequest,
    service: PythonApplyDependency,
    access: PythonEditGraphAccess,
) -> ApplyPythonCodeResponse:
    """Derive the contract of Python node code without running it on the host."""

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Python nodes need the isolated Plugin runtime",
        )
    try:
        result = await service.apply(
            workspace_id=access.workspace_id,
            code=request.code,
            scope=request.plugin_release.scope,
            slug=request.plugin_release.slug,
            revision=request.plugin_release.revision,
        )
    except PythonApplyUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return ApplyPythonCodeResponse.from_result(result)


__all__ = ["router"]
