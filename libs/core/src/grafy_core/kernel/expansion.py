"""Instance expansion: one target Graph, its calls inlined (ADR 0020, issue #194).

``expand_graph`` walks a target Graph of a :class:`ProjectDocument` and places
one :class:`ExpandedInstance` per non-call node of the target and, recursively,
of every callee Graph. A call node never becomes an instance: its ports are
the callee's interface, so the pass-through boundary model rewires around it.
Edges into a call node connect to the callee's ``graph.input`` boundary
instance at the deeper call path, and edges out of a call node read from the
callee's ``graph.output`` boundary instance there. The boundary nodes are
ordinary instances inside the callee, so the callee's own edges carry values
from its input boundaries to its output boundaries and no edge composition is
needed at the call site.

Because the boundary instances sit in the callee's Graph, their identity comes
from the callee document and the caller's feeding edges, never from which call
node was used: two calls of the same Graph supplied with the same inputs
produce identical instances, and therefore identical fingerprints, at the two
call paths. That equality is what lets one computation serve both calls.

A caller-supplied input beats a callee default: an input boundary fed by the
caller — an edge or an origin at the call node's port — drops the origins the
callee wrote on its own boundary node. Connections of a call interface the
callee cannot satisfy are skipped here; ``call_site_issues`` reports them at
the call site, where the user can see the broken connection.

The function is pure: it reads the document, mutates nothing, performs no I/O,
and raises :class:`ExpansionError` when the expanded instances form a cycle.
"""

import heapq
from collections.abc import Mapping
from dataclasses import dataclass, field

from grafy_core.domain.saved_graphs import (
    SavedGraphNode,
    SavedGraphOrigin,
)
from grafy_core.kernel.instances import (
    Connection,
    ExpandedGraph,
    ExpandedInstance,
    InstanceKey,
)
from grafy_core.kernel.project import (
    CALL_NODE_KIND,
    GRAPH_BOUNDARY_PORT,
    GRAPH_INPUT_OPERATOR_ID,
    GRAPH_OUTPUT_OPERATOR_ID,
    GraphDefinition,
    ProjectDocument,
    ProjectDocumentError,
)


class ExpansionError(ProjectDocumentError):
    """The expanded instances of a Graph form a cycle no Run could schedule."""


def _describe(key: InstanceKey) -> str:
    """Name one instance in an error message."""
    call_path = "/".join(key.call_path) if key.call_path else "(root)"
    return f"instance node={key.node_id!r} graph={key.graph_id!r} call_path={call_path}"


def _is_call(node: SavedGraphNode) -> bool:
    return node.kind == CALL_NODE_KIND


def _public_name(node: SavedGraphNode) -> str:
    value = node.config.get("public_name")
    return value if isinstance(value, str) else ""


@dataclass(frozen=True, slots=True)
class _GraphIndex:
    """One visited Graph with its node and interface lookups precomputed."""

    graph: GraphDefinition
    nodes: dict[str, SavedGraphNode]
    inputs: dict[str, SavedGraphNode]
    outputs: dict[str, SavedGraphNode]


def _index(graph: GraphDefinition) -> _GraphIndex:
    nodes: dict[str, SavedGraphNode] = {}
    inputs: dict[str, SavedGraphNode] = {}
    outputs: dict[str, SavedGraphNode] = {}
    for node in graph.document.nodes:
        nodes[node.id] = node
        if node.operator_id == GRAPH_INPUT_OPERATOR_ID:
            inputs[_public_name(node)] = node
        elif node.operator_id == GRAPH_OUTPUT_OPERATOR_ID:
            outputs[_public_name(node)] = node
    return _GraphIndex(graph=graph, nodes=nodes, inputs=inputs, outputs=outputs)


@dataclass
class _Pending:
    """One instance while its edges and origins are being rewritten."""

    node: SavedGraphNode
    refresh_generation: int
    connections: list[Connection] = field(default_factory=list)
    own_origins: list[SavedGraphOrigin] = field(default_factory=list)
    caller_origins: list[SavedGraphOrigin] = field(default_factory=list)
    caller_supplied: bool = False


def _incoming_order(connection: Connection) -> tuple[str, str]:
    """Stable per-target order; ties keep the order the edges were read in."""
    return (connection.edge.to_port, connection.edge.to_plug or "")


def _visits(
    project: ProjectDocument,
    graph: GraphDefinition,
    call_path: tuple[str, ...],
) -> list[tuple[GraphDefinition, tuple[str, ...]]]:
    """This Graph and, under each call node in document order, its callees.

    The document has already rejected a call cycle, so this walk terminates:
    each call node occurrence opens exactly one deeper call path, and a Graph
    reached twice sits at two paths.
    """
    visits: list[tuple[GraphDefinition, tuple[str, ...]]] = [(graph, call_path)]
    for node in graph.document.nodes:
        if _is_call(node):
            visits.extend(
                _visits(
                    project, project.get_graph(node.operator_id), (*call_path, node.id)
                )
            )
    return visits


def _wire_edges(
    index: _GraphIndex,
    call_path: tuple[str, ...],
    indexes: Mapping[str, _GraphIndex],
    project_id: str,
    pending: dict[InstanceKey, _Pending],
) -> None:
    """Rewire every enabled edge of this Graph occurrence onto instances.

    An endpoint on a call node resolves to the callee boundary instance one
    call path deeper, with the stored edge rewritten to that boundary's single
    ``value`` port. An endpoint naming a port the callee does not declare
    skips the edge: ``call_site_issues`` owns that report.
    """
    for edge in index.graph.document.edges:
        if not edge.enabled:
            continue
        target = index.nodes.get(edge.to_node)
        source = index.nodes.get(edge.from_node)
        if target is None or source is None:
            continue
        updates: dict[str, object] = {}
        if _is_call(target):
            callee = indexes[target.operator_id]
            boundary = callee.inputs.get(edge.to_port)
            if boundary is None:
                continue
            target_key = InstanceKey(
                project_id,
                callee.graph.id,
                (*call_path, target.id),
                boundary.id,
            )
            pending[target_key].caller_supplied = True
            updates["to_port"] = GRAPH_BOUNDARY_PORT
            updates["to_plug"] = None
        else:
            target_key = InstanceKey(project_id, index.graph.id, call_path, target.id)
        if _is_call(source):
            callee = indexes[source.operator_id]
            boundary = callee.outputs.get(edge.from_port)
            if boundary is None:
                continue
            source_key = InstanceKey(
                project_id,
                callee.graph.id,
                (*call_path, source.id),
                boundary.id,
            )
            updates["from_port"] = GRAPH_BOUNDARY_PORT
        else:
            source_key = InstanceKey(project_id, index.graph.id, call_path, source.id)
        pending[target_key].connections.append(
            Connection(source=source_key, edge=edge.model_copy(update=updates))
        )


def _wire_origins(
    index: _GraphIndex,
    call_path: tuple[str, ...],
    indexes: Mapping[str, _GraphIndex],
    project_id: str,
    pending: dict[InstanceKey, _Pending],
) -> None:
    """Place every origin of this Graph occurrence onto instances.

    An origin on a call node's input port becomes an origin of the callee's
    input boundary instance at the deeper call path, and counts as a caller
    supply, so the callee's default origins on that boundary drop out.
    """
    for origin in index.graph.document.origins:
        target = index.nodes.get(origin.to_node)
        if target is None:
            continue
        if not _is_call(target):
            pending[
                InstanceKey(project_id, index.graph.id, call_path, target.id)
            ].own_origins.append(origin)
            continue
        callee = indexes[target.operator_id]
        boundary = callee.inputs.get(origin.to_port)
        if boundary is None:
            continue
        target_key = InstanceKey(
            project_id,
            callee.graph.id,
            (*call_path, target.id),
            boundary.id,
        )
        pending[target_key].caller_supplied = True
        pending[target_key].caller_origins.append(
            origin.model_copy(
                update={
                    "to_node": boundary.id,
                    "to_port": GRAPH_BOUNDARY_PORT,
                    "to_plug": None,
                }
            )
        )


def _topological_order(
    instances: Mapping[InstanceKey, ExpandedInstance],
) -> tuple[InstanceKey, ...]:
    """Kahn's algorithm with a heap keyed on ``InstanceKey.sort_key``.

    A heap rather than a set makes the order a property of the graph, not of
    insertion or iteration luck. Instances left over at the end sit in, or
    downstream of, a cycle; one cycle is named in the raised error.
    """
    predecessors = {
        key: {connection.source for connection in instance.connections}
        for key, instance in instances.items()
    }
    successors: dict[InstanceKey, list[InstanceKey]] = {key: [] for key in instances}
    for key, sources in predecessors.items():
        for source in sources:
            successors[source].append(key)

    by_sort_key = {key.sort_key: key for key in instances}
    ready = [key.sort_key for key, sources in predecessors.items() if not sources]
    heapq.heapify(ready)
    remaining = {key: set(sources) for key, sources in predecessors.items()}
    order: list[InstanceKey] = []
    while ready:
        key = by_sort_key[heapq.heappop(ready)]
        order.append(key)
        for successor in successors[key]:
            remaining[successor].discard(key)
            if not remaining[successor]:
                heapq.heappush(ready, successor.sort_key)

    if len(order) != len(instances):
        raise ExpansionError(
            "Expanded graph holds a dependency cycle: "
            + " -> ".join(_describe(key) for key in (*_one_cycle(order, instances),))
        )
    return tuple(order)


def _one_cycle(
    order: list[InstanceKey],
    instances: Mapping[InstanceKey, ExpandedInstance],
) -> tuple[InstanceKey, ...]:
    """One dependency cycle among the unplaced instances, deterministically."""
    unplaced = [key for key in instances if key not in set(order)]
    unplaced.sort(key=lambda key: key.sort_key)
    outside = set(unplaced)
    start = unplaced[0]
    path: list[InstanceKey] = []
    seen: dict[InstanceKey, int] = {}
    current = start
    while current not in seen:
        seen[current] = len(path)
        path.append(current)
        feeders = sorted(
            (
                connection.source
                for connection in instances[current].connections
                if connection.source in outside
            ),
            key=lambda key: key.sort_key,
        )
        current = feeders[0]
    return tuple(path[seen[current] :])


def expand_graph(
    project: ProjectDocument,
    graph_id: str,
    *,
    project_id: str,
) -> ExpandedGraph:
    """Expand one target Graph into every instance it runs, call nodes inlined.

    ``graph_id`` names the target; :class:`UnknownGraphError` is raised when
    the Project holds no such Graph. ``project_id`` labels every produced
    :class:`InstanceKey`: the document is identity-free, so the caller states
    where it lives.
    """
    target = project.get_graph(graph_id)
    visits = _visits(project, target, ())
    indexes = {graph.id: _index(graph) for graph, _path in visits}

    pending: dict[InstanceKey, _Pending] = {}
    for graph, call_path in visits:
        for node in graph.document.nodes:
            if _is_call(node):
                continue
            pending[InstanceKey(project_id, graph.id, call_path, node.id)] = _Pending(
                node=node,
                refresh_generation=graph.refresh_generations.get(node.id, 0),
            )

    for graph, call_path in visits:
        index = indexes[graph.id]
        _wire_edges(index, call_path, indexes, project_id, pending)
        _wire_origins(index, call_path, indexes, project_id, pending)

    draft: dict[InstanceKey, ExpandedInstance] = {}
    for key, item in pending.items():
        # A caller-supplied input drops the callee's default origins on that
        # boundary; the supplied origins follow what an unsupplied input keeps.
        kept = () if item.caller_supplied else tuple(item.own_origins)
        draft[key] = ExpandedInstance(
            key=key,
            node=item.node,
            connections=tuple(sorted(item.connections, key=_incoming_order)),
            origins=(*kept, *item.caller_origins),
            refresh_generation=item.refresh_generation,
        )

    order = _topological_order(draft)
    return ExpandedGraph(
        project_id=project_id,
        graph_id=graph_id,
        instances={key: draft[key] for key in order},
        order=order,
    )


__all__ = ["ExpansionError", "expand_graph"]
