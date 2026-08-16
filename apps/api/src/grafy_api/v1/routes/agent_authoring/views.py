import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from starlette.responses import StreamingResponse

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.conversions import ArtifactConversionKey
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentAuthoringConflictError,
    AgentAuthoringError,
    AgentPortDirection,
    AnchoredPortContract,
    PortConversion,
    PortFeed,
)
from grafy_core.domain.collaboration import (
    AddEdgeCommand,
    AddNodeCommand,
    ApplyGraphCommandBatch,
    CommandReceiptOutcome,
    UpdateNodeOperatorCommand,
)
from grafy_core.domain.errors import (
    CollaborationCommandRejectedError,
    CollaborationHeadConflictError,
    CollaborationIdempotencyMismatchError,
    MissingCollaborativeHeadError,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceCapability,
)
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraphConversion,
    SavedGraphEdge,
    SavedGraphNode,
    SavedGraphProjection,
)
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.app_state import AppResources, get_resources
from grafy_api.v1.routes.auth.dependencies import workspace_capability_dependency
from grafy_api.v1.routes.catalog.models import (
    NodeRegistryResponse,
    NodeSpecResponse,
    agent_release_is_runnable,
)
from grafy_api.v1.routes.collaboration.publish import publish_accepted_command
from grafy_api.v1.routes.saved_graphs.models import (
    CollaborativeHeadResponse,
    GraphCommandReceiptResponse,
)

from .dependencies import AgentAuthoringDependency, BuildReviewDependency
from .models import (
    AgentDraftDetailResponse,
    AgentDraftResponse,
    AgentEnvironmentListResponse,
    AgentEnvironmentResponse,
    AgentEventResponse,
    AgentFollowUpRunResponse,
    AgentRunDetailResponse,
    AgentRunResponse,
    AgentThreadResponse,
    ApproveBuildRequest,
    BuildReviewFileContentResponse,
    BuildReviewResponse,
    CapabilityApprovalResponse,
    CreateAgentDraftRequest,
    CreateAgentDraftResponse,
    CreateAgentEnvironmentRequest,
    NodeBuildResponse,
    NodeReleaseResponse,
    PublishBuildRequest,
    PublishBuildResponse,
    QueueAgentFollowUpRequest,
)
from .services import BuildReviewError, BuildReviewFileNotFoundError


_MAX_EVENT_SEQUENCE = (2**63) - 1
_MAX_EVENT_SEQUENCE_DIGITS = len(str(_MAX_EVENT_SEQUENCE))
_EVENT_POLL_SECONDS = 0.5
_HEARTBEAT_POLL_COUNT = 30

router = APIRouter(
    prefix="/workspaces/{workspace_id}/agent-authoring",
    tags=["agent authoring"],
)

ViewGraphAccess = Annotated[
    WorkspaceAccess,
    Depends(workspace_capability_dependency(WorkspaceCapability.VIEW_GRAPH)),
]
EditGraphAccess = Annotated[
    WorkspaceAccess,
    Depends(workspace_capability_dependency(WorkspaceCapability.EDIT_GRAPH)),
]


async def _resolve_authoritative_anchor(
    *,
    resources: AppResources,
    actor: ActorContext,
    workspace_id: UUID,
    graph_id: UUID,
    body: CreateAgentDraftRequest,
) -> AnchoredPortContract:
    if body.anchor.collection_mode != "direct":
        raise AgentAuthoringError(
            "Generated-node anchors support direct collection mode in this release"
        )
    head = await resources.collaboration.get_head(
        actor=actor,
        workspace_id=workspace_id,
        graph_id=graph_id,
    )
    existing_node = next(
        (
            node
            for node in head.document.nodes
            if node.id == body.anchor.node_id
        ),
        None,
    )
    if existing_node is None:
        raise AgentAuthoringError(
            f"Generated-node anchor references missing graph node "
            f"{body.anchor.node_id!r}"
        )

    module_listing = await resources.graph_modules.list(workspace_id)
    drafts = await resources.agent_authoring.list_drafts(workspace_id)
    releases = await resources.agent_authoring.list_releases(workspace_id)
    registry = NodeRegistryResponse.from_registry(
        resources.plugin_registry,
        module_listing,
        resources.run_graph,
        agent_drafts=drafts,
        agent_releases=releases,
        generated_execution_available=(resources.generated_executor is not None),
    )
    node_spec = next(
        (
            node
            for node in registry.nodes
            if node.operator_id == existing_node.operator_id
            and node.operator_version == existing_node.operator_version
        ),
        None,
    )
    if node_spec is None:
        raise AgentAuthoringError(
            f"Generated-node anchor operator {existing_node.operator_id}@"
            f"{existing_node.operator_version} is unavailable"
        )

    expected_direction = "output"
    ports = node_spec.outputs
    generated_direction = AgentPortDirection.INPUT
    if body.anchor.direction == "upstream":
        expected_direction = "input"
        ports = node_spec.inputs
        generated_direction = AgentPortDirection.OUTPUT
    port = next(
        (candidate for candidate in ports if candidate.name == body.anchor.port_name),
        None,
    )
    if port is None or port.direction != expected_direction:
        raise AgentAuthoringError(
            f"Generated-node anchor {body.anchor.node_id!r}."
            f"{body.anchor.port_name!r} is not an available {expected_direction} port"
        )

    artifact_type: ArtifactTypeKey | None = None
    if port.artifact_type is not None:
        artifact_type = port.artifact_type.to_key()
    elif port.artifact_type_variable is not None:
        artifact_type = existing_node.artifact_type_binding_map().get(
            port.artifact_type_variable
        )
    if artifact_type is None:
        raise AgentAuthoringError(
            f"Generated-node anchor {body.anchor.node_id!r}."
            f"{body.anchor.port_name!r} must have a concrete artifact type binding"
        )

    requested_shape = body.anchor.shape
    if body.anchor.direction == "downstream":
        if requested_shape is not port.shape:
            raise AgentAuthoringError(
                "Generated-node downstream anchor shape does not match the live "
                "output port"
            )
    elif requested_shape not in port.accepted_shapes:
        raise AgentAuthoringError(
            "Generated-node upstream anchor shape is not accepted by the live input "
            "port"
        )

    projection_path = body.anchor.feed.projection_path
    if projection_path:
        if body.anchor.direction != "downstream":
            raise AgentAuthoringError(
                "Generated-node projection feeds are only valid downstream of outputs"
            )
        artifact_spec = next(
            (
                candidate
                for candidate in resources.plugin_registry.artifact_types
                if candidate.key == artifact_type
            ),
            None,
        )
        projection = None
        if artifact_spec is not None:
            projection = next(
                (
                    candidate
                    for candidate in artifact_spec.field_projections
                    if candidate.path == projection_path
                ),
                None,
            )
        if projection is None:
            raise AgentAuthoringError(
                f"Generated-node anchor requests undeclared projection "
                f"{'.'.join(projection_path)!r}"
            )
        artifact_type = projection.target

    conversions = {
        conversion.key: conversion
        for conversion in resources.plugin_registry.artifact_conversions
    }
    for requested_conversion in body.anchor.feed.conversion_path:
        key = ArtifactConversionKey(
            id=requested_conversion.id,
            version=requested_conversion.version,
        )
        conversion = conversions.get(key)
        if conversion is None or conversion.source != artifact_type:
            raise AgentAuthoringError(
                f"Generated-node anchor conversion {key.id}@{key.version} does not "
                "apply to the effective artifact type"
            )
        artifact_type = conversion.target

    if artifact_type != body.anchor.artifact_type.to_key():
        raise AgentAuthoringError(
            "Generated-node anchor artifact type does not match the authoritative "
            "port, binding, projection, and conversion contract"
        )

    if body.anchor.direction == "upstream":
        if port.instance_plugs:
            plug = next(
                (
                    candidate
                    for candidate in existing_node.input_plugs
                    if candidate.id == body.anchor.input_plug_id
                ),
                None,
            )
            if plug is None or plug.port != port.name:
                raise AgentAuthoringError(
                    "Generated-node anchor input plug is not declared on the live port"
                )
        elif body.anchor.input_plug_id is not None:
            raise AgentAuthoringError(
                "Generated-node anchor supplied a plug for a non-pluggable input"
            )

    return AnchoredPortContract(
        direction=generated_direction,
        name=port.name,
        artifact_type=AgentArtifactType(
            id=artifact_type.id,
            schema_version=artifact_type.schema_version,
        ),
        shape=requested_shape,
        collection_mode="direct",
        feed=PortFeed(
            projection_path=projection_path,
            conversion_path=tuple(
                PortConversion(id=conversion.id, version=conversion.version)
                for conversion in body.anchor.feed.conversion_path
            ),
        ),
    )


@router.get(
    "/environments",
    response_model=AgentEnvironmentListResponse,
)
async def list_agent_environments(
    authoring: AgentAuthoringDependency,
    access: ViewGraphAccess,
) -> AgentEnvironmentListResponse:
    environments = await authoring.list_environments(access.workspace_id)
    return AgentEnvironmentListResponse.from_environments(environments)


@router.post(
    "/environments",
    response_model=AgentEnvironmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_environment(
    body: CreateAgentEnvironmentRequest,
    request: Request,
    authoring: AgentAuthoringDependency,
    access: EditGraphAccess,
) -> AgentEnvironmentResponse:
    environment = await authoring.create_environment(
        workspace_id=access.workspace_id,
        name=body.name,
        profile_id=body.profile_slug,
        provider=request.app.state.settings.agent_environment_provider,
        created_by_user_id=access.actor.user_id,
    )
    return AgentEnvironmentResponse.from_environment(environment)


@router.post(
    "/graphs/{graph_id}/drafts",
    response_model=CreateAgentDraftResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_agent_draft(
    graph_id: UUID,
    body: CreateAgentDraftRequest,
    request: Request,
    authoring: AgentAuthoringDependency,
    access: EditGraphAccess,
) -> CreateAgentDraftResponse:
    resources = get_resources(request.app)
    command: ApplyGraphCommandBatch
    try:
        anchor = await _resolve_authoritative_anchor(
            resources=resources,
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=graph_id,
            body=body,
        )
        async with SqlAlchemyUnitOfWork(resources.database.sessions) as unit_of_work:
            creation = await authoring.create_draft_in_unit_of_work(
                unit_of_work,
                workspace_id=access.workspace_id,
                graph_id=graph_id,
                prompt=body.prompt,
                anchor=anchor,
                created_by_user_id=access.actor.user_id,
                idempotency_key=str(body.idempotency_key),
                environment_id=body.environment_id,
                thread_id=body.thread_id,
            )
            node = SavedGraphNode(
                id=body.placement.node_id,
                operator_id=creation.draft.operator_id,
                operator_version=creation.draft.operator_version,
                position=GraphPoint(x=body.placement.x, y=body.placement.y),
            )
            projection = None
            if body.anchor.feed.projection_path:
                projection = SavedGraphProjection(
                    path=body.anchor.feed.projection_path
                )
            conversion_path = tuple(
                SavedGraphConversion(
                    id=conversion.id,
                    version=conversion.version,
                )
                for conversion in body.anchor.feed.conversion_path
            )
            if body.anchor.direction == "downstream":
                edge = SavedGraphEdge(
                    id=body.placement.edge_id,
                    from_node=body.anchor.node_id,
                    from_port=body.anchor.port_name,
                    to_node=body.placement.node_id,
                    to_port=creation.draft.anchor.name,
                    collection_mode=body.anchor.collection_mode,
                    projection=projection,
                    conversion_path=conversion_path,
                )
            else:
                edge = SavedGraphEdge(
                    id=body.placement.edge_id,
                    from_node=body.placement.node_id,
                    from_port=creation.draft.anchor.name,
                    to_node=body.anchor.node_id,
                    to_port=body.anchor.port_name,
                    to_plug=body.anchor.input_plug_id,
                    collection_mode=body.anchor.collection_mode,
                    projection=projection,
                    conversion_path=conversion_path,
                )
            command = ApplyGraphCommandBatch(
                commands=(
                    AddNodeCommand(node=node),
                    AddEdgeCommand(edge=edge),
                )
            )
            head, receipt = await resources.collaboration.accept_command_in_unit_of_work(
                unit_of_work,
                actor=access.actor,
                workspace_id=access.workspace_id,
                graph_id=graph_id,
                command_id=body.placement.command_id,
                observed_sequence=body.placement.observed_sequence,
                observed_room_epoch=body.placement.room_epoch,
                command=command,
            )
            await unit_of_work.commit()
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationCommandRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        AgentAuthoringConflictError,
        CollaborationHeadConflictError,
        CollaborationIdempotencyMismatchError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentAuthoringError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if receipt.outcome is not CommandReceiptOutcome.IDEMPOTENT_REPLAY:
        await publish_accepted_command(
            request,
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=graph_id,
            command=command,
            receipt=receipt,
        )
    node_spec = NodeSpecResponse.from_agent_draft(creation.draft)
    anchor_ports = (
        node_spec.inputs
        if creation.draft.anchor.direction is AgentPortDirection.INPUT
        else node_spec.outputs
    )
    anchor_port = next(
        port for port in anchor_ports if port.name == creation.draft.anchor.name
    )
    return CreateAgentDraftResponse(
        environment=AgentEnvironmentResponse.from_environment(creation.environment),
        thread=AgentThreadResponse.from_thread(creation.thread),
        draft=AgentDraftResponse.from_draft(creation.draft),
        run=AgentRunResponse.from_run(creation.run),
        build=NodeBuildResponse.from_build(creation.build),
        node_spec=node_spec,
        anchor_port=anchor_port,
        head=CollaborativeHeadResponse.from_head(head),
        receipt=GraphCommandReceiptResponse.from_receipt(receipt),
    )


@router.get(
    "/drafts/{draft_node_id}",
    response_model=AgentDraftDetailResponse,
)
async def get_agent_draft(
    draft_node_id: UUID,
    request: Request,
    authoring: AgentAuthoringDependency,
    access: ViewGraphAccess,
) -> AgentDraftDetailResponse:
    detail = await authoring.get_draft_detail(
        access.workspace_id,
        draft_node_id,
    )
    releases = await authoring.list_releases(access.workspace_id)
    approval = await authoring.get_capability_approval(
        workspace_id=access.workspace_id,
        build_attempt_id=detail.latest_build.id,
    )
    release = max(
        (
            candidate
            for candidate in releases
            if candidate.draft_node_id == detail.draft.id
        ),
        key=lambda candidate: candidate.revision,
        default=None,
    )
    node_spec = NodeSpecResponse.from_agent_build(
        detail.draft,
        detail.latest_build,
    )
    if detail.draft.status.value == "published" and release is not None:
        resources = get_resources(request.app)
        node_spec = NodeSpecResponse.from_agent_release(
            release,
            runnable=agent_release_is_runnable(
                release,
                resources.plugin_registry,
                generated_execution_available=(
                    resources.generated_executor is not None
                ),
            ),
        )
    return AgentDraftDetailResponse(
        environment=AgentEnvironmentResponse.from_environment(detail.environment),
        thread=AgentThreadResponse.from_thread(detail.thread),
        draft=AgentDraftResponse.from_draft(detail.draft),
        latest_run=AgentRunResponse.from_run(detail.latest_run),
        latest_build=NodeBuildResponse.from_build(detail.latest_build),
        node_spec=node_spec,
        release=(
            NodeReleaseResponse.from_release(release)
            if release is not None
            else None
        ),
        capability_approval=(
            CapabilityApprovalResponse.from_approval(approval)
            if approval is not None
            else None
        ),
    )


@router.post(
    "/threads/{thread_id}/runs",
    response_model=AgentFollowUpRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_agent_follow_up_run(
    thread_id: UUID,
    body: QueueAgentFollowUpRequest,
    authoring: AgentAuthoringDependency,
    access: EditGraphAccess,
) -> AgentFollowUpRunResponse:
    try:
        follow_up = await authoring.queue_follow_up_run(
            workspace_id=access.workspace_id,
            thread_id=thread_id,
            draft_node_ids=body.draft_node_ids,
            instructions=body.prompt,
            idempotency_key=str(body.idempotency_key),
            created_by_user_id=access.actor.user_id,
        )
    except AgentAuthoringConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentAuthoringError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    drafts = {
        draft.id: draft
        for draft in await authoring.list_drafts(
            access.workspace_id,
            thread_id=thread_id,
        )
    }
    node_specs = [
        NodeSpecResponse.from_agent_build(drafts[build.draft_node_id], build)
        for build in follow_up.builds
    ]
    return AgentFollowUpRunResponse(
        environment=AgentEnvironmentResponse.from_environment(
            follow_up.environment
        ),
        thread=AgentThreadResponse.from_thread(follow_up.thread),
        run=AgentRunResponse.from_run(follow_up.run),
        builds=[NodeBuildResponse.from_build(build) for build in follow_up.builds],
        node_specs=node_specs,
    )


@router.get(
    "/builds/{build_attempt_id}/review",
    response_model=BuildReviewResponse,
)
async def get_agent_build_review(
    build_attempt_id: UUID,
    request: Request,
    authoring: AgentAuthoringDependency,
    review_service: BuildReviewDependency,
    access: EditGraphAccess,
) -> BuildReviewResponse:
    build = await authoring.get_build_attempt(
        access.workspace_id,
        build_attempt_id,
    )
    draft = await authoring.get_draft(
        access.workspace_id,
        build.draft_node_id,
    )
    releases = await authoring.list_releases(access.workspace_id)
    current_release = next(
        (
            release
            for release in releases
            if release.build_attempt_id == build.id
        ),
        None,
    )
    previous_release = max(
        (
            release
            for release in releases
            if release.draft_node_id == draft.id
            and release.build_attempt_id != build.id
        ),
        key=lambda release: release.revision,
        default=None,
    )
    try:
        review = await review_service.review(build, previous_release)
    except BuildReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    node_spec = NodeSpecResponse.from_agent_build(draft, build)
    if current_release is not None:
        resources = get_resources(request.app)
        node_spec = NodeSpecResponse.from_agent_release(
            current_release,
            runnable=agent_release_is_runnable(
                current_release,
                resources.plugin_registry,
                generated_execution_available=(
                    resources.generated_executor is not None
                ),
            ),
        )
    return BuildReviewResponse.from_review(
        review,
        build=build,
        node_spec=node_spec,
    )


@router.get(
    "/builds/{build_attempt_id}/review/files/{file_path:path}",
    response_model=BuildReviewFileContentResponse,
)
async def get_agent_build_review_file(
    build_attempt_id: UUID,
    file_path: str,
    authoring: AgentAuthoringDependency,
    review_service: BuildReviewDependency,
    access: EditGraphAccess,
) -> BuildReviewFileContentResponse:
    build = await authoring.get_build_attempt(
        access.workspace_id,
        build_attempt_id,
    )
    try:
        content = await review_service.file(build, file_path)
    except BuildReviewFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BuildReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BuildReviewFileContentResponse.from_content(content)


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunDetailResponse,
)
async def get_agent_run(
    run_id: UUID,
    authoring: AgentAuthoringDependency,
    access: ViewGraphAccess,
) -> AgentRunDetailResponse:
    run = await authoring.get_run(access.workspace_id, run_id)
    builds = await authoring.list_build_attempts(access.workspace_id, run_id)
    return AgentRunDetailResponse.from_run_and_builds(run, builds)


@router.delete(
    "/runs/{run_id}",
    response_model=AgentRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_agent_run(
    run_id: UUID,
    authoring: AgentAuthoringDependency,
    access: EditGraphAccess,
) -> AgentRunResponse:
    run = await authoring.cancel_run(
        workspace_id=access.workspace_id,
        run_id=run_id,
    )
    return AgentRunResponse.from_run(run)


@router.get(
    "/runs/{run_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Durable agent authoring events with replay",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream_agent_run_events(
    run_id: UUID,
    request: Request,
    authoring: AgentAuthoringDependency,
    access: ViewGraphAccess,
    last_event_id: Annotated[
        str | None,
        Header(alias="Last-Event-ID"),
    ] = None,
    after_sequence: Annotated[
        int | None,
        Query(ge=0, le=_MAX_EVENT_SEQUENCE),
    ] = None,
) -> StreamingResponse:
    header_sequence = _parse_last_event_id(last_event_id)
    if (
        last_event_id is not None
        and after_sequence is not None
        and header_sequence != after_sequence
    ):
        raise HTTPException(
            status_code=422,
            detail="after_sequence and Last-Event-ID must identify the same event",
        )
    event_cursor = after_sequence if after_sequence is not None else header_sequence
    run = await authoring.get_run(access.workspace_id, run_id)

    async def event_stream() -> AsyncIterator[str]:
        sequence = event_cursor
        empty_polls = 0
        while True:
            events = await authoring.list_events(
                workspace_id=access.workspace_id,
                thread_id=run.thread_id,
                after_sequence=sequence,
                limit=200,
            )
            if await request.is_disconnected():
                return
            for event in events:
                sequence = event.sequence
                if event.run_id != run_id:
                    continue
                response = AgentEventResponse.from_event(event)
                yield (
                    f"id: {event.sequence}\n"
                    f"event: {event.kind.value}\n"
                    f"data: {response.model_dump_json()}\n\n"
                )
            current_run = await authoring.get_run(access.workspace_id, run_id)
            if current_run.is_terminal and len(events) < 200:
                return
            if events:
                empty_polls = 0
                continue
            empty_polls += 1
            if empty_polls >= _HEARTBEAT_POLL_COUNT:
                empty_polls = 0
                yield ": heartbeat\n\n"
            await asyncio.sleep(_EVENT_POLL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/builds/{build_attempt_id}/approval",
    response_model=CapabilityApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def approve_agent_build(
    build_attempt_id: UUID,
    body: ApproveBuildRequest,
    authoring: AgentAuthoringDependency,
    access: EditGraphAccess,
) -> CapabilityApprovalResponse:
    try:
        approval = await authoring.approve_build(
            workspace_id=access.workspace_id,
            build_attempt_id=build_attempt_id,
            capability_digest=body.capability_digest,
            approved_by_user_id=access.actor.user_id,
        )
    except AgentAuthoringConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CapabilityApprovalResponse.from_approval(approval)


@router.post(
    "/builds/{build_attempt_id}/publish",
    response_model=PublishBuildResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_agent_build(
    build_attempt_id: UUID,
    body: PublishBuildRequest,
    request: Request,
    authoring: AgentAuthoringDependency,
    access: EditGraphAccess,
) -> PublishBuildResponse:
    resources = get_resources(request.app)
    command: UpdateNodeOperatorCommand | None = None
    head = None
    receipt = None
    try:
        async with SqlAlchemyUnitOfWork(resources.database.sessions) as unit_of_work:
            publication = await authoring.publish_build_in_unit_of_work(
                unit_of_work,
                workspace_id=access.workspace_id,
                build_attempt_id=build_attempt_id,
                capability_approval_id=body.capability_approval_id,
                published_by_user_id=access.actor.user_id,
            )
            promotion = body.graph_promotion
            if publication.release.revision == 1:
                if promotion is not None:
                    raise AgentAuthoringError(
                        "graph_promotion must be omitted for the first release"
                    )
            else:
                if promotion is None:
                    raise AgentAuthoringError(
                        "graph_promotion is required after the first release"
                    )
                if promotion.graph_id != publication.draft.graph_id:
                    raise AgentAuthoringError(
                        "graph_promotion.graph_id must match the draft graph"
                    )
                command = UpdateNodeOperatorCommand(
                    node_id=promotion.node_id,
                    operator_id=publication.release.operator_id,
                    operator_version=publication.release.operator_version,
                    expected_operator_id=publication.release.operator_id,
                    expected_operator_version=(
                        publication.release.operator_version - 1
                    ),
                )
                head, receipt = (
                    await resources.collaboration.accept_command_in_unit_of_work(
                        unit_of_work,
                        actor=access.actor,
                        workspace_id=access.workspace_id,
                        graph_id=promotion.graph_id,
                        command_id=promotion.command_id,
                        observed_sequence=promotion.observed_sequence,
                        observed_room_epoch=promotion.room_epoch,
                        command=command,
                    )
                )
            await unit_of_work.commit()
    except MissingCollaborativeHeadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollaborationCommandRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        AgentAuthoringConflictError,
        CollaborationHeadConflictError,
        CollaborationIdempotencyMismatchError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentAuthoringError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if (
        command is not None
        and receipt is not None
        and receipt.outcome is not CommandReceiptOutcome.IDEMPOTENT_REPLAY
    ):
        await publish_accepted_command(
            request,
            actor=access.actor,
            workspace_id=access.workspace_id,
            graph_id=publication.draft.graph_id,
            command=command,
            receipt=receipt,
        )
    response = PublishBuildResponse.from_release(
        publication.release,
        runnable=agent_release_is_runnable(
            publication.release,
            resources.plugin_registry,
            generated_execution_available=(resources.generated_executor is not None),
        ),
    )
    if head is not None and receipt is not None:
        response = response.model_copy(
            update={
                "head": CollaborativeHeadResponse.from_head(head),
                "receipt": GraphCommandReceiptResponse.from_receipt(receipt),
            }
        )
    return response


def _parse_last_event_id(value: str | None) -> int:
    if value is None:
        return 0
    normalized = value.strip()
    if normalized == "" or not normalized.isascii() or not normalized.isdigit():
        raise HTTPException(
            status_code=422,
            detail="Last-Event-ID must be a non-negative integer",
        )
    if len(normalized) > _MAX_EVENT_SEQUENCE_DIGITS:
        raise HTTPException(
            status_code=422,
            detail="Last-Event-ID exceeds the supported sequence range",
        )
    sequence = int(normalized)
    if sequence > _MAX_EVENT_SEQUENCE:
        raise HTTPException(
            status_code=422,
            detail="Last-Event-ID exceeds the supported sequence range",
        )
    return sequence


__all__ = ["router"]
