from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from grafy_core.application.project_creation import MAIN_GRAPH_ID
from grafy_core.domain.errors import (
    NotFoundError,
    CollaborationHeadConflictError,
)
from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.v1.routes.auth.dependencies import require_workspace_capability
from grafy_api.v1.routes.node_secrets.dependencies import NodeSecretDependency
from grafy_api.v1.routes.node_secrets.models import (
    ConfigureNodeSecretRequest,
    NodeSecretStatusResponse,
    ProjectNodeSecretsResponse,
)
from grafy_api.node_secrets import (
    NodeSecretConfigurationError,
    NodeSecretDeclarationError,
)


router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}",
    tags=["node secrets"],
)


@router.get(
    "/node-secrets",
    response_model=ProjectNodeSecretsResponse,
)
async def get_node_secret_status(
    project_id: UUID,
    service: NodeSecretDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_PROJECT),
    graph_id: Annotated[str, Query()] = MAIN_GRAPH_ID,
) -> ProjectNodeSecretsResponse:
    """Secret status for one Graph of the Project's live head.

    A Project holds several Graphs and a secret belongs to a node of exactly one of
    them, so the listing stays per-Graph and defaults to the Graph a new Project
    opens on.
    """

    try:
        state = await service.status(access.workspace_id, project_id, graph_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectNodeSecretsResponse.from_state(state)


@router.put(
    "/graphs/{graph_id}/nodes/{node_id}/secrets/{name}",
    response_model=NodeSecretStatusResponse,
)
async def configure_node_secret(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    name: str,
    request: ConfigureNodeSecretRequest,
    service: NodeSecretDependency,
    access: require_workspace_capability(WorkspaceCapability.MANAGE_SECRETS),
) -> NodeSecretStatusResponse:
    try:
        state = await service.configure(
            project_id=project_id,
            graph_id=graph_id,
            workspace_id=access.workspace_id,
            node_id=node_id,
            name=name,
            value=request.value,
            expected_head_sequence=request.expected_head_sequence,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NodeSecretDeclarationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationHeadConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NodeSecretConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return NodeSecretStatusResponse.from_state(state)


@router.delete(
    "/graphs/{graph_id}/nodes/{node_id}/secrets/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_node_secret(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    name: str,
    service: NodeSecretDependency,
    access: require_workspace_capability(WorkspaceCapability.MANAGE_SECRETS),
    expected_head_sequence: Annotated[int, Query(ge=0)],
) -> Response:
    try:
        await service.remove(
            project_id=project_id,
            graph_id=graph_id,
            workspace_id=access.workspace_id,
            node_id=node_id,
            name=name,
            expected_head_sequence=expected_head_sequence,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NodeSecretDeclarationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationHeadConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
