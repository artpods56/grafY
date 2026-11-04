"""The toolbox's seams, wired to the deployment (ADR 0021, issue #203).

``toolbox.py`` decides what a tool is and what a call does, against four small seams. This
module is the one place those seams meet the registry, the artifact store, the file storage
and the Run service, so the toolbox stays testable without any of them:

* **Ports** are read from the operator contract the registry registers, resolved against the
  node's own artifact type bindings, so a generic port is offered as the type it is bound to.
* **Arguments are content-addressed.** A value the model wrote becomes an inline artifact
  whose id is derived from the Workspace, the type and the content, so the same text is the
  same artifact every time and the kernel sees equal origins for equal calls.
* **Model views** are plain text a model can read: the value of a scalar or markdown, a page
  of rows of a table, and for anything else a one-line description that says it was not
  shown. Nothing here fetches a blob a model could not usefully read.
* **The computation** is ``RunService.call_tool`` with the Project already chosen.
"""

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid5

from grafy_api.agents.context import AgentContextReader, ContextBlock
from grafy_api.agents.toolbox import (
    AgentToolbox,
    ArgumentArtifacts,
    JsonType,
    ModelViews,
    NodePorts,
    PortFacts,
    ToolComputation,
)
from grafy_api.agents.turns import AgentToolboxFactory
from grafy_api.runs.ports import ToolCallResult
from grafy_api.runs.service import RunService
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    ArtifactTypeSpec,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.domain.graph_documents import (
    GraphAgent,
    GraphDocument,
    GraphNode,
    GraphOrigin,
)
from grafy_core.kernel.instances import InstanceKey
from grafy_core.nodes import ArtifactTypeVariable, resolve_node_contracts
from grafy_core.plugins import PluginRegistry, UnknownOperatorError
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.table_storage import load_table_page

#: Names the artifacts a model's argument is stored under, so no other writer's id collides.
ARGUMENT_ARTIFACT_NAMESPACE = UUID("6d7f4d10-1a2b-4c3d-8e4f-5a6b7c8d9e01")

logger = logging.getLogger(__name__)

MAX_VIEW_CHARS = 20_000
"""The most of one value a model is shown. The artifact itself is untouched."""

TABLE_VIEW_ROWS = 20
"""How many rows of a table a model is shown, with the total, so it can ask for more."""

SEQUENCE_VIEW_ITEMS = 5


class RegistryNodePorts(NodePorts):
    """A node's ports as its registered operator declares them."""

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    def input_ports(self, node: GraphNode) -> Sequence[PortFacts] | None:
        return self._ports(node, inputs=True)

    def output_ports(self, node: GraphNode) -> Sequence[PortFacts] | None:
        return self._ports(node, inputs=False)

    def title(self, node: GraphNode) -> str:
        try:
            return self._registry.node_registration(
                node.operator_id, node.operator_version
            ).title
        except UnknownOperatorError:
            return node.operator_id

    def _ports(self, node: GraphNode, *, inputs: bool) -> Sequence[PortFacts] | None:
        try:
            registration = self._registry.node_registration(
                node.operator_id, node.operator_version
            )
        except UnknownOperatorError:
            return None
        # A node's own bindings decide what a generic port is. The class carries the
        # contract; resolving never builds the node, so one that needs runtime services is
        # described like any other.
        resolved = resolve_node_contracts(
            cast(Any, registration.node_class),
            node.artifact_type_binding_map(),
            node.config_dict(),
        )
        facts: list[PortFacts] = []
        if inputs:
            for name, port in resolved.input_contract.ports.items():
                facts.append(
                    PortFacts(
                        name=name,
                        artifact_type=_concrete(port.accepts),
                        required=port.required,
                        title=port.title,
                        description=port.description,
                    )
                )
        else:
            for name, out in resolved.output_contract.ports.items():
                facts.append(
                    PortFacts(
                        name=name,
                        artifact_type=_concrete(out.produces),
                        required=out.required,
                        title=out.title,
                        description=out.description,
                    )
                )
        return facts


def _concrete(
    contract: ArtifactTypeKey | ArtifactTypeVariable,
) -> ArtifactTypeKey | None:
    """The type a port is, or ``None`` while it is a variable nothing has bound."""
    return None if isinstance(contract, ArtifactTypeVariable) else contract


class ContentAddressedArguments(ArgumentArtifacts):
    """Model-written values as inline artifacts, one artifact per distinct content."""

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._json_types: dict[ArtifactTypeKey, JsonType] = {}
        for spec in registry.artifact_types:
            json_type = _writable_json_type(spec)
            if json_type is not None:
                self._json_types[spec.key] = json_type

    def json_type(self, key: ArtifactTypeKey) -> JsonType | None:
        return self._json_types.get(key)

    async def ref_for(
        self,
        *,
        workspace_id: UUID,
        key: ArtifactTypeKey,
        value: str | int,
    ) -> ArtifactRef:
        payload = {"value": value}
        content = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        digest = sha256(content).hexdigest()
        artifact_id = uuid5(
            ARGUMENT_ARTIFACT_NAMESPACE,
            f"{workspace_id}:{key.id}@{key.schema_version}:{digest}",
        )
        async with self._unit_of_work_factory() as unit_of_work:
            existing = await unit_of_work.artifacts.get(workspace_id, artifact_id)
            if existing is not None:
                return existing.ref()
            artifact = ArtifactObject(
                id=artifact_id,
                workspace_id=workspace_id,
                artifact_type=key.id,
                schema_version=key.schema_version,
                content_type="application/json",
                storage_backend="inline",
                inline_payload=payload,
                byte_size=len(content),
                sha256=digest,
                metadata={"written_by": "agent_tool_call"},
            )
            try:
                await unit_of_work.artifacts.add(artifact)
                await unit_of_work.commit()
            except ObjectAlreadyExistsError:
                # Two identical calls wrote at once. The id is the content's, so the one
                # that lost the race holds exactly what the winner stored.
                await unit_of_work.rollback()
        return artifact.ref()


def _writable_json_type(spec: ArtifactTypeSpec) -> JsonType | None:
    """``string`` or ``integer`` when a bare ``{"value": ...}`` payload is the whole type."""

    if spec.materialized_json_type not in ("string", "integer"):
        return None
    properties = spec.payload_schema.get("properties")
    if not isinstance(properties, dict) or set(properties) != {"value"}:
        return None
    return "string" if spec.materialized_json_type == "string" else "integer"


class ArtifactModelViews(ModelViews):
    """Outputs rendered as text a model can read."""

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        storage: FileStoragePort,
        workspace_id: UUID,
    ) -> None:
        self._titles = {spec.key: spec.title for spec in registry.artifact_types}
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._workspace_id = workspace_id

    async def render(self, *, outputs: Mapping[str, ArtifactOutputValue]) -> str:
        sections: list[str] = []
        for port, value in outputs.items():
            sections.append(f"{port}:\n{await self._render_value(value)}")
        return "\n\n".join(sections) if sections else "The tool returned nothing."

    async def _render_value(self, value: ArtifactOutputValue) -> str:
        if isinstance(value, ArtifactRefSequence):
            shown = [
                await self._render_ref(ref)
                for ref in value.item_refs[:SEQUENCE_VIEW_ITEMS]
            ]
            more = len(value.item_refs) - len(shown)
            lines = [f"{len(value.item_refs)} items:"]
            lines += [f"- {text}" for text in shown]
            if more > 0:
                lines.append(f"- ... and {more} more not shown")
            return "\n".join(lines)
        return await self._render_ref(value)

    async def render_ref(self, ref: ArtifactRef) -> str:
        return await self._render_ref(ref)

    async def render_library_item(self, artifact_id: UUID) -> str:
        """One Library artifact by id, as a model reads it."""

        async with self._unit_of_work_factory() as unit_of_work:
            artifact = await unit_of_work.artifacts.get(self._workspace_id, artifact_id)
        if artifact is None:
            return "[this Library item is no longer available]"
        return await self._render_artifact(artifact)

    async def _render_ref(self, ref: ArtifactRef) -> str:
        async with self._unit_of_work_factory() as unit_of_work:
            artifact = await unit_of_work.artifacts.get(
                self._workspace_id, ref.artifact_id
            )
        if artifact is None:
            return f"[{ref.artifact_type} artifact that is no longer available]"
        return await self._render_artifact(artifact)

    async def _render_artifact(self, artifact: ArtifactObject) -> str:
        payload = artifact.inline_payload
        if isinstance(payload, dict):
            for field in ("value", "markdown", "text"):
                found = payload.get(field)
                if isinstance(found, (str, int, float, bool)):
                    return _clip(str(found))
        if artifact.artifact_type.startswith("table."):
            return await self._render_table(artifact)
        title = self._titles.get(
            ArtifactTypeKey(artifact.artifact_type, artifact.schema_version),
            artifact.artifact_type,
        )
        size = f", {artifact.byte_size} bytes" if artifact.byte_size else ""
        return f"[{title}{size}; its content is not shown to you]"

    async def _render_table(self, artifact: ArtifactObject) -> str:
        page = await load_table_page(
            artifact, self._storage, offset=0, limit=TABLE_VIEW_ROWS
        )
        header = [column.title or column.id for column in page.columns]
        lines = [" | ".join(header), " | ".join("---" for _ in header)]
        for row in page.rows:
            lines.append(
                " | ".join(str(row.get(column.id, "")) for column in page.columns)
            )
        shown = len(page.rows)
        if page.total_rows > shown:
            lines.append(f"(showing {shown} of {page.total_rows} rows)")
        return _clip("\n".join(lines))


def _clip(text: str) -> str:
    if len(text) <= MAX_VIEW_CHARS:
        return text
    return (
        text[:MAX_VIEW_CHARS] + f"\n... [{len(text) - MAX_VIEW_CHARS} more characters]"
    )


class ProjectToolComputation(ToolComputation):
    """``RunService.call_tool`` for one Project, at the root call path."""

    def __init__(
        self, runs: RunService, *, workspace_id: UUID, project_id: UUID
    ) -> None:
        self._runs = runs
        self._workspace_id = workspace_id
        self._project_id = project_id

    async def __call__(
        self,
        *,
        graph_id: str,
        node_id: str,
        arguments: Sequence[GraphOrigin],
    ) -> ToolCallResult:
        return await self._runs.call_tool(
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            graph_id=graph_id,
            call_path=(),
            node_id=node_id,
            arguments=arguments,
        )


class ProjectContextReader(AgentContextReader):
    """The three things that can be connected to an Agent, read for one turn."""

    def __init__(
        self,
        *,
        runs: RunService,
        registry: PluginRegistry,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        storage: FileStoragePort,
    ) -> None:
        self._runs = runs
        self._registry = registry
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage

    async def read(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent: GraphAgent,
        document: GraphDocument,
    ) -> Sequence[ContextBlock]:
        views = ArtifactModelViews(
            registry=self._registry,
            unit_of_work_factory=self._unit_of_work_factory,
            storage=self._storage,
            workspace_id=workspace_id,
        )
        viewers = {viewer.id: viewer for viewer in document.presentation.viewers}
        nodes = {node.id: node for node in document.nodes}
        titles = RegistryNodePorts(self._registry)
        blocks: list[ContextBlock] = []
        for link in agent.context:
            try:
                if link.kind == "node_output" and link.node_id and link.port:
                    node = nodes[link.node_id]
                    label = f"{titles.title(node)}, output {link.port}"
                    blocks.append(
                        ContextBlock(
                            label,
                            await self._node_output(
                                views,
                                workspace_id,
                                project_id,
                                graph_id,
                                link.node_id,
                                link.port,
                            ),
                        )
                    )
                elif link.kind == "card" and link.card_id:
                    viewer = viewers.get(link.card_id)
                    if viewer is None or viewer.artifact_ref is None:
                        blocks.append(ContextBlock("A card", "[this card is gone]"))
                    else:
                        blocks.append(
                            ContextBlock(
                                "A card on the canvas",
                                await views.render_ref(viewer.artifact_ref),
                            )
                        )
                elif link.kind == "library_item" and link.library_item_id:
                    blocks.append(
                        ContextBlock(
                            "A Library item",
                            await views.render_library_item(link.library_item_id),
                        )
                    )
            except Exception:  # noqa: BLE001 - one unreadable link must not end the turn
                logger.warning(
                    "agent_context_unreadable agent=%s link=%s", agent.id, link.id
                )
                blocks.append(ContextBlock(f"Context {link.id}", "[could not be read]"))
        return blocks

    async def _node_output(
        self,
        views: "ArtifactModelViews",
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        port: str,
    ) -> str:
        snapshot, stored = await self._runs.instance_result(
            workspace_id=workspace_id,
            project_id=project_id,
            key=InstanceKey(
                project_id=str(project_id),
                graph_id=graph_id,
                call_path=(),
                node_id=node_id,
            ),
        )
        if stored is None or port not in stored.outputs:
            return (
                f"[this node has no result to show yet; it is {snapshot.state.value}]"
            )
        text = await views.render(outputs={port: stored.outputs[port]})
        # The view names the port again; the heading already did.
        return text.split(":\n", 1)[1] if text.startswith(f"{port}:\n") else text


def build_toolbox_factory(
    *,
    registry: PluginRegistry,
    runs: RunService,
    unit_of_work_factory: Callable[[], UnitOfWorkPort],
    storage: FileStoragePort,
) -> AgentToolboxFactory:
    """The turn runtime's way to get the tools of one Agent on one Graph."""

    ports = RegistryNodePorts(registry)
    arguments = ContentAddressedArguments(
        registry=registry, unit_of_work_factory=unit_of_work_factory
    )

    def factory(
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent: GraphAgent,
        document: GraphDocument,
    ) -> AgentToolbox | None:
        return AgentToolbox.build(
            agent=agent,
            document=document,
            graph_id=graph_id,
            workspace_id=workspace_id,
            node_ports=ports,
            computation=ProjectToolComputation(
                runs, workspace_id=workspace_id, project_id=project_id
            ),
            artifacts=arguments,
            views=ArtifactModelViews(
                registry=registry,
                unit_of_work_factory=unit_of_work_factory,
                storage=storage,
                workspace_id=workspace_id,
            ),
        )

    return factory


__all__ = [
    "ARGUMENT_ARTIFACT_NAMESPACE",
    "ProjectContextReader",
    "ArtifactModelViews",
    "ContentAddressedArguments",
    "ProjectToolComputation",
    "RegistryNodePorts",
    "build_toolbox_factory",
]
