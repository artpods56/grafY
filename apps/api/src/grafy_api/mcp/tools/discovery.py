"""Who am I, and what can I build with: the Workspace and its node catalog."""

from typing import Annotated, Any, Final

from fastmcp.exceptions import ToolError
from grafy_client import CatalogPort
from pydantic import Field

from grafy_api.mcp.context import READ, dump, grafy, tool, type_label


def _port_summary(port: CatalogPort) -> str:
    accepted = (
        type_label(port.artifact_type)
        if port.artifact_type is not None
        else f"<{port.artifact_type_variable}>"
    )
    shape = port.shape.value
    optional = "" if port.required else "?"
    return f"{port.name}{optional}: {accepted} ({shape})"


async def get_workspace() -> dict[str, Any]:
    """The Workspace this token is bound to and the capabilities it holds there."""
    async with grafy() as (client, _workspace_id):
        return dump(await client.workspaces.current())


async def list_nodes(
    query: Annotated[
        str | None,
        Field(description="Case-insensitive filter on id, title, or description"),
    ] = None,
) -> list[dict[str, Any]]:
    """The node catalog: operator ids, versions, titles and port types."""
    async with grafy() as (client, workspace_id):
        catalog = await client.catalog.get(workspace_id)
    needle = None if query is None else query.lower()
    listed: list[dict[str, Any]] = []
    for node in catalog.nodes:
        if not node.catalog_visible:
            continue
        text = f"{node.operator_id} {node.title} {node.description}".lower()
        if needle is not None and needle not in text:
            continue
        listed.append(
            {
                "operator_id": node.operator_id,
                "operator_version": node.operator_version,
                "plugin_slug": node.plugin_slug,
                "title": node.title,
                "description": node.description[:300],
                "inputs": [_port_summary(port) for port in node.inputs],
                "outputs": [_port_summary(port) for port in node.outputs],
            }
        )
    return listed


async def describe_node(
    operator_id: str,
    operator_version: int | None = None,
) -> dict[str, Any]:
    """One node's full contract: config JSON Schema, ports, and conversions."""
    async with grafy() as (client, workspace_id):
        catalog = await client.catalog.get(workspace_id)
    matching = [
        node
        for node in catalog.nodes
        if node.operator_id == operator_id
        and (operator_version is None or node.operator_version == operator_version)
    ]
    if len(matching) != 1:
        raise ToolError(
            f"Catalog has {len(matching)} matches for {operator_id!r}; "
            "pass operator_version"
        )
    node = dump(matching[0])
    node["artifact_conversions"] = [
        dump(conversion) for conversion in catalog.artifact_conversions
    ]
    return node


async def list_packs() -> list[dict[str, Any]]:
    """Node packs in this deployment and whether the Workspace subscribes to each.

    A node of an unsubscribed pack is not in `list_nodes`; subscribing is an owner
    action in the Workbench.
    """
    async with grafy() as (client, workspace_id):
        catalog = await client.catalog.get(workspace_id)
    return [dump(pack) for pack in catalog.packs]


TOOLS: Final = (
    tool(get_workspace, READ, tags={"discovery"}),
    tool(list_nodes, READ, tags={"discovery"}),
    tool(describe_node, READ, tags={"discovery"}),
    tool(list_packs, READ, tags={"discovery"}),
)
