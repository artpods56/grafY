"""Projects and the Graphs inside them: create, find, rename, file, and move between
deployments."""

from typing import Annotated, Any, Final, cast
from uuid import UUID

from fastmcp.exceptions import ToolError
from grafy_client import ProjectHead
from grafy_core.domain.collaboration import (
    AddGraphCommand,
    ProjectCommand,
    RemoveGraphCommand,
    RenameGraphCommand,
    RenameProjectCommand,
)
from pydantic import Field

from grafy_api.mcp.context import (
    DESTRUCTIVE,
    EDIT,
    IDEMPOTENT_EDIT,
    READ,
    dump,
    grafy,
    graph_of,
    tool,
)


def _head_summary(head: ProjectHead) -> dict[str, Any]:
    return {
        "project_id": str(head.project_id),
        "collaboration_sequence": head.collaboration_sequence,
        "checkpoint_revision": head.checkpoint_revision,
        "graphs": [
            {"id": graph.id, "name": graph.name} for graph in head.document.graphs
        ],
    }


async def _submit(project_id: UUID, *commands: ProjectCommand) -> dict[str, Any]:
    async with grafy() as (client, workspace_id):
        submitted = await client.projects.apply(workspace_id, project_id, commands)
    return _head_summary(submitted.head)


async def list_projects() -> list[dict[str, Any]]:
    """Projects in the Workspace, with counts describing their live heads."""
    async with grafy() as (client, workspace_id):
        return [dump(item) for item in await client.projects.list(workspace_id)]


async def create_project(
    name: str,
    graph_id: str = "main",
    graph_name: str = "Main",
) -> dict[str, Any]:
    """Create a Project holding one empty Graph."""
    async with grafy() as (client, workspace_id):
        project = await client.projects.create(
            workspace_id, name=name, graph_id=graph_id, graph_name=graph_name
        )
        return dump(project)


async def get_project(
    project_id: UUID,
    graph_id: Annotated[
        str | None, Field(description="Return only this Graph's document")
    ] = None,
) -> dict[str, Any]:
    """The live head of a Project: sequences, checkpoint revision, Graph documents.

    For a compact view of one Graph's canvas (positions, wiring, cards) use
    `get_canvas` instead.
    """
    async with grafy() as (client, workspace_id):
        head = dump(await client.projects.head(workspace_id, project_id))
    if graph_id is not None:
        document = cast(dict[str, Any], head["document"])
        graphs = cast(list[dict[str, Any]], document["graphs"])
        document["graphs"] = [graph for graph in graphs if graph["id"] == graph_id]
        if not document["graphs"]:
            raise ToolError(f"Project has no graph {graph_id!r}")
    return head


async def rename_project(project_id: UUID, name: str) -> dict[str, Any]:
    """Give a Project a new name."""
    async with grafy() as (client, workspace_id):
        project = await client.projects.get(workspace_id, project_id)
    return await _submit(
        project_id, RenameProjectCommand(name=name, expected_name=project.name)
    )


async def add_graph(project_id: UUID, graph_id: str, name: str) -> dict[str, Any]:
    """Add an empty Graph to a Project. A Graph can be called from another as a
    node (`add_call_node`), the way a function is."""
    return await _submit(project_id, AddGraphCommand(graph_id=graph_id, name=name))


async def rename_graph(project_id: UUID, graph_id: str, name: str) -> dict[str, Any]:
    """Give one Graph of a Project a new name; its id stays."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
    current = graph_of(head, graph_id)
    return await _submit(
        project_id,
        RenameGraphCommand(graph_id=graph_id, name=name, expected_name=current.name),
    )


async def remove_graph(project_id: UUID, graph_id: str) -> dict[str, Any]:
    """Remove a Graph from a Project. Refused while another Graph calls it.

    A checkpoint restore brings it back.
    """
    return await _submit(project_id, RemoveGraphCommand(graph_id=graph_id))


async def export_project(
    project_id: UUID,
    revision: Annotated[
        int | None,
        Field(ge=0, description="A checkpoint revision; default the live head"),
    ] = None,
) -> dict[str, Any]:
    """The whole Project as portable JSON, secrets stripped, for `import_project`."""
    async with grafy() as (client, workspace_id):
        exported = await client.projects.export_project(
            workspace_id, project_id, revision=revision
        )
    return dump(exported)


async def import_project(
    export: Annotated[
        dict[str, Any], Field(description="The JSON `export_project` returned")
    ],
    name: str | None = None,
) -> dict[str, Any]:
    """Create a new Project from a portable export (any Workspace or deployment)."""
    async with grafy() as (client, workspace_id):
        imported = await client.projects.import_project(workspace_id, export, name=name)
    return dump(imported)


async def copy_project(
    project_id: UUID,
    name: Annotated[str | None, Field(description="Default: '<name> copy'")] = None,
) -> dict[str, Any]:
    """Make an independent copy of a Project's live head, the browser's Duplicate."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        copied = await client.projects.copy(
            workspace_id, project_id, head=head, name=name
        )
    return dump(copied)


async def archive_project(project_id: UUID) -> dict[str, Any]:
    """Move a Project out of the active list. `unarchive_project` brings it back."""
    async with grafy() as (client, workspace_id):
        return dump(await client.projects.archive(workspace_id, project_id))


async def unarchive_project(project_id: UUID) -> dict[str, Any]:
    """Return an archived Project to the active list."""
    async with grafy() as (client, workspace_id):
        return dump(await client.projects.unarchive(workspace_id, project_id))


async def star_project(project_id: UUID, starred: bool = True) -> dict[str, Any]:
    """Star (or unstar) a Project for yourself; stars are never shared."""
    async with grafy() as (client, workspace_id):
        if starred:
            return dump(await client.projects.star(workspace_id, project_id))
        return dump(await client.projects.unstar(workspace_id, project_id))


async def list_project_folders() -> list[dict[str, Any]]:
    """The Workspace's Project folders (one level, shared by all members)."""
    async with grafy() as (client, workspace_id):
        return [dump(item) for item in await client.projects.list_folders(workspace_id)]


async def create_project_folder(name: str) -> dict[str, Any]:
    """Create a Project folder."""
    async with grafy() as (client, workspace_id):
        return dump(await client.projects.create_folder(workspace_id, name=name))


async def rename_project_folder(folder_id: UUID, name: str) -> dict[str, Any]:
    """Rename a Project folder."""
    async with grafy() as (client, workspace_id):
        return dump(
            await client.projects.rename_folder(workspace_id, folder_id, name=name)
        )


async def delete_project_folder(folder_id: UUID) -> dict[str, Any]:
    """Delete a Project folder; its Projects become Unfiled, none is deleted."""
    async with grafy() as (client, workspace_id):
        await client.projects.delete_folder(workspace_id, folder_id)
    return {"deleted": str(folder_id)}


async def file_project(
    project_id: UUID,
    folder_id: Annotated[
        UUID | None, Field(description="The folder, or null for Unfiled")
    ],
) -> dict[str, Any]:
    """Put a Project in a folder, or take it out of one."""
    async with grafy() as (client, workspace_id):
        return dump(
            await client.projects.assign_folder(
                workspace_id, project_id, folder_id=folder_id
            )
        )


async def list_checkpoints(project_id: UUID) -> list[dict[str, Any]]:
    """A Project's checkpoint history, its restore points, newest first."""
    async with grafy() as (client, workspace_id):
        checkpoints = await client.projects.list_checkpoints(workspace_id, project_id)
    return [dump(checkpoint) for checkpoint in checkpoints]


async def get_checkpoint(project_id: UUID, revision: int) -> dict[str, Any]:
    """One checkpoint with the whole Project document as it was then."""
    async with grafy() as (client, workspace_id):
        return dump(
            await client.projects.get_checkpoint(workspace_id, project_id, revision)
        )


async def restore_checkpoint(project_id: UUID, revision: int) -> dict[str, Any]:
    """Make an earlier checkpoint the live head again: the undo for any edit.

    Edits made since the last checkpoint are checkpointed first, so nothing is lost:
    restoring that newer revision redoes them.
    """
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        saved_revision: int | None = None
        if head.collaboration_sequence != head.checkpoint_sequence:
            head = await client.projects.checkpoint(workspace_id, project_id, head=head)
            saved_revision = head.checkpoint_revision
        restored = await client.projects.restore_checkpoint(
            workspace_id, project_id, revision, head=head
        )
    return {**_head_summary(restored), "saved_edits_as_revision": saved_revision}


TOOLS: Final = (
    tool(list_projects, READ, tags={"projects"}),
    tool(create_project, EDIT, tags={"projects"}),
    tool(get_project, READ, tags={"projects"}),
    tool(rename_project, IDEMPOTENT_EDIT, tags={"projects"}),
    tool(add_graph, EDIT, tags={"projects"}),
    tool(rename_graph, IDEMPOTENT_EDIT, tags={"projects"}),
    tool(remove_graph, DESTRUCTIVE, tags={"projects"}),
    tool(export_project, READ, tags={"projects"}),
    tool(import_project, EDIT, tags={"projects"}),
    tool(copy_project, EDIT, tags={"projects"}),
    tool(archive_project, IDEMPOTENT_EDIT, tags={"projects"}),
    tool(unarchive_project, IDEMPOTENT_EDIT, tags={"projects"}),
    tool(star_project, IDEMPOTENT_EDIT, tags={"projects"}),
    tool(list_project_folders, READ, tags={"projects", "folders"}),
    tool(create_project_folder, EDIT, tags={"projects", "folders"}),
    tool(rename_project_folder, IDEMPOTENT_EDIT, tags={"projects", "folders"}),
    tool(delete_project_folder, DESTRUCTIVE, tags={"projects", "folders"}),
    tool(file_project, IDEMPOTENT_EDIT, tags={"projects", "folders"}),
    tool(list_checkpoints, READ, tags={"projects", "history"}),
    tool(get_checkpoint, READ, tags={"projects", "history"}),
    tool(restore_checkpoint, EDIT, tags={"projects", "history"}),
)
