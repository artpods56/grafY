"""The Grafy MCP server: a FastMCP server whose tools act as the caller through REST.

Every tool is a thin call through ``grafy_client`` into this API's own routes, in
process over ASGI, with the caller's bearer token (``grafy_api.mcp.context``). That
is the whole security model: the route that serves a call computes role ∩ PAT
scope ∩ capability, reads the Project under the token's Workspace, applies a
command batch against the live head and publishes it to the room, exactly as it
does for any other client. A tool cannot reach a service the REST surface does not
expose, and a missing capability is the route's 403, relayed.

The tool set follows what a person can do in the Workbench: find and file
Projects, edit a canvas gesture by gesture, run, read results, keep them in the
Library, manage node secrets, and talk to canvas Agents. Tools take the Workspace
from the token, never from an argument: a PAT is bound to one Workspace (ADR 0003).
"""

import json
from typing import Final
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.prompts import Message

from grafy_api.mcp.context import grafy
from grafy_api.mcp.tools import (
    agents,
    artifacts,
    authoring,
    canvas,
    discovery,
    library,
    projects,
    runs,
    secrets,
)

INSTRUCTIONS: Final = """\
Grafy is a typed artifact-graph workbench. A Workspace holds Projects; a Project holds
named Graphs of nodes wired output -> input, plus cards, annotations and Agents on
the canvas, and the results its nodes produced. Your token is bound to one Workspace;
every tool acts there, with that token's permissions.

Find things: get_workspace, list_projects, list_nodes, describe_node.
Build a whole Graph at once: author_graph. Edit an existing canvas the way a person
does: get_canvas (ids and positions), then add_nodes, connect, configure_node,
place_artifacts, add_card, move_items, resize_item, remove_items, arrange_graph,
add_annotation. Every edit is validated and applied as the Workbench's own
commands, live for anyone watching the canvas.
Run and read: start_run -> wait_for_run -> get_instance_result -> read_table_page /
get_geo_render / read_artifact_text. Files: upload_file, list_library.
Undo: checkpoint_project records a restore point; restore_checkpoint goes back.
Artifacts are referenced by id plus type `id@version` (for example `file.csv@1`).
Canvas coordinates grow right and down; a node is about 300 x 200.
"""

TOOL_MODULES: Final = (
    discovery,
    projects,
    authoring,
    canvas,
    runs,
    library,
    artifacts,
    secrets,
    agents,
)


async def node_catalog() -> str:
    """Every node the Workspace can use, with its ports."""
    return json.dumps(await discovery.list_nodes())


async def graph_canvas(project_id: str, graph_id: str) -> str:
    """One Graph's canvas, as get_canvas returns it."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, UUID(project_id))
    return json.dumps(canvas.canvas_view(head, graph_id))


def build_graph_prompt(goal: str) -> list[Message]:
    """Plan and build a Graph for a goal, then run it and check it."""
    return [
        Message(
            f"Build a Grafy Graph for this goal: {goal}\n\n"
            "1. list_nodes (filter by keywords) and describe_node for the ones you "
            "need; check that port types line up.\n"
            "2. create_project, then author_graph with every node, connection and "
            "an output card on each result you want to see.\n"
            "3. start_run and wait_for_run; on failure read the instance error with "
            "list_instances, fix it with configure_node or connect, and run again.\n"
            "4. Read the results (get_instance_result, read_table_page, ...), "
            "arrange_graph for a tidy canvas, and checkpoint_project."
        )
    ]


def build_mcp_server() -> FastMCP:
    server = FastMCP(
        name="grafy",
        instructions=INSTRUCTIONS,
        # An unexpected failure reports no internals; tool errors keep their text.
        mask_error_details=True,
        # Arguments are checked against each tool's schema, not coerced into it.
        strict_input_validation=True,
    )
    for module in TOOL_MODULES:
        for tool in module.TOOLS:
            _ = server.add_tool(tool)
    _ = server.resource(
        "grafy://catalog", name="node-catalog", mime_type="application/json"
    )(node_catalog)
    _ = server.resource(
        "grafy://projects/{project_id}/graphs/{graph_id}/canvas",
        name="graph-canvas",
        mime_type="application/json",
    )(graph_canvas)
    _ = server.prompt(name="build-graph")(build_graph_prompt)
    return server


__all__ = ["INSTRUCTIONS", "build_mcp_server"]
