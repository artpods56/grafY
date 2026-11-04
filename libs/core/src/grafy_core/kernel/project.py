"""The Project document: named Graphs and the calls between them (ADR 0020).

A **Project** is the collaborative document. It holds **Graphs**, each a typed
interface plus nodes, edges and canvas layout. A **call node** places a sibling
Graph as a node whose ports are that Graph's **interface**, which its **boundary
nodes** (``graph.input`` / ``graph.output``) declare by public name. The call
relation must be acyclic, a Graph with callers cannot be removed, and an
interface change is never rejected at the call site: it is reported there as a
connection issue by :func:`call_site_issues`, the same way an incompatible edge
reads today.

The document is a value: every mutation returns a new one, so a command is a
pure function of the previous checkpoint.

Nodes and edges use the Graph value types in
``grafy_core.domain.graph_documents``.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal, Self, cast

from pydantic import (
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.graph_documents import (
    GraphIdentifier,
    GraphDocument,
    GraphNode,
    GraphValue,
)

#: The operator a boundary input node runs. It contributes the Graph's own input.
GRAPH_INPUT_OPERATOR_ID = "graph.input"
#: The operator a boundary output node runs. It carries the Graph's own output.
GRAPH_OUTPUT_OPERATOR_ID = "graph.output"
#: The only boundary operator version a document may name.
GRAPH_BOUNDARY_OPERATOR_VERSION = 1
#: The single port a boundary node reads or writes inside its own Graph.
GRAPH_BOUNDARY_PORT = "value"
#: The artifact type binding variable that types a boundary node.
GRAPH_ARTIFACT_TYPE_VARIABLE = "T"
#: The ``GraphNode.kind`` of a node that calls a sibling Graph.
CALL_NODE_KIND = "call"
#: The only operator version a call node may name; it is the callee Graph itself.
CALL_NODE_OPERATOR_VERSION = 1

GRAPH_NAME_MAX_LENGTH = 160

PUBLIC_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_BOUNDARY_OPERATORS: frozenset[str] = frozenset(
    {GRAPH_INPUT_OPERATOR_ID, GRAPH_OUTPUT_OPERATOR_ID}
)

GraphName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=GRAPH_NAME_MAX_LENGTH
    ),
]
RefreshGeneration = Annotated[int, Field(ge=0)]


@dataclass(frozen=True, slots=True)
class CallSite:
    """One call node: the Graph it sits in and the node itself."""

    graph_id: str
    node_id: str


class ProjectDocumentError(ValueError):
    """A Project document rule was broken."""


class GraphCallCycleError(ProjectDocumentError):
    """The call relation would no longer be acyclic."""


class MissingCalleeError(ProjectDocumentError):
    """A call node names a Graph this Project does not hold."""


class GraphHasCallersError(ProjectDocumentError):
    """A Graph still called by other Graphs cannot be removed.

    The way back from an accepted change is checkpoint restore, so removal is
    refused rather than repaired: the caller has to drop its call node first.
    """

    def __init__(self, graph_id: str, callers: Sequence[CallSite]) -> None:
        self.graph_id = graph_id
        self.callers: tuple[CallSite, ...] = tuple(callers)
        named = ", ".join(f"{site.graph_id}/{site.node_id}" for site in self.callers)
        super().__init__(
            f"Graph {graph_id!r} is still called by: {named}; remove those call "
            "nodes first"
        )


class DuplicateGraphError(ProjectDocumentError):
    """A Graph id or name was already taken in this Project."""


class UnknownGraphError(ProjectDocumentError, KeyError):
    """No Graph in this Project carries that id."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


@dataclass(frozen=True, slots=True)
class CallSiteIssue:
    """One broken connection at a call node after an interface changed."""

    graph_id: str
    node_id: str
    edge_id: str | None
    origin_id: str | None
    kind: Literal["unknown_input_port", "unknown_output_port", "missing_required_input"]
    port: str


@dataclass(frozen=True, slots=True)
class InterfacePort:
    """One declared input or output of a Graph.

    ``artifact_type`` is the type bound to the boundary node, or ``None`` when
    the boundary node binds nothing and the port is untyped.
    """

    name: str
    artifact_type: ArtifactTypeKey | None
    required: bool
    description: str | None


@dataclass(frozen=True, slots=True)
class GraphInterface:
    """The ports a Graph offers its call sites, in document order."""

    inputs: tuple[InterfacePort, ...] = ()
    outputs: tuple[InterfacePort, ...] = ()

    @property
    def input_names(self) -> frozenset[str]:
        return frozenset(port.name for port in self.inputs)

    @property
    def output_names(self) -> frozenset[str]:
        return frozenset(port.name for port in self.outputs)


def _graph_name(value: str) -> str:
    """Strip and range-check a Graph name, raising the Project error type."""
    name = value.strip()
    if not name:
        raise ProjectDocumentError("Graph name must not be blank")
    if len(name) > GRAPH_NAME_MAX_LENGTH:
        raise ProjectDocumentError(
            f"Graph name must be at most {GRAPH_NAME_MAX_LENGTH} characters"
        )
    return name


def _freeze_generations(value: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(value))


def _thaw_generations(value: Mapping[str, int]) -> dict[str, int]:
    return dict(value)


def _config_text(node: GraphNode, key: str) -> str | None:
    value = node.config.get(key)
    return value if isinstance(value, str) else None


def _is_boundary(node: GraphNode) -> bool:
    return node.operator_id in _BOUNDARY_OPERATORS


def _public_name(node: GraphNode) -> str:
    """The public name a boundary node contributes to its Graph's interface."""
    return _config_text(node, "public_name") or ""


def _is_call(node: GraphNode) -> bool:
    return node.kind == CALL_NODE_KIND


class GraphDefinition(GraphValue):
    """One Graph of a Project: its interface, its nodes, its layout.

    A call node is a ``GraphNode`` with ``kind == "call"``, ``operator_id``
    set to the callee Graph's id and ``operator_version == 1``. Boundary nodes
    declare the interface: a builtin running ``graph.input`` or ``graph.output``
    whose config carries ``public_name`` and, for inputs only, ``required``.
    """

    id: GraphIdentifier
    name: GraphName
    document: GraphDocument
    refresh_generations: Mapping[str, RefreshGeneration] = Field(default_factory=dict)

    @field_validator("refresh_generations")
    @classmethod
    def freeze_refresh_generations(
        cls,
        value: Mapping[str, int],
    ) -> Mapping[str, int]:
        return _freeze_generations(value)

    @field_serializer("refresh_generations")
    def serialize_refresh_generations(self, value: Mapping[str, int]) -> dict[str, int]:
        return _thaw_generations(value)

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        known_nodes = {node.id for node in self.document.nodes}
        for node_id in sorted(self.refresh_generations):
            if node_id not in known_nodes:
                raise ValueError(
                    f"Graph {self.id} refresh generation names unknown node {node_id}"
                )
        self._validate_boundary_nodes()
        return self

    @property
    def interface(self) -> GraphInterface:
        return graph_interface(self)

    def _validate_boundary_nodes(self) -> None:
        public_names: dict[tuple[str, str], str] = {}
        for node in self.document.nodes:
            if not _is_boundary(node):
                continue
            direction = (
                "input" if node.operator_id == GRAPH_INPUT_OPERATOR_ID else "output"
            )
            if node.kind != "builtin":
                raise ValueError(
                    f"Graph {self.id} boundary node {node.id} must be a builtin node"
                )
            if node.operator_version != GRAPH_BOUNDARY_OPERATOR_VERSION:
                raise ValueError(
                    f"Graph {self.id} boundary node {node.id} must use "
                    f"operator_version {GRAPH_BOUNDARY_OPERATOR_VERSION}"
                )
            keys = set(node.config)
            unknown_keys = keys - {"public_name", "required", "description"}
            if unknown_keys:
                raise ValueError(
                    f"Graph {self.id} boundary node {node.id} has unknown config "
                    f"keys: {', '.join(sorted(unknown_keys))}"
                )
            public_name = _public_name(node)
            if not PUBLIC_NAME_PATTERN.match(public_name):
                raise ValueError(
                    f"Graph {self.id} boundary node {node.id} needs a public_name "
                    f"matching {PUBLIC_NAME_PATTERN.pattern}"
                )
            if direction == "output" and "required" in node.config:
                raise ValueError(
                    f"Graph {self.id} output boundary node {node.id} must not "
                    "declare required"
                )
            if "required" in node.config and not isinstance(
                node.config["required"], bool
            ):
                raise ValueError(
                    f"Graph {self.id} boundary node {node.id} required must be a "
                    "boolean"
                )
            description = node.config.get("description")
            if description is not None and not isinstance(description, str):
                raise ValueError(
                    f"Graph {self.id} boundary node {node.id} description must be "
                    "a string"
                )
            slot = (direction, public_name)
            if slot in public_names:
                raise ValueError(
                    f"Graph {self.id} declares {direction} {public_name!r} twice "
                    f"(nodes {public_names[slot]} and {node.id})"
                )
            public_names[slot] = node.id


def graph_interface(graph: GraphDefinition) -> GraphInterface:
    """Read the interface a Graph's boundary nodes declare, in document order."""
    inputs: list[InterfacePort] = []
    outputs: list[InterfacePort] = []
    for node in graph.document.nodes:
        if not _is_boundary(node):
            continue
        artifact_type = node.artifact_type_binding_map().get(
            GRAPH_ARTIFACT_TYPE_VARIABLE
        )
        description = _config_text(node, "description")
        if node.operator_id == GRAPH_INPUT_OPERATOR_ID:
            # GraphDefinition validation has already rejected a non-boolean.
            required = cast("bool", node.config.get("required", True))
            inputs.append(
                InterfacePort(
                    name=_public_name(node),
                    artifact_type=artifact_type,
                    required=required,
                    description=description,
                )
            )
        else:
            outputs.append(
                InterfacePort(
                    name=_public_name(node),
                    artifact_type=artifact_type,
                    required=True,
                    description=description,
                )
            )
    return GraphInterface(inputs=tuple(inputs), outputs=tuple(outputs))


def _callees(graphs: Sequence[GraphDefinition]) -> dict[str, tuple[str, ...]]:
    """The call relation: each Graph id to the distinct sibling ids it calls."""
    edges: dict[str, set[str]] = {graph.id: set() for graph in graphs}
    for graph in graphs:
        for node in graph.document.nodes:
            if _is_call(node) and node.operator_id in edges:
                edges[graph.id].add(node.operator_id)
    return {graph_id: tuple(sorted(called)) for graph_id, called in edges.items()}


def _find_call_cycle(callees: Mapping[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    """One cycle path (repeated at both ends) in the call relation, if any."""
    done: set[str] = set()
    path: list[str] = []
    on_path: set[str] = set()

    def visit(graph_id: str) -> tuple[str, ...] | None:
        path.append(graph_id)
        on_path.add(graph_id)
        for callee in callees.get(graph_id, ()):
            if callee in on_path:
                return (*path[path.index(callee) :], callee)
            if callee not in done:
                found = visit(callee)
                if found is not None:
                    return found
        path.pop()
        on_path.discard(graph_id)
        done.add(graph_id)
        return None

    for graph_id in sorted(callees):
        if graph_id not in done:
            found = visit(graph_id)
            if found is not None:
                return found
    return None


def _check_project(graphs: Sequence[GraphDefinition]) -> None:
    """Project rules every document must satisfy, raising the specific errors.

    Called by the mutation methods before they build a new document, and by the
    model validator as the backstop for a document built from raw values.
    """
    ids: set[str] = set()
    names: dict[str, str] = {}
    for graph in graphs:
        if graph.id in ids:
            raise DuplicateGraphError(f"Graph id {graph.id!r} appears twice")
        ids.add(graph.id)
        folded = graph.name.casefold()
        if folded in names:
            raise DuplicateGraphError(
                f"Graph name {graph.name!r} is used by both {names[folded]!r} and "
                f"{graph.id!r}"
            )
        names[folded] = graph.id

    for graph in graphs:
        for node in graph.document.nodes:
            if not _is_call(node):
                continue
            if node.operator_version != CALL_NODE_OPERATOR_VERSION:
                raise ProjectDocumentError(
                    f"Graph {graph.id} call node {node.id} must use "
                    f"operator_version {CALL_NODE_OPERATOR_VERSION}"
                )
            if node.operator_id not in ids:
                raise MissingCalleeError(
                    f"Graph {graph.id} node {node.id} calls unknown graph "
                    f"{node.operator_id!r}"
                )

    cycle = _find_call_cycle(_callees(graphs))
    if cycle is not None:
        raise GraphCallCycleError("Graph call cycle: " + " -> ".join(cycle))


class ProjectDocument(GraphValue):
    """The document of a Project: its Graphs and the calls between them."""

    graphs: tuple[GraphDefinition, ...] = ()

    @model_validator(mode="after")
    def validate_project(self) -> Self:
        _check_project(self.graphs)
        return self

    def get_graph(self, graph_id: str) -> GraphDefinition:
        for graph in self.graphs:
            if graph.id == graph_id:
                return graph
        raise UnknownGraphError(f"Project has no graph {graph_id!r}")

    def callers_of(self, graph_id: str) -> tuple[CallSite, ...]:
        """Every call node placing this Graph, ordered by graph then node."""
        self.get_graph(graph_id)
        callers = [
            CallSite(graph_id=graph.id, node_id=node.id)
            for graph in self.graphs
            for node in graph.document.nodes
            if _is_call(node) and node.operator_id == graph_id
        ]
        return tuple(sorted(callers, key=lambda site: (site.graph_id, site.node_id)))

    def callees_of(self, graph_id: str) -> tuple[str, ...]:
        """The distinct Graphs this Graph calls, sorted."""
        self.get_graph(graph_id)
        return tuple(sorted(_callees(self.graphs)[graph_id]))

    def add_graph(self, graph: GraphDefinition) -> "ProjectDocument":
        return self._rebuild((*self.graphs, graph))

    def rename_graph(self, graph_id: str, name: str) -> "ProjectDocument":
        graph = self.get_graph(graph_id)
        replacement = GraphDefinition(
            id=graph.id,
            name=_graph_name(name),
            document=graph.document,
            refresh_generations=graph.refresh_generations,
        )
        return self._rebuild(
            tuple(
                replacement if existing.id == graph_id else existing
                for existing in self.graphs
            )
        )

    def replace_graph_document(
        self,
        graph_id: str,
        document: GraphDocument,
    ) -> "ProjectDocument":
        """Swap one Graph's document, dropping generations for nodes it removed."""
        self.get_graph(graph_id)
        known_nodes = {node.id for node in document.nodes}
        return self._rebuild(
            tuple(
                GraphDefinition(
                    id=existing.id,
                    name=existing.name,
                    document=document,
                    refresh_generations={
                        node_id: generation
                        for node_id, generation in existing.refresh_generations.items()
                        if node_id in known_nodes
                    },
                )
                if existing.id == graph_id
                else existing
                for existing in self.graphs
            )
        )

    def set_refresh_generation(
        self,
        graph_id: str,
        node_id: str,
        generation: int,
    ) -> "ProjectDocument":
        graph = self.get_graph(graph_id)
        if isinstance(generation, bool):
            raise ProjectDocumentError(
                f"Refresh generation must be an integer, got {generation!r}"
            )
        if generation < 0:
            raise ProjectDocumentError(
                f"Refresh generation must not be negative, got {generation}"
            )
        if node_id not in {node.id for node in graph.document.nodes}:
            raise ProjectDocumentError(
                f"Graph {graph_id} has no node {node_id!r} to refresh"
            )
        return self._rebuild(
            tuple(
                GraphDefinition(
                    id=existing.id,
                    name=existing.name,
                    document=existing.document,
                    refresh_generations={
                        **existing.refresh_generations,
                        node_id: generation,
                    },
                )
                if existing.id == graph_id
                else existing
                for existing in self.graphs
            )
        )

    def remove_graph(self, graph_id: str) -> "ProjectDocument":
        """Drop a Graph. Refused while another Graph still calls it."""
        graph = self.get_graph(graph_id)
        callers = self.callers_of(graph.id)
        if callers:
            raise GraphHasCallersError(graph.id, callers)
        return self._rebuild(
            tuple(existing for existing in self.graphs if existing.id != graph_id)
        )

    def _rebuild(self, graphs: Sequence[GraphDefinition]) -> "ProjectDocument":
        """Validate the rules callers can be told about, then build the value."""
        replacement = tuple(graphs)
        _check_project(replacement)
        return ProjectDocument(graphs=replacement)


def call_site_issues(project: ProjectDocument) -> tuple[CallSiteIssue, ...]:
    """Every connection at a call node its callee interface cannot satisfy.

    An interface change is not a document error, so it is never rejected; it
    reads here as a connection issue, exactly like an edge whose artifact types
    do not line up. Disabled edges neither satisfy a port nor report one.
    """
    issues: list[CallSiteIssue] = []
    for graph in project.graphs:
        for node in graph.document.nodes:
            if not _is_call(node):
                continue
            interface = graph_interface(project.get_graph(node.operator_id))
            incoming = [
                edge
                for edge in graph.document.edges
                if edge.to_node == node.id and edge.enabled
            ]
            outgoing = [
                edge
                for edge in graph.document.edges
                if edge.from_node == node.id and edge.enabled
            ]
            origins = [
                origin for origin in graph.document.origins if origin.to_node == node.id
            ]

            for edge in incoming:
                if edge.to_port not in interface.input_names:
                    issues.append(
                        CallSiteIssue(
                            graph_id=graph.id,
                            node_id=node.id,
                            edge_id=edge.id,
                            origin_id=None,
                            kind="unknown_input_port",
                            port=edge.to_port,
                        )
                    )
            for origin in origins:
                if origin.to_port not in interface.input_names:
                    issues.append(
                        CallSiteIssue(
                            graph_id=graph.id,
                            node_id=node.id,
                            edge_id=None,
                            origin_id=origin.id,
                            kind="unknown_input_port",
                            port=origin.to_port,
                        )
                    )
            for edge in outgoing:
                if edge.from_port not in interface.output_names:
                    issues.append(
                        CallSiteIssue(
                            graph_id=graph.id,
                            node_id=node.id,
                            edge_id=edge.id,
                            origin_id=None,
                            kind="unknown_output_port",
                            port=edge.from_port,
                        )
                    )

            satisfied = {edge.to_port for edge in incoming} | {
                origin.to_port for origin in origins
            }
            for port in interface.inputs:
                if port.required and port.name not in satisfied:
                    issues.append(
                        CallSiteIssue(
                            graph_id=graph.id,
                            node_id=node.id,
                            edge_id=None,
                            origin_id=None,
                            kind="missing_required_input",
                            port=port.name,
                        )
                    )

    return tuple(
        sorted(
            issues,
            key=lambda issue: (
                issue.graph_id,
                issue.node_id,
                issue.kind,
                issue.port,
                issue.edge_id or "",
                issue.origin_id or "",
            ),
        )
    )


__all__ = [
    "CALL_NODE_KIND",
    "CALL_NODE_OPERATOR_VERSION",
    "GRAPH_ARTIFACT_TYPE_VARIABLE",
    "GRAPH_BOUNDARY_OPERATOR_VERSION",
    "GRAPH_BOUNDARY_PORT",
    "GRAPH_INPUT_OPERATOR_ID",
    "GRAPH_OUTPUT_OPERATOR_ID",
    "CallSite",
    "CallSiteIssue",
    "DuplicateGraphError",
    "GraphCallCycleError",
    "GraphDefinition",
    "GraphHasCallersError",
    "GraphInterface",
    "InterfacePort",
    "MissingCalleeError",
    "ProjectDocument",
    "ProjectDocumentError",
    "UnknownGraphError",
    "call_site_issues",
    "graph_interface",
]
