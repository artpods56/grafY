"""Node instances: the unit that owns a fingerprint and a state (ADR 0020)."""

from collections.abc import Mapping
from dataclasses import dataclass

from grafy_core.domain.saved_graphs import (
    SavedGraphEdge,
    SavedGraphNode,
    SavedGraphOrigin,
)


@dataclass(frozen=True, slots=True)
class InstanceKey:
    """``(project, graph, call path, node id[, map index])``.

    ``call_path`` lists the ids of the call nodes entered to reach ``graph_id``,
    outermost first. It is empty for a Graph run directly. ``map_index`` is
    reserved for MAP items and stays ``None`` until that decision is made.
    """

    project_id: str
    graph_id: str
    call_path: tuple[str, ...]
    node_id: str
    map_index: int | None = None

    @property
    def sort_key(self) -> tuple[str, str, tuple[str, ...], str, int]:
        return (
            self.project_id,
            self.graph_id,
            self.call_path,
            self.node_id,
            -1 if self.map_index is None else self.map_index,
        )


@dataclass(frozen=True, slots=True)
class Connection:
    """One enabled incoming edge, resolved to the upstream instance it reads.

    ``edge`` carries the transport (ports, plug, collection mode, projection,
    conversion path). Its ``from_node`` / ``to_node`` ids are those of the
    graph the edge was written in, not of the expanded instances; ``source``
    is the authoritative upstream.
    """

    source: InstanceKey
    edge: SavedGraphEdge


@dataclass(frozen=True, slots=True)
class ExpandedInstance:
    """A node placed at a call path, with its incoming connections and origins.

    ``connections`` are the enabled incoming edges in a stable order (sorted by
    ``(to_port, to_plug or "")``, ties keep document edge order). ``origins``
    are the artifacts held on inputs that have no incoming edge.
    ``refresh_generation`` is the document's refresh counter for this node.
    """

    key: InstanceKey
    node: SavedGraphNode
    connections: tuple[Connection, ...]
    origins: tuple[SavedGraphOrigin, ...]
    refresh_generation: int = 0


@dataclass(frozen=True, slots=True)
class ExpandedGraph:
    """Every instance of one target Graph, call nodes inlined.

    ``order`` is a deterministic topological order over ``connections``.
    Call nodes do not appear: the caller's edges into a call connect to the
    callee's input boundary instances and the callee's output boundary
    instances connect to the call's consumers.
    """

    project_id: str
    graph_id: str
    instances: Mapping[InstanceKey, ExpandedInstance]
    order: tuple[InstanceKey, ...]
