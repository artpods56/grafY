from collections.abc import AsyncIterator
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import StringConstraints
from starlette.responses import StreamingResponse

from grafy_core.domain.errors import (
    CollaborationActiveExecutionError,
    NotFoundError,
    SavedGraphRevisionConflictError,
)
from grafy_core.domain.execution_history import GraphExecutionStatus
from grafy_core.domain.identity import WorkspaceAccess, WorkspaceCapability

from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)
from grafy_api.v1.routes.auth.dependencies import (
    IdentityUnitOfWorkFactoryDependency,
    require_workspace_capability,
)
from grafy_api.v1.routes.collaboration.publish import actor_presentation_for
from grafy_api.v1.routes.saved_graphs.dependencies import SavedGraphDependency

from .dependencies import (
    ExecutionAdmissionLimiterDependency,
    ExecutionHistoryDependency,
    MaterializationDependency,
    RunExecutionManagerDependency,
    RunGraphDependency,
    RunResultPresenterDependency,
)
from grafy_api.v1.routes.executions.models import (
    GraphExecutionCursorModel,
    GraphExecutionDetailResponse,
    GraphExecutionListResponse,
    GraphExecutionNodeResultResponse,
    GraphMaterializationsResponse,
    RunExecutionCapacityErrorDetail,
    RunExecutionCapacityErrorResponse,
    RunExecutionQueueFullErrorDetail,
    RunExecutionQueueFullErrorResponse,
    RunExecutionIdempotencyConflictErrorDetail,
    RunExecutionResponse,
    RunResponse,
    SavedGraphExecutionRequest,
)
from grafy_api.execution.requests import RunRequest
from grafy_api.execution.admission import (
    RunExecutionCapacityError,
    RunExecutionQueueFullError,
)
from grafy_api.execution.manager import RunExecutionIdempotencyConflictError


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["executions"])

_MAX_EVENT_SEQUENCE: Final = 9_007_199_254_740_991
_MAX_EVENT_SEQUENCE_DIGITS: Final = len(str(_MAX_EVENT_SEQUENCE))

ExecutionNodeFilter = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


def _idempotency_conflict_http_exception(
    error: RunExecutionIdempotencyConflictError,
) -> HTTPException:
    detail = RunExecutionIdempotencyConflictErrorDetail(
        error_code=error.error_code,
        message=str(error),
        idempotency_key=error.idempotency_key,
        execution_id=error.execution_id,
    )
    return HTTPException(
        status_code=409,
        detail=detail.model_dump(mode="json"),
    )


@router.post(
    "/runs",
    response_model=RunResponse,
    responses={
        429: {
            "description": "The process-wide active execution limit is exhausted",
            "model": RunExecutionCapacityErrorResponse,
            "headers": {
                "Retry-After": {
                    "description": "Minimum delay before retrying, in seconds",
                    "schema": {"type": "integer", "minimum": 1},
                }
            },
        }
    },
)
async def run_graph(
    request: RunRequest,
    service: RunGraphDependency,
    admission_limiter: ExecutionAdmissionLimiterDependency,
    presenter: RunResultPresenterDependency,
    access: require_workspace_capability(WorkspaceCapability.EXECUTE_GRAPH),
) -> RunResponse:
    try:
        admission_lease = admission_limiter.acquire()
        try:
            execution = await service.run(access.workspace_id, request)
            return await presenter.run_response(access.workspace_id, execution)
        finally:
            admission_lease.release()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunExecutionCapacityError as exc:
        detail = RunExecutionCapacityErrorDetail(
            error_code=exc.error_code,
            message=str(exc),
            max_active_executions=exc.max_active_executions,
        )
        raise HTTPException(
            status_code=429,
            detail=detail.model_dump(mode="json"),
            headers={"Retry-After": "1"},
        ) from exc
    except SavedGraphRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _start_execution(
    *,
    request: RunRequest,
    manager: RunExecutionManagerDependency,
    presenter: RunResultPresenterDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
    access: WorkspaceAccess,
    idempotency_key: str | None,
) -> RunExecutionResponse:
    try:
        starter = await actor_presentation_for(uow_factory, access.actor)
        execution = await manager.start(
            access.workspace_id,
            request,
            starter=starter,
            idempotency_key=idempotency_key,
        )
        return await presenter.execution_response(execution)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunExecutionCapacityError as exc:
        detail = RunExecutionCapacityErrorDetail(
            error_code=exc.error_code,
            message=str(exc),
            max_active_executions=exc.max_active_executions,
        )
        raise HTTPException(
            status_code=429,
            detail=detail.model_dump(mode="json"),
            headers={"Retry-After": "1"},
        ) from exc
    except RunExecutionQueueFullError as exc:
        detail = RunExecutionQueueFullErrorDetail(
            error_code=exc.error_code,
            message=str(exc),
            max_pending_graphs=exc.max_pending_graphs,
        )
        raise HTTPException(
            status_code=429,
            detail=detail.model_dump(mode="json"),
            headers={"Retry-After": "1"},
        ) from exc
    except RunExecutionIdempotencyConflictError as exc:
        raise _idempotency_conflict_http_exception(exc) from exc
    except CollaborationActiveExecutionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": exc.error_code,
                "message": str(exc),
                "execution_id": str(exc.execution_id),
                "graph_id": str(exc.graph_id),
                "workspace_id": str(exc.workspace_id),
            },
        ) from exc
    except SavedGraphRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/executions",
    response_model=RunExecutionResponse,
    status_code=202,
    responses={
        429: {
            "description": (
                "The durable pending queue is full, or a non-durable draft run "
                "cannot acquire active capacity"
            ),
            "model": (
                RunExecutionQueueFullErrorResponse | RunExecutionCapacityErrorResponse
            ),
            "headers": {
                "Retry-After": {
                    "description": "Minimum delay before retrying, in seconds",
                    "schema": {"type": "integer", "minimum": 1},
                }
            },
        }
    },
)
async def start_graph_execution(
    request: RunRequest,
    manager: RunExecutionManagerDependency,
    presenter: RunResultPresenterDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
    access: require_workspace_capability(WorkspaceCapability.EXECUTE_GRAPH),
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            pattern=r".*\S.*",
        ),
    ] = None,
) -> RunExecutionResponse:
    return await _start_execution(
        request=request,
        manager=manager,
        presenter=presenter,
        uow_factory=uow_factory,
        access=access,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/graphs/{graph_id}/executions",
    response_model=RunExecutionResponse,
    status_code=202,
    responses={
        429: {
            "description": "The durable pending execution queue is full",
            "model": RunExecutionQueueFullErrorResponse,
            "headers": {
                "Retry-After": {
                    "description": "Minimum delay before retrying, in seconds",
                    "schema": {"type": "integer", "minimum": 1},
                }
            },
        }
    },
)
async def start_saved_graph_execution(
    graph_id: UUID,
    request: SavedGraphExecutionRequest,
    saved_graphs: SavedGraphDependency,
    manager: RunExecutionManagerDependency,
    presenter: RunResultPresenterDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
    access: require_workspace_capability(WorkspaceCapability.EXECUTE_GRAPH),
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            pattern=r".*\S.*",
        ),
    ] = None,
) -> RunExecutionResponse:
    if idempotency_key is not None:
        try:
            replay = await manager.replay_saved_graph_execution(
                access.workspace_id,
                idempotency_key,
                graph_id=graph_id,
                graph_revision=request.expected_revision,
            )
        except RunExecutionIdempotencyConflictError as exc:
            raise _idempotency_conflict_http_exception(exc) from exc
        if replay is not None:
            return await presenter.execution_response(replay)

    try:
        graph = await saved_graphs.get(access.workspace_id, graph_id)
        graph.ensure_revision(request.expected_revision)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SavedGraphRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return await _start_execution(
        request=RunRequest.from_saved_graph(graph),
        manager=manager,
        presenter=presenter,
        uow_factory=uow_factory,
        access=access,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/executions/{execution_id}",
    response_model=RunExecutionResponse,
)
async def get_graph_execution(
    execution_id: UUID,
    manager: RunExecutionManagerDependency,
    presenter: RunResultPresenterDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_EXECUTION),
) -> RunExecutionResponse:
    try:
        execution = await manager.get(access.workspace_id, execution_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await presenter.execution_response(execution)


@router.get(
    "/executions/{execution_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-sent execution lifecycle and node progress events",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream_graph_execution_events(
    execution_id: UUID,
    request: Request,
    manager: RunExecutionManagerDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_EXECUTION),
    last_event_id: Annotated[
        str | None,
        Header(alias="Last-Event-ID"),
    ] = None,
) -> StreamingResponse:
    after_sequence = 0
    if last_event_id is not None:
        normalized_event_id = last_event_id.strip()
        if (
            normalized_event_id == ""
            or not normalized_event_id.isascii()
            or not normalized_event_id.isdigit()
        ):
            raise HTTPException(
                status_code=422,
                detail="Last-Event-ID must be a non-negative integer",
            )
        if len(normalized_event_id) > _MAX_EVENT_SEQUENCE_DIGITS:
            raise HTTPException(
                status_code=422,
                detail="Last-Event-ID exceeds the supported sequence range",
            )
        try:
            after_sequence = int(normalized_event_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Last-Event-ID must be a non-negative integer",
            ) from exc
        if after_sequence > _MAX_EVENT_SEQUENCE:
            raise HTTPException(
                status_code=422,
                detail="Last-Event-ID exceeds the supported sequence range",
            )

    try:
        subscription = await manager.subscribe_events(access.workspace_id, execution_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_stream() -> AsyncIterator[str]:
        sequence = after_sequence
        while True:
            batch = await subscription.wait(
                after_sequence=sequence,
                timeout=15,
            )
            if await request.is_disconnected():
                return
            if not batch.events:
                if batch.terminal:
                    return
                yield ": heartbeat\n\n"
                continue
            for event in batch.events:
                sequence = event.sequence
                yield (
                    f"id: {event.sequence}\n"
                    f"event: {event.kind}\n"
                    f"data: {event.model_dump_json()}\n\n"
                )
            if batch.terminal:
                return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete(
    "/executions/{execution_id}",
    response_model=RunExecutionResponse,
)
async def cancel_graph_execution(
    execution_id: UUID,
    manager: RunExecutionManagerDependency,
    presenter: RunResultPresenterDependency,
    access: require_workspace_capability(WorkspaceCapability.CANCEL_EXECUTION),
) -> RunExecutionResponse:
    try:
        execution = await manager.cancel(access.workspace_id, execution_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await presenter.execution_response(execution)


@router.get(
    "/graphs/{graph_id}/materializations",
    response_model=GraphMaterializationsResponse,
)
async def get_graph_materializations(
    graph_id: UUID,
    graph_revision: Annotated[int, Query(ge=1)],
    service: MaterializationDependency,
    presenter: RunResultPresenterDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_MATERIALIZATIONS),
) -> GraphMaterializationsResponse:
    try:
        materializations = await service.list_for_graph(
            access.workspace_id,
            graph_id,
            graph_revision,
        )
        return await presenter.materializations_response(
            access.workspace_id,
            graph_id,
            graph_revision,
            materializations,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SavedGraphRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/graphs/{graph_id}/executions",
    response_model=GraphExecutionListResponse,
)
async def list_graph_executions(
    graph_id: UUID,
    service: ExecutionHistoryDependency,
    saved_graphs: SavedGraphDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_HISTORY),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    graph_revision: Annotated[int | None, Query(ge=1)] = None,
    execution_status: Annotated[
        GraphExecutionStatus | None,
        Query(alias="status"),
    ] = None,
    node_id: Annotated[ExecutionNodeFilter | None, Query()] = None,
) -> GraphExecutionListResponse:
    try:
        await saved_graphs.get(access.workspace_id, graph_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    decoded_cursor = None
    if cursor is not None:
        try:
            decoded_cursor = GraphExecutionCursorModel.decode(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    page = await service.list_for_graph(
        access.workspace_id,
        graph_id,
        limit=limit,
        cursor=decoded_cursor,
        graph_revision=graph_revision,
        status=execution_status,
        node_id=node_id,
    )
    return GraphExecutionListResponse.from_page(page)


@router.get(
    "/graphs/{graph_id}/executions/{execution_id}",
    response_model=GraphExecutionDetailResponse,
)
async def get_graph_execution_history(
    graph_id: UUID,
    execution_id: UUID,
    service: ExecutionHistoryDependency,
    presenter: RunResultPresenterDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_HISTORY),
) -> GraphExecutionDetailResponse:
    detail = await service.get_for_graph(access.workspace_id, graph_id, execution_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Graph execution not found")

    node_results = [
        GraphExecutionNodeResultResponse.from_result(
            node_result,
            outputs=[
                await presenter.port_output_response(
                    access.workspace_id, port_name, value
                )
                for port_name, value in node_result.outputs.items()
            ],
        )
        for node_result in detail.node_results
    ]
    return GraphExecutionDetailResponse.from_detail(
        detail,
        node_results=node_results,
    )


__all__ = [
    "cancel_graph_execution",
    "get_graph_execution",
    "stream_graph_execution_events",
    "get_graph_execution_history",
    "get_graph_materializations",
    "list_graph_executions",
    "router",
    "run_graph",
    "start_graph_execution",
    "start_saved_graph_execution",
]
