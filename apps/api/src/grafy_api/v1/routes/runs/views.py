"""Run HTTP routes: the demand side of a Project (ADR 0020).

Six routes, all under one Project, and all of them read the Project before the Run
service: a Run is a demand over a document, so a request that names no Project of
this Workspace has nothing to demand.

* ``POST /projects/{project_id}/runs`` starts a Run for a Graph and its targets.
* ``GET  /projects/{project_id}/runs`` lists Runs, ``?active=true`` for the ones
  still running, which is also what the room carries in ``room.ready``.
* ``GET  /projects/{project_id}/runs/{run_id}`` reads one Run.
* ``POST /projects/{project_id}/runs/{run_id}/cancel`` withdraws one Run's demand.
* ``GET  /projects/{project_id}/graphs/{graph_id}/instances`` reads derived state.
* ``GET  /projects/{project_id}/instance-result`` reads what one instance last
  produced, which may be older than the document — that is what keeps a stale node
  showing something.

There is no "the active execution" here: any number of Runs are active in one
Project at once, and a Run neither holds the document nor locks anyone else out.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from grafy_core.domain.identity import WorkspaceCapability
from grafy_core.kernel.instances import InstanceKey

from grafy_api.runs.ports import RunRejectedError
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability
from grafy_api.v1.routes.runs.dependencies import (
    ProjectScopeDependency,
    RunServiceDependency,
)
from grafy_api.v1.routes.runs.models import (
    InstanceResultResponse,
    InstanceStateListResponse,
    InstanceStateResponse,
    RunListResponse,
    RunResponse,
    StartRunRequest,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["runs"])


def _rejected(exc: RunRejectedError) -> HTTPException:
    """A rejected Run as 422, with the machine-readable code the service chose.

    ``code`` is the stable half: ``unknown_graph``, ``unknown_target``,
    ``unknown_operator``, ``invalid_document``. The message is for a human and may
    be reworded, so a client branches on the code alone.
    """

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.post("/projects/{project_id}/runs", status_code=status.HTTP_201_CREATED)
async def start_run(
    project_id: UUID,
    payload: StartRunRequest,
    project: ProjectScopeDependency,
    runs: RunServiceDependency,
    access: require_workspace_capability(WorkspaceCapability.START_RUN),
) -> RunResponse:
    """Ask for a Graph's targets to become fresh, and start satisfying the demand."""

    try:
        run = await runs.start(
            workspace_id=project.workspace_id,
            project_id=project.id,
            graph_id=payload.graph_id,
            targets=tuple(target.to_target() for target in payload.targets),
            started_by_user_id=access.actor.user_id,
        )
    except RunRejectedError as exc:
        raise _rejected(exc) from exc
    return RunResponse.from_run(run)


@router.get("/projects/{project_id}/runs")
async def list_runs(
    project_id: UUID,
    project: ProjectScopeDependency,
    runs: RunServiceDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_RUNS),
    active: Annotated[
        bool, Query(description="Only the Runs still active in this Project.")
    ] = False,
) -> RunListResponse:
    listed = await runs.list_runs(
        workspace_id=project.workspace_id,
        project_id=project.id,
        active_only=active,
    )
    return RunListResponse(runs=[RunResponse.from_run(run) for run in listed])


@router.get("/projects/{project_id}/runs/{run_id}")
async def get_run(
    project_id: UUID,
    run_id: UUID,
    project: ProjectScopeDependency,
    runs: RunServiceDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_RUNS),
) -> RunResponse:
    run = await runs.get_run(
        workspace_id=project.workspace_id,
        project_id=project.id,
        run_id=run_id,
    )
    return RunResponse.from_run(run)


@router.post("/projects/{project_id}/runs/{run_id}/cancel")
async def cancel_run(
    project_id: UUID,
    run_id: UUID,
    project: ProjectScopeDependency,
    runs: RunServiceDependency,
    access: require_workspace_capability(WorkspaceCapability.CANCEL_RUN),
) -> RunResponse:
    """Withdraw one Run's demand; a computation another Run still needs goes on."""

    run = await runs.cancel(
        workspace_id=project.workspace_id,
        project_id=project.id,
        run_id=run_id,
    )
    return RunResponse.from_run(run)


@router.get("/projects/{project_id}/graphs/{graph_id}/instances")
async def list_graph_instances(
    project_id: UUID,
    graph_id: str,
    project: ProjectScopeDependency,
    runs: RunServiceDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_RUNS),
) -> InstanceStateListResponse:
    """Derived state for every instance of one Graph: fresh, queued, running,
    failed or stale. Nothing here is stored; it is read off the document, the
    result store and what this API owner has in flight."""

    try:
        snapshots = await runs.instance_states(
            workspace_id=project.workspace_id,
            project_id=project.id,
            graph_id=graph_id,
        )
    except RunRejectedError as exc:
        raise _rejected(exc) from exc
    return InstanceStateListResponse(
        instances=[
            InstanceStateResponse.from_snapshot(snapshot) for snapshot in snapshots
        ]
    )


@router.get("/projects/{project_id}/instance-result")
async def get_instance_result(
    project_id: UUID,
    project: ProjectScopeDependency,
    runs: RunServiceDependency,
    runs_access: require_workspace_capability(WorkspaceCapability.VIEW_RUNS),
    artifacts_access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
    graph_id: Annotated[str, Query(min_length=1)],
    node_id: Annotated[str, Query(min_length=1)],
    call_path: Annotated[
        tuple[str, ...],
        Query(
            description=(
                "The call path of the callee, one repeated parameter per call node, "
                "in call order. Empty for an instance of the root Graph."
            )
        ),
    ] = (),
) -> InstanceResultResponse:
    """One instance's state and the last result it produced, possibly stale.

    Outputs are artifact references and inline values, so this route demands
    ``view_artifacts`` as well as ``view_runs``: the first says you may see that an
    instance ran, the second that you may read what it handed back. Both go through
    ``require_workspace_capability`` rather than one check plus ``access.require``,
    because a Personal Access Token's scope is only consulted on that path — a
    narrower token must not reach outputs its scope leaves out.
    """

    del runs_access, artifacts_access
    key = InstanceKey(
        project_id=str(project.id),
        graph_id=graph_id,
        call_path=tuple(call_path),
        node_id=node_id,
    )
    try:
        snapshot, result = await runs.instance_result(
            workspace_id=project.workspace_id,
            project_id=project.id,
            key=key,
        )
    except RunRejectedError as exc:
        raise _rejected(exc) from exc
    return InstanceResultResponse.from_result(snapshot, result)


__all__ = ["router"]
