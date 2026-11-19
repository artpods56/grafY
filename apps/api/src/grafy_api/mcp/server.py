"""MCP tools for external agents: discover, author, run, and inspect Projects.

Every tool is a thin call through ``grafy_client`` into this API's own REST routes,
in process over ASGI, with the caller's bearer token. That is the whole security
model: the route that serves a call computes role ∩ PAT scope ∩ capability, reads the
Project under the token's Workspace, applies a command batch against the live head
and publishes it to the room, exactly as it does for any other client. A tool cannot
reach a service the REST surface does not expose, and a missing capability is the
route's 403, relayed.

Tools take the Workspace from the token, never from an argument: a PAT is bound to
one Workspace (ADR 0003), so there is nothing for the caller to choose.
"""

import base64
import binascii
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Any, Final, Literal, cast
from uuid import UUID

import httpx
from fastapi import FastAPI
from grafy_client import (
    CardHandle,
    CatalogPort,
    ExecutionTimeoutError,
    GrafyClient,
    GrafyClientError,
    GraphBuilder,
    GraphBuilderError,
    NodeHandle,
    RunTarget,
)
from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.domain.collaboration import PROJECT_COMMAND_ADAPTER, ProjectCommand
from grafy_core.domain.graph_documents import GraphConversion, GraphPoint
from grafy_core.domain.identity import WorkspacePatPrincipal
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from starlette.requests import Request

from grafy_api.mcp.http import PRINCIPAL_STATE_KEY

# The in-process base URL: the ASGI transport never dials it, and the client only
# accepts plain HTTP for a loopback host.
_IN_PROCESS_BASE_URL: Final = "http://127.0.0.1"
_RUN_POLL_SECONDS: Final = 0.5
_MAX_WAIT_SECONDS: Final = 300.0
_MAX_TEXT_BYTES: Final = 256 * 1024
_MAX_INLINE_UPLOAD_BYTES: Final = 2 * 1024 * 1024

INSTRUCTIONS: Final = """\
Grafy is a typed artifact-graph workbench. A Workspace holds Projects; a Project holds
named Graphs of nodes and edges, and the results its nodes produced. Your token is
bound to one Workspace; every tool acts there.

Typical flow: get_workspace -> list_nodes / describe_node -> create_project ->
author_graph (validated against the node catalog, then checkpointed) -> start_run ->
wait_for_run -> get_instance_result -> read_table_page / get_geo_render.
Artifacts are referenced by id plus type `id@version` (for example `file.csv@1`).
Every change is a validated command batch on the live Project head; a checkpoint
restore in the Workbench undoes it.
"""


class _ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortRef(_ToolModel):
    node: str = Field(description="Node id within the graph")
    port: str = Field(description="Port name on that node")


class ArtifactSpec(_ToolModel):
    artifact_id: UUID
    artifact_type: str = Field(
        description="Artifact type with version, for example 'file.tiff@1'"
    )
    content_hash: str | None = Field(
        default=None,
        description=(
            "The artifact's sha256 (`artifact.sha256` in list_library). Omit it for "
            "a Library artifact and it is looked up"
        ),
    )


class NodeSpec(_ToolModel):
    id: str = Field(description="Node id, unique within the graph")
    operator_id: str
    operator_version: int | None = Field(
        default=None, description="Pin a version; default: the only one in catalog"
    )
    config: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, str] = Field(
        default_factory=dict,
        description="Artifact type variable bindings, variable -> 'type@version'",
    )
    x: float | None = None
    y: float | None = None


class ConversionSpec(_ToolModel):
    id: str
    version: int = Field(ge=1)


class ConnectionSpec(_ToolModel):
    source: PortRef
    target: PortRef
    collection_mode: Literal["direct", "map"] = "direct"
    conversion_path: list[ConversionSpec] = Field(default_factory=list)


class OriginSpec(_ToolModel):
    """A stored artifact (or ordered list of them) fed straight into an input."""

    target: PortRef
    artifacts: list[ArtifactSpec] = Field(
        min_length=1,
        description="One artifact, or several to form an ordered sequence",
    )
    as_sequence: bool = Field(
        default=False, description="Pass a single artifact as a one-item sequence"
    )
    card: str | None = Field(
        default=None, description="Id of a library card in `cards` that owns it"
    )
    collection_mode: Literal["direct", "map"] = "direct"
    conversion_path: list[ConversionSpec] = Field(default_factory=list)


class CardSpec(_ToolModel):
    """An artifact card: shows a stored artifact, or follows one node output."""

    id: str = Field(description="Card id; must start with 'artifact-viewer-'")
    artifacts: list[ArtifactSpec] = Field(
        default_factory=list, description="Library card content"
    )
    follows: PortRef | None = Field(
        default=None, description="Output card: the node output it shows"
    )
    projection: list[str] = Field(
        default_factory=list, description="Nested field path shown by an output card"
    )
    x: float | None = None
    y: float | None = None


class CardBindingSpec(_ToolModel):
    """Selecting rows or features on one card filters/highlights another."""

    source_card: str
    target_card: str
    fields: dict[str, str] = Field(
        min_length=1, description="source field -> target field that must be equal"
    )
    effects: list[Literal["filter", "highlight", "focus"]] = Field(
        default_factory=lambda: ["highlight", "focus"], min_length=1
    )


class RunTargetSpec(_ToolModel):
    node_id: str
    call_path: list[str] = Field(default_factory=list)


def _type_key(value: str) -> ArtifactTypeKey:
    artifact_id, separator, version = value.rpartition("@")
    if not separator or not artifact_id or not version.isdigit():
        raise ToolError(f"Artifact type {value!r} must look like 'type.id@1'")
    return ArtifactTypeKey(id=artifact_id, schema_version=int(version))


type _Hashes = Mapping[UUID, str | None]


def _artifact_ref(spec: ArtifactSpec, hashes: _Hashes) -> ArtifactRef:
    """The exact reference: an origin naming a different hash is not the artifact."""
    content_hash = spec.content_hash
    if content_hash is None:
        if spec.artifact_id not in hashes:
            raise ToolError(
                f"Artifact {spec.artifact_id} is not in the Library; pass its "
                "content_hash"
            )
        content_hash = hashes[spec.artifact_id]
    return ArtifactRef.from_key(
        artifact_id=spec.artifact_id,
        key=_type_key(spec.artifact_type),
        content_hash=content_hash,
    )


def _artifact_value(
    specs: list[ArtifactSpec], hashes: _Hashes, *, as_sequence: bool
) -> ArtifactRef | ArtifactRefSequence:
    refs = [_artifact_ref(spec, hashes) for spec in specs]
    if len(refs) == 1 and not as_sequence:
        return refs[0]
    key = _type_key(specs[0].artifact_type)
    for spec in specs[1:]:
        if _type_key(spec.artifact_type) != key:
            raise ToolError("Every artifact in one sequence must share its type")
    return ArtifactRefSequence.from_key(key=key, item_refs=refs)


def _needs_library_hashes(
    cards: list[CardSpec] | None, origins: list[OriginSpec] | None
) -> bool:
    for spec in [*(cards or []), *(origins or [])]:
        for artifact in spec.artifacts:
            if artifact.content_hash is None:
                return True
    return False


def _point(x: float | None, y: float | None) -> GraphPoint | None:
    if x is None or y is None:
        return None
    return GraphPoint(x=x, y=y)


def _dump(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


@asynccontextmanager
async def _grafy(ctx: Context) -> AsyncIterator[tuple[GrafyClient, UUID]]:
    """A client that calls this API in process as the MCP caller, and its Workspace.

    Client and builder failures become tool errors the agent can read and correct;
    anything else is a crash the SDK reports without detail.
    """

    request = cast(Request, ctx.request_context.request)
    principal = cast(
        WorkspacePatPrincipal | None,
        request.scope.get("state", {}).get(PRINCIPAL_STATE_KEY),
    )
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if principal is None or scheme.lower() != "bearer" or token == "":
        raise ToolError("This tool needs a bearer personal access token")
    app = cast(FastAPI, request.app)
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


def _add_nodes(builder: GraphBuilder, nodes: list[NodeSpec]) -> dict[str, NodeHandle]:
    handles: dict[str, NodeHandle] = {}
    for spec in nodes:
        handles[spec.id] = builder.add_catalog_node(
            spec.operator_id,
            spec.config,
            operator_version=spec.operator_version,
            bindings={name: _type_key(value) for name, value in spec.bindings.items()},
            position=_point(spec.x, spec.y),
            node_id=spec.id,
        )
    return handles


def _node(handles: Mapping[str, NodeHandle], ref: PortRef) -> NodeHandle:
    handle = handles.get(ref.node)
    if handle is None:
        raise ToolError(f"No node {ref.node!r} in this graph spec")
    return handle


def _conversions(specs: list[ConversionSpec]) -> tuple[GraphConversion, ...]:
    return tuple(GraphConversion(id=spec.id, version=spec.version) for spec in specs)


def _card(cards: Mapping[str, CardHandle], card_id: str) -> CardHandle:
    card = cards.get(card_id)
    if card is None:
        raise ToolError(f"No card {card_id!r} in this graph spec")
    return card


async def get_workspace(ctx: Context) -> dict[str, Any]:
    """The Workspace this token is bound to and the capabilities it holds there."""
    async with _grafy(ctx) as (grafy, _workspace_id):
        return _dump(await grafy.workspaces.current())


async def list_projects(ctx: Context) -> list[dict[str, Any]]:
    """Projects in the Workspace, with counts describing their live heads."""
    async with _grafy(ctx) as (grafy, workspace_id):
        return [_dump(item) for item in await grafy.projects.list(workspace_id)]


async def create_project(
    ctx: Context,
    name: str,
    graph_id: str = "main",
    graph_name: str = "Main",
) -> dict[str, Any]:
    """Create a Project holding one empty Graph."""
    async with _grafy(ctx) as (grafy, workspace_id):
        project = await grafy.projects.create(
            workspace_id, name=name, graph_id=graph_id, graph_name=graph_name
        )
        return _dump(project)


async def get_project(
    ctx: Context,
    project_id: UUID,
    graph_id: Annotated[
        str | None, Field(description="Return only this Graph's document")
    ] = None,
) -> dict[str, Any]:
    """The live head of a Project: sequences, checkpoint revision, Graph documents."""
    async with _grafy(ctx) as (grafy, workspace_id):
        head = _dump(await grafy.projects.head(workspace_id, project_id))
    if graph_id is not None:
        document = cast(dict[str, Any], head["document"])
        graphs = cast(list[dict[str, Any]], document["graphs"])
        document["graphs"] = [graph for graph in graphs if graph["id"] == graph_id]
        if not document["graphs"]:
            raise ToolError(f"Project has no graph {graph_id!r}")
    return head


async def list_nodes(
    ctx: Context,
    query: Annotated[
        str | None,
        Field(description="Case-insensitive filter on id, title, or description"),
    ] = None,
) -> list[dict[str, Any]]:
    """The node catalog: operator ids, versions, titles and port types."""
    async with _grafy(ctx) as (grafy, workspace_id):
        catalog = await grafy.catalog.get(workspace_id)
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
    ctx: Context,
    operator_id: str,
    operator_version: int | None = None,
) -> dict[str, Any]:
    """One node's full contract: config JSON Schema, ports, and conversions."""
    async with _grafy(ctx) as (grafy, workspace_id):
        catalog = await grafy.catalog.get(workspace_id)
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
    node = _dump(matching[0])
    node["artifact_conversions"] = [
        _dump(conversion) for conversion in catalog.artifact_conversions
    ]
    return node


async def author_graph(
    ctx: Context,
    project_id: UUID,
    graph_id: str,
    nodes: list[NodeSpec],
    connections: list[ConnectionSpec] | None = None,
    origins: list[OriginSpec] | None = None,
    cards: list[CardSpec] | None = None,
    card_bindings: list[CardBindingSpec] | None = None,
    graph_name: str | None = None,
    checkpoint: bool = True,
) -> dict[str, Any]:
    """Create or replace one Graph from a spec, validated against the catalog.

    Nodes, connections and origins are checked for operator identity, config
    schema, port shapes and artifact types before anything is sent. The Graph is
    then written in one validated batch (add or replace) and, by default,
    checkpointed. Cards show artifacts on the canvas: give `artifacts` for a
    Library card or `follows` for a card that shows a node output.
    """
    async with _grafy(ctx) as (grafy, workspace_id):
        hashes: dict[UUID, str | None] = {}
        if _needs_library_hashes(cards, origins):
            for item in await grafy.library.list(workspace_id):
                hashes[item.artifact.artifact_id] = item.artifact.sha256
        builder = GraphBuilder(await grafy.catalog.get(workspace_id))
        handles = _add_nodes(builder, nodes)
        for connection in connections or []:
            builder.connect(
                _node(handles, connection.source).output(connection.source.port),
                _node(handles, connection.target).input(connection.target.port),
                conversion_path=_conversions(connection.conversion_path),
                collection_mode=connection.collection_mode,
            )
        card_handles: dict[str, CardHandle] = {}
        for card in cards or []:
            if (card.follows is None) == (not card.artifacts):
                raise ToolError(
                    f"Card {card.id!r} needs exactly one of artifacts or follows"
                )
            position = _point(card.x, card.y)
            if card.follows is not None:
                card_handles[card.id] = builder.add_output_card(
                    _node(handles, card.follows).output(card.follows.port),
                    position=position,
                    projection=card.projection,
                    card_id=card.id,
                )
            else:
                card_handles[card.id] = builder.add_artifact_card(
                    _artifact_value(card.artifacts, hashes, as_sequence=False),
                    position=position,
                    card_id=card.id,
                )
        for origin in origins or []:
            target = _node(handles, origin.target).input(origin.target.port)
            source = (
                _card(card_handles, origin.card)
                if origin.card is not None
                else _artifact_value(
                    origin.artifacts, hashes, as_sequence=origin.as_sequence
                )
            )
            builder.place(
                target,
                source,
                conversion_path=_conversions(origin.conversion_path),
                collection_mode=origin.collection_mode,
            )
        for binding in card_bindings or []:
            _ = builder.bind_cards(
                _card(card_handles, binding.source_card),
                _card(card_handles, binding.target_card),
                binding.fields,
                effects=binding.effects,
            )
        head = await grafy.projects.upsert_graph(
            workspace_id,
            project_id,
            graph_id=graph_id,
            document=builder.build(),
            name=graph_name,
            checkpoint=checkpoint,
        )
    return {
        "project_id": str(head.project_id),
        "graph_id": graph_id,
        "collaboration_sequence": head.collaboration_sequence,
        "checkpoint_revision": head.checkpoint_revision,
        "checkpointed": head.collaboration_sequence == head.checkpoint_sequence,
    }


async def apply_project_commands(
    ctx: Context,
    project_id: UUID,
    commands: Annotated[
        list[dict[str, Any]],
        Field(
            min_length=1,
            description=(
                "Project commands, each with a `kind` (rename_project, add_graph, "
                "rename_graph, remove_graph, refresh_node, add_call_node, in_graph)"
                "; `in_graph` wraps one graph command such as add_node, add_edge, "
                "update_node_configuration or remove_nodes"
            ),
        ),
    ],
    checkpoint: bool = False,
) -> dict[str, Any]:
    """Apply fine-grained edits as one batch, accepted or rejected as a whole."""
    try:
        parsed: list[ProjectCommand] = [
            PROJECT_COMMAND_ADAPTER.validate_python(command) for command in commands
        ]
    except ValidationError as exc:
        raise ToolError(f"Invalid project command: {exc}") from exc
    async with _grafy(ctx) as (grafy, workspace_id):
        submitted = await grafy.projects.apply(
            workspace_id, project_id, parsed, checkpoint=checkpoint
        )
    return {
        "receipt": _dump(submitted.receipt),
        "collaboration_sequence": submitted.head.collaboration_sequence,
        "checkpoint_revision": submitted.head.checkpoint_revision,
    }


async def checkpoint_project(ctx: Context, project_id: UUID) -> dict[str, Any]:
    """Record the live head as a new immutable checkpoint."""
    async with _grafy(ctx) as (grafy, workspace_id):
        head = await grafy.projects.head(workspace_id, project_id)
        if head.collaboration_sequence == head.checkpoint_sequence:
            return {"checkpoint_revision": head.checkpoint_revision, "new": False}
        head = await grafy.projects.checkpoint(workspace_id, project_id, head=head)
    return {"checkpoint_revision": head.checkpoint_revision, "new": True}


async def start_run(
    ctx: Context,
    project_id: UUID,
    graph_id: str,
    targets: Annotated[
        list[RunTargetSpec] | None,
        Field(description="Nodes to make fresh; default every node of the Graph"),
    ] = None,
) -> dict[str, Any]:
    """Start a Run; only the stale part of the targets' upstream is computed."""
    async with _grafy(ctx) as (grafy, workspace_id):
        run = await grafy.runs.start(
            workspace_id,
            project_id,
            graph_id=graph_id,
            targets=[
                RunTarget(node_id=target.node_id, call_path=tuple(target.call_path))
                for target in targets or []
            ],
        )
    return _dump(run)


async def get_run(ctx: Context, project_id: UUID, run_id: UUID) -> dict[str, Any]:
    """A Run's status and error, if any."""
    async with _grafy(ctx) as (grafy, workspace_id):
        return _dump(await grafy.runs.get(workspace_id, project_id, run_id))


async def wait_for_run(
    ctx: Context,
    project_id: UUID,
    run_id: UUID,
    timeout_seconds: Annotated[float, Field(gt=0, le=_MAX_WAIT_SECONDS)] = 60.0,
) -> dict[str, Any]:
    """Wait until a Run finishes or the timeout passes, then report its status."""
    async with _grafy(ctx) as (grafy, workspace_id):
        try:
            run = await grafy.runs.wait(
                workspace_id,
                project_id,
                run_id,
                timeout=timeout_seconds,
                poll_interval=_RUN_POLL_SECONDS,
            )
        except ExecutionTimeoutError:
            run = await grafy.runs.get(workspace_id, project_id, run_id)
    return _dump(run)


async def cancel_run(ctx: Context, project_id: UUID, run_id: UUID) -> dict[str, Any]:
    """Withdraw a Run's demand; shared computations keep running for others."""
    async with _grafy(ctx) as (grafy, workspace_id):
        return _dump(await grafy.runs.cancel(workspace_id, project_id, run_id))


async def list_instances(
    ctx: Context, project_id: UUID, graph_id: str
) -> list[dict[str, Any]]:
    """Every node instance of a Graph with its state: fresh, stale, running..."""
    async with _grafy(ctx) as (grafy, workspace_id):
        states = await grafy.runs.instances(workspace_id, project_id, graph_id)
    return [_dump(state) for state in states]


async def get_instance_result(
    ctx: Context,
    project_id: UUID,
    graph_id: str,
    node_id: str,
    call_path: list[str] | None = None,
) -> dict[str, Any]:
    """A node's last result: output artifact references per port (may be stale)."""
    async with _grafy(ctx) as (grafy, workspace_id):
        result = await grafy.runs.instance_result(
            workspace_id,
            project_id,
            graph_id=graph_id,
            node_id=node_id,
            call_path=call_path or [],
        )
    return _dump(result)


async def list_library(ctx: Context) -> list[dict[str, Any]]:
    """Artifacts saved in the Workspace Library."""
    async with _grafy(ctx) as (grafy, workspace_id):
        return [_dump(item) for item in await grafy.library.list(workspace_id)]


async def upload_file(
    ctx: Context,
    filename: Annotated[
        str, Field(description="The extension decides the file format")
    ],
    content_base64: str,
    save_to_library: bool = True,
) -> dict[str, Any]:
    """Upload a small file (up to 2 MiB) and get its typed artifact reference.

    Only a deployment whose API receives upload bytes serves this tool. Where the
    API hands out signed object-storage URLs instead, the bytes cannot be sent from
    inside the API process and the tool reports that; use the staged upload API over
    HTTP. Larger files go through that API in every deployment (`grafy_client`
    uploads stream a file of any size the deployment accepts).
    """
    try:
        content = base64.b64decode(content_base64, validate=True)
    except binascii.Error as exc:
        raise ToolError("content_base64 is not valid base64") from exc
    if len(content) > _MAX_INLINE_UPLOAD_BYTES:
        raise ToolError("Inline uploads are limited to 2 MiB")
    async with _grafy(ctx) as (grafy, workspace_id):
        upload = await grafy.uploads.upload(workspace_id, content, filename=filename)
        content_hash: str | None = None
        saved = False
        if save_to_library and upload.artifact_id is not None:
            item = await grafy.library.save_from_upload(
                workspace_id,
                artifact_id=upload.artifact_id,
                original_filename=upload.filename,
            )
            content_hash = item.artifact.sha256
            saved = True
    return {
        **_dump(upload),
        "content_hash": content_hash,
        "saved_to_library": saved,
    }


async def read_artifact_text(
    ctx: Context,
    artifact_id: UUID,
    max_bytes: Annotated[int, Field(ge=1, le=_MAX_TEXT_BYTES)] = 64 * 1024,
) -> dict[str, Any]:
    """The stored bytes of a text-like artifact (JSON, CSV, text), as UTF-8."""
    async with _grafy(ctx) as (grafy, workspace_id):
        content = await grafy.artifacts.content(workspace_id, artifact_id)
    return {
        "text": content[:max_bytes].decode("utf-8", errors="replace"),
        "byte_size": len(content),
        "truncated": len(content) > max_bytes,
    }


async def get_table_schema(ctx: Context, artifact_id: UUID) -> dict[str, Any]:
    """A table artifact's columns (id, title, value type) and row count."""
    async with _grafy(ctx) as (grafy, workspace_id):
        return _dump(await grafy.artifacts.table_schema(workspace_id, artifact_id))


async def read_table_page(
    ctx: Context,
    artifact_id: UUID,
    offset: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    column_ids: list[str] | None = None,
) -> dict[str, Any]:
    """A window of table rows; long cells come back truncated."""
    async with _grafy(ctx) as (grafy, workspace_id):
        page = await grafy.artifacts.table_page(
            workspace_id,
            artifact_id,
            offset=offset,
            limit=limit,
            column_ids=column_ids,
        )
    return _dump(page)


async def query_table(
    ctx: Context,
    artifact_id: UUID,
    match_rows: Annotated[
        list[dict[str, str | int | float | bool]],
        Field(
            min_length=1,
            max_length=50,
            description="Keep rows equal to any one of these {column_id: value}",
        ),
    ],
    offset: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    """Table rows that exactly match one of the given key rows."""
    async with _grafy(ctx) as (grafy, workspace_id):
        page = await grafy.artifacts.table_query(
            workspace_id,
            artifact_id,
            filter_rows=match_rows,
            offset=offset,
            limit=limit,
        )
    return _dump(page)


async def get_geo_render(ctx: Context, artifact_id: UUID) -> dict[str, Any]:
    """A geo artifact's render descriptor: layers, bounds, basemap."""
    async with _grafy(ctx) as (grafy, workspace_id):
        return _dump(await grafy.artifacts.geo_render(workspace_id, artifact_id))


async def query_geo_features(
    ctx: Context,
    artifact_id: UUID,
    match_rows: Annotated[
        list[dict[str, str | int | float | bool]],
        Field(
            min_length=1,
            max_length=50,
            description="Features whose properties equal any one of these rows",
        ),
    ],
) -> dict[str, Any]:
    """How many features match, and their combined bounds."""
    async with _grafy(ctx) as (grafy, workspace_id):
        matched = await grafy.artifacts.geo_query(workspace_id, artifact_id, match_rows)
    return _dump(matched)


TOOLS: Final = (
    get_workspace,
    list_projects,
    create_project,
    get_project,
    list_nodes,
    describe_node,
    author_graph,
    apply_project_commands,
    checkpoint_project,
    start_run,
    get_run,
    wait_for_run,
    cancel_run,
    list_instances,
    get_instance_result,
    list_library,
    upload_file,
    read_artifact_text,
    get_table_schema,
    read_table_page,
    query_table,
    get_geo_render,
    query_geo_features,
)


def build_mcp_server() -> MCPServer:
    server = MCPServer(name="grafy", title="Grafy", instructions=INSTRUCTIONS)
    for tool in TOOLS:
        server.add_tool(tool)
    return server


def _port_summary(port: CatalogPort) -> str:
    accepted = (
        f"{port.artifact_type.id}@{port.artifact_type.schema_version}"
        if port.artifact_type is not None
        else f"<{port.artifact_type_variable}>"
    )
    shape = port.shape.value
    optional = "" if port.required else "?"
    return f"{port.name}{optional}: {accepted} ({shape})"


__all__ = ["INSTRUCTIONS", "TOOLS", "build_mcp_server"]
