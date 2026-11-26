"""How a tool reaches Grafy: this API's own REST routes, in process, as the caller.

Every tool opens :func:`grafy` and calls ``grafy_client`` through it. The client
carries the caller's bearer header over an ASGI transport into this same app, so the
route that serves the call computes role ∩ PAT scope ∩ capability, reads the Project
under the token's Workspace, and publishes accepted batches to the room, exactly as
for any other client (ADR 0023). Nothing here grants anything the token lacks.
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any, Final, cast
from uuid import UUID

import httpx
from fastapi import FastAPI
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools import Tool
from grafy_client import GrafyClient, GrafyClientError, GraphBuilderError, ProjectHead
from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.identity import WorkspacePatPrincipal
from grafy_core.kernel.project import GraphDefinition
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, SecretStr

from grafy_api.mcp.http import API_APP_STATE_KEY, PRINCIPAL_STATE_KEY

# The in-process base URL: the ASGI transport never dials it, and the client only
# accepts plain HTTP for a loopback host.
_IN_PROCESS_BASE_URL: Final = "http://127.0.0.1"

READ: Final = ToolAnnotations(read_only_hint=True, open_world_hint=False)
"""Looks only; safe to call at any time."""
EDIT: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, open_world_hint=False
)
"""Changes Workspace state in a way the Workbench can show and undo."""
IDEMPOTENT_EDIT: Final = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
"""Sets a state; calling it again with the same arguments changes nothing."""
DESTRUCTIVE: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)
"""Removes something; a checkpoint restore (or nothing) brings it back."""


class ToolModel(BaseModel):
    """A tool argument object: unknown keys are a caller mistake, not ignored."""

    model_config = ConfigDict(extra="forbid")


def tool(
    function: Callable[..., Any],
    annotations: ToolAnnotations,
    *,
    tags: set[str],
) -> Tool:
    return Tool.from_function(function, annotations=annotations, tags=tags)


def dump(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


def type_key(value: str) -> ArtifactTypeKey:
    artifact_id, separator, version = value.rpartition("@")
    if not separator or not artifact_id or not version.isdigit():
        raise ToolError(f"Artifact type {value!r} must look like 'type.id@1'")
    return ArtifactTypeKey(id=artifact_id, schema_version=int(version))


def type_label(key: ArtifactTypeKey) -> str:
    return f"{key.id}@{key.schema_version}"


def graph_of(head: ProjectHead, graph_id: str) -> GraphDefinition:
    for graph in head.document.graphs:
        if graph.id == graph_id:
            return graph
    names = ", ".join(repr(graph.id) for graph in head.document.graphs)
    raise ToolError(f"Project has no graph {graph_id!r}; its graphs are {names}")


@asynccontextmanager
async def grafy() -> AsyncGenerator[tuple[GrafyClient, UUID]]:
    """A client that calls this API in process as the MCP caller, and its Workspace.

    Client and builder failures become tool errors the agent can read and correct;
    anything else is a crash the server reports without detail.
    """

    request = get_http_request()
    state = cast(dict[str, object], request.scope.get("state", {}))
    principal = cast(WorkspacePatPrincipal | None, state.get(PRINCIPAL_STATE_KEY))
    app = cast(FastAPI | None, state.get(API_APP_STATE_KEY))
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if principal is None or app is None or scheme.lower() != "bearer" or token == "":
        raise ToolError("This tool needs a bearer personal access token")
    client = GrafyClient(
        base_url=_IN_PROCESS_BASE_URL,
        token=SecretStr(token),
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
    )
    try:
        async with client:
            yield client, principal.workspace_id
    except GrafyClientError as exc:
        raise ToolError(str(exc)) from exc
    except GraphBuilderError as exc:
        raise ToolError(f"Graph is invalid: {exc}") from exc


__all__ = [
    "DESTRUCTIVE",
    "EDIT",
    "IDEMPOTENT_EDIT",
    "READ",
    "ToolModel",
    "dump",
    "grafy",
    "graph_of",
    "tool",
    "type_key",
    "type_label",
]
