"""Runs and node instances: make results fresh, watch them, read them."""

from typing import Annotated, Any, Final
from uuid import UUID

from grafy_client import ExecutionTimeoutError, RunTarget
from grafy_core.domain.collaboration import RefreshNodeCommand
from pydantic import Field

from grafy_api.mcp.context import (
    EDIT,
    IDEMPOTENT_EDIT,
    READ,
    ToolModel,
    dump,
    grafy,
    graph_of,
    tool,
)

_RUN_POLL_SECONDS: Final = 0.5
_MAX_WAIT_SECONDS: Final = 300.0


class RunTargetSpec(ToolModel):
    node_id: str
    call_path: list[str] = Field(default_factory=list)


async def start_run(
    project_id: UUID,
    graph_id: str,
    targets: Annotated[
        list[RunTargetSpec] | None,
        Field(description="Nodes to make fresh; default every node of the Graph"),
    ] = None,
) -> dict[str, Any]:
    """Start a Run; only the stale part of the targets' upstream is computed."""
    async with grafy() as (client, workspace_id):
        run = await client.runs.start(
            workspace_id,
            project_id,
            graph_id=graph_id,
            targets=[
                RunTarget(node_id=target.node_id, call_path=tuple(target.call_path))
                for target in targets or []
            ],
        )
    return dump(run)


async def get_run(project_id: UUID, run_id: UUID) -> dict[str, Any]:
    """A Run's status and error, if any."""
    async with grafy() as (client, workspace_id):
        return dump(await client.runs.get(workspace_id, project_id, run_id))


async def list_runs(
    project_id: UUID,
    active: Annotated[bool, Field(description="Only Runs still in flight")] = False,
) -> list[dict[str, Any]]:
    """Runs of a Project, newest first."""
    async with grafy() as (client, workspace_id):
        runs = await client.runs.list(workspace_id, project_id, active=active)
    return [dump(run) for run in runs]


async def wait_for_run(
    project_id: UUID,
    run_id: UUID,
    timeout_seconds: Annotated[float, Field(gt=0, le=_MAX_WAIT_SECONDS)] = 60.0,
) -> dict[str, Any]:
    """Wait until a Run finishes or the timeout passes, then report its status."""
    async with grafy() as (client, workspace_id):
        try:
            run = await client.runs.wait(
                workspace_id,
                project_id,
                run_id,
                timeout=timeout_seconds,
                poll_interval=_RUN_POLL_SECONDS,
            )
        except ExecutionTimeoutError:
            run = await client.runs.get(workspace_id, project_id, run_id)
    return dump(run)


async def cancel_run(project_id: UUID, run_id: UUID) -> dict[str, Any]:
    """Withdraw a Run's demand; shared computations keep running for others."""
    async with grafy() as (client, workspace_id):
        return dump(await client.runs.cancel(workspace_id, project_id, run_id))


async def list_instances(project_id: UUID, graph_id: str) -> list[dict[str, Any]]:
    """Every node instance of a Graph with its state: fresh, stale, running..."""
    async with grafy() as (client, workspace_id):
        states = await client.runs.instances(workspace_id, project_id, graph_id)
    return [dump(state) for state in states]


async def get_instance_result(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    call_path: list[str] | None = None,
) -> dict[str, Any]:
    """A node's last result: output artifact references per port (may be stale)."""
    async with grafy() as (client, workspace_id):
        result = await client.runs.instance_result(
            workspace_id,
            project_id,
            graph_id=graph_id,
            node_id=node_id,
            call_path=call_path or [],
        )
    return dump(result)


async def refresh_node(project_id: UUID, graph_id: str, node_id: str) -> dict[str, Any]:
    """Mark a non-deterministic node (an LLM call, a live fetch) stale on purpose.

    The Workbench's refresh button: the node's next Run computes it again even
    though nothing upstream changed. Start a Run afterwards to get the new result.
    """
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        generation = graph_of(head, graph_id).refresh_generations.get(node_id, 0)
        submitted = await client.projects.submit_commands(
            workspace_id,
            project_id,
            head=head,
            commands=[
                RefreshNodeCommand(
                    graph_id=graph_id,
                    node_id=node_id,
                    expected_generation=generation,
                )
            ],
        )
    return {
        "refresh_generation": generation + 1,
        "collaboration_sequence": submitted.head.collaboration_sequence,
    }


TOOLS: Final = (
    tool(start_run, EDIT, tags={"runs"}),
    tool(get_run, READ, tags={"runs"}),
    tool(list_runs, READ, tags={"runs"}),
    tool(wait_for_run, READ, tags={"runs"}),
    tool(cancel_run, IDEMPOTENT_EDIT, tags={"runs"}),
    tool(list_instances, READ, tags={"runs"}),
    tool(get_instance_result, READ, tags={"runs"}),
    tool(refresh_node, EDIT, tags={"runs"}),
)
