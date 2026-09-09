from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from grafy_core.domain.errors import (
    NotFoundError,
    SavedGraphRevisionConflictError,
)
from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.v1.routes.auth.dependencies import require_workspace_capability
from grafy_api.v1.routes.node_secrets.dependencies import NodeSecretDependency
from grafy_api.v1.routes.node_secrets.models import (
    ConfigureNodeSecretRequest,
    GraphNodeSecretsResponse,
    NodeSecretStatusResponse,
)
from grafy_api.node_secrets import (
    NodeSecretConfigurationError,
    NodeSecretDeclarationError,
    NodeSecretValueError,
)


router = APIRouter(prefix="/workspaces/{workspace_id}/graphs", tags=["node secrets"])


@router.get(
    "/{graph_id}/node-secrets",
    response_model=GraphNodeSecretsResponse,
)
async def get_node_secret_status(
    graph_id: UUID,
    service: NodeSecretDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_GRAPH),
) -> GraphNodeSecretsResponse:
    try:
        state = await service.status(access.workspace_id, graph_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GraphNodeSecretsResponse.from_state(state)


@router.put(
    "/{graph_id}/nodes/{node_id}/secrets/{name}",
    response_model=NodeSecretStatusResponse,
)
async def configure_node_secret(
    graph_id: UUID,
    node_id: str,
    name: str,
    request: ConfigureNodeSecretRequest,
    service: NodeSecretDependency,
    access: require_workspace_capability(WorkspaceCapability.MANAGE_SECRETS),
) -> NodeSecretStatusResponse:
    try:
        state = await service.configure(
            graph_id=graph_id,
            workspace_id=access.workspace_id,
            node_id=node_id,
            name=name,
            value=request.value,
            expected_graph_revision=request.expected_graph_revision,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NodeSecretDeclarationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SavedGraphRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NodeSecretConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NodeSecretValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return NodeSecretStatusResponse.from_state(state)


@router.delete(
    "/{graph_id}/nodes/{node_id}/secrets/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_node_secret(
    graph_id: UUID,
    node_id: str,
    name: str,
    service: NodeSecretDependency,
    access: require_workspace_capability(WorkspaceCapability.MANAGE_SECRETS),
    expected_graph_revision: Annotated[int, Query(ge=1)],
) -> Response:
    try:
        await service.remove(
            graph_id=graph_id,
            workspace_id=access.workspace_id,
            node_id=node_id,
            name=name,
            expected_graph_revision=expected_graph_revision,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NodeSecretDeclarationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SavedGraphRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
