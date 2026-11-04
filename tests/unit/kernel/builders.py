"""Hand-built expanded graphs for the kernel fingerprint tests.

Builders here construct the pinned kernel types directly (``GraphNode``,
``GraphEdge``, ``GraphOrigin`` folded into ``ExpandedInstance`` and
``ExpandedGraph``) so a test can move one input at a time and nothing else
moves. No I/O, no clocks, no sleeps.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.graph_documents import (
    GraphPoint,
    GraphArtifactTypeBinding,
    GraphConversion,
    GraphEdge,
    GraphInputPlug,
    GraphNode,
    GraphNodeKind,
    GraphNodeLayout,
    GraphOrigin,
    GraphProjection,
)
from grafy_core.kernel.facts import FingerprintFacts
from grafy_core.kernel.instances import (
    Connection,
    ExpandedGraph,
    ExpandedInstance,
    InstanceKey,
)
from grafy_core.plugins import NodeCachePolicy

DEFAULT_PROJECT_ID = "project-1"
DEFAULT_GRAPH_ID = "graph-1"

ARTIFACT_ID_ONE = UUID("00000000-0000-0000-0000-000000000401")
ARTIFACT_ID_TWO = UUID("00000000-0000-0000-0000-000000000402")

type CollectionMode = Literal["direct", "map"]


def make_artifact(
    artifact_id: UUID = ARTIFACT_ID_ONE,
    *,
    artifact_type: str = "scalar.integer",
    schema_version: int = 1,
    content_hash: str | None = None,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        schema_version=schema_version,
        content_hash=content_hash,
    )


def make_plugs(*slots: tuple[str, str]) -> tuple[GraphInputPlug, ...]:
    return tuple(GraphInputPlug(id=plug_id, port=port) for plug_id, port in slots)


def make_bindings(
    *bindings: tuple[str, str, int],
) -> tuple[GraphArtifactTypeBinding, ...]:
    return tuple(
        GraphArtifactTypeBinding(
            variable=variable,
            artifact_type=ArtifactTypeKey(
                id=type_id,
                schema_version=schema_version,
            ),
        )
        for variable, type_id, schema_version in bindings
    )


def make_conversions(
    *steps: tuple[str, int],
) -> tuple[GraphConversion, ...]:
    return tuple(
        GraphConversion(id=step_id, version=version) for step_id, version in steps
    )


def make_point(x: float, y: float) -> GraphPoint:
    return GraphPoint(x=x, y=y)


def make_layout(width: float) -> GraphNodeLayout:
    return GraphNodeLayout(width=width)


def make_projection(path: Sequence[str]) -> GraphProjection:
    return GraphProjection(path=tuple(path))


def make_node(
    node_id: str,
    *,
    kind: GraphNodeKind = "builtin",
    operator_id: str = "value.integer",
    operator_version: int = 1,
    config: Mapping[str, object] | None = None,
    plugs: Sequence[tuple[str, str]] = (),
    bindings: Sequence[tuple[str, str, int]] = (),
    position: tuple[float, float] = (0.0, 0.0),
    width: float | None = None,
) -> GraphNode:
    return GraphNode(
        kind=kind,
        id=node_id,
        operator_id=operator_id,
        operator_version=operator_version,
        config={} if config is None else dict(config),
        position=make_point(position[0], position[1]),
        layout=None if width is None else GraphNodeLayout(width=width),
        input_plugs=make_plugs(*plugs),
        artifact_type_bindings=make_bindings(*bindings),
    )


def make_edge(
    edge_id: str,
    from_node: str,
    to_node: str,
    *,
    from_port: str = "result",
    to_port: str = "value",
    to_plug: str | None = None,
    collection_mode: CollectionMode = "direct",
    projection: Sequence[str] | None = None,
    conversion: Sequence[tuple[str, int]] = (),
    enabled: bool = True,
    route_offset: tuple[float, float] | None = None,
) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
        to_plug=to_plug,
        collection_mode=collection_mode,
        projection=(
            None if projection is None else GraphProjection(path=tuple(projection))
        ),
        conversion_path=make_conversions(*conversion),
        enabled=enabled,
        route_offset=None if route_offset is None else make_point(*route_offset),
    )


def make_origin(
    origin_id: str,
    to_node: str,
    *,
    to_port: str = "value",
    to_plug: str | None = None,
    value: ArtifactRef | None = None,
    collection_mode: CollectionMode = "direct",
    conversion: Sequence[tuple[str, int]] = (),
) -> GraphOrigin:
    return GraphOrigin(
        id=origin_id,
        to_node=to_node,
        to_port=to_port,
        to_plug=to_plug,
        value=make_artifact() if value is None else value,
        collection_mode=collection_mode,
        conversion_path=make_conversions(*conversion),
    )


def make_key(
    node_id: str,
    *,
    project_id: str = DEFAULT_PROJECT_ID,
    graph_id: str = DEFAULT_GRAPH_ID,
    call_path: tuple[str, ...] = (),
    map_index: int | None = None,
) -> InstanceKey:
    return InstanceKey(
        project_id=project_id,
        graph_id=graph_id,
        call_path=call_path,
        node_id=node_id,
        map_index=map_index,
    )


def incoming_order(
    edge: GraphEdge,
) -> tuple[str, str]:
    """The stable per-target order the kernel expands connections in."""
    return (edge.to_port, edge.to_plug or "")


def _topological_order(
    keys: Sequence[InstanceKey],
    connections: Mapping[InstanceKey, Sequence[Connection]],
) -> tuple[InstanceKey, ...]:
    """Deterministic topological order; keys no feeder set can place come last."""
    remaining = {key.sort_key: key for key in keys}
    placed: set[InstanceKey] = set()
    order: list[InstanceKey] = []
    while remaining:
        ready = sorted(
            sort_key
            for sort_key, key in remaining.items()
            if all(
                connection.source in placed for connection in connections.get(key, ())
            )
        )
        if not ready:
            break
        key = remaining.pop(ready[0])
        placed.add(key)
        order.append(key)
    order.extend(remaining[sort_key] for sort_key in sorted(remaining))
    return tuple(order)


@dataclass
class ExpandedGraphBuilder:
    """Places instances under explicit keys, then wires them key to key.

    Unlike a saved document, a builder can hold two instances of one node
    content at two call paths, which is what the shared-computation rule of
    ADR 0020 is about.
    """

    project_id: str = DEFAULT_PROJECT_ID
    graph_id: str = DEFAULT_GRAPH_ID
    instances: dict[InstanceKey, ExpandedInstance] = field(default_factory=dict)
    feeders: dict[InstanceKey, list[Connection]] = field(default_factory=dict)

    def add_instance(
        self,
        node: GraphNode,
        *,
        node_id: str | None = None,
        call_path: tuple[str, ...] = (),
        map_index: int | None = None,
        refresh_generation: int = 0,
    ) -> InstanceKey:
        key = make_key(
            node.id if node_id is None else node_id,
            project_id=self.project_id,
            graph_id=self.graph_id,
            call_path=call_path,
            map_index=map_index,
        )
        if key in self.instances:
            raise ValueError(f"Duplicate instance key for node {node.id}")
        self.instances[key] = ExpandedInstance(
            key=key,
            node=node,
            connections=(),
            origins=(),
            refresh_generation=refresh_generation,
        )
        self.feeders[key] = []
        return key

    def add_connection(self, target: InstanceKey, connection: Connection) -> None:
        self.feeders[target].append(connection)
        self.instances[target] = replace(
            self.instances[target],
            connections=tuple(self.feeders[target]),
        )

    def connect(
        self,
        source: InstanceKey,
        target: InstanceKey,
        *,
        edge_id: str | None = None,
        from_port: str = "result",
        to_port: str = "value",
        to_plug: str | None = None,
        collection_mode: CollectionMode = "direct",
        projection: Sequence[str] | None = None,
        conversion: Sequence[tuple[str, int]] = (),
    ) -> Connection:
        connection = Connection(
            source=source,
            edge=make_edge(
                f"{source.node_id}->{target.node_id}" if edge_id is None else edge_id,
                source.node_id,
                target.node_id,
                from_port=from_port,
                to_port=to_port,
                to_plug=to_plug,
                collection_mode=collection_mode,
                projection=projection,
                conversion=conversion,
            ),
        )
        self.add_connection(target, connection)
        return connection

    def attach_origin(self, target: InstanceKey, origin: GraphOrigin) -> None:
        instance = self.instances[target]
        self.instances[target] = replace(instance, origins=(*instance.origins, origin))

    def set_refresh_generation(self, target: InstanceKey, generation: int) -> None:
        self.instances[target] = replace(
            self.instances[target],
            refresh_generation=generation,
        )

    def build(self, order: Sequence[InstanceKey] | None = None) -> ExpandedGraph:
        """Freeze the graph. ``order`` overrides the computed topological order."""
        for target, feeders in self.feeders.items():
            self.instances[target] = replace(
                self.instances[target],
                connections=tuple(feeders),
            )
        return ExpandedGraph(
            project_id=self.project_id,
            graph_id=self.graph_id,
            instances=dict(self.instances),
            order=(
                tuple(order)
                if order is not None
                else _topological_order(list(self.instances), self.feeders)
            ),
        )


def expand_document(
    nodes: Sequence[GraphNode],
    edges: Sequence[GraphEdge] = (),
    origins: Sequence[GraphOrigin] = (),
    *,
    project_id: str = DEFAULT_PROJECT_ID,
    graph_id: str = DEFAULT_GRAPH_ID,
    call_path: tuple[str, ...] = (),
    refresh_generations: Mapping[str, int] = MappingProxyType({}),
    order: Sequence[InstanceKey] | None = None,
) -> ExpandedGraph:
    """Expand a node/edge/origin set the way the kernel would.

    One instance per node at one call path, enabled connections in
    ``(to_port, to_plug or "")`` order with document order breaking ties, and
    origins in the order they were written.
    """
    builder = ExpandedGraphBuilder(project_id=project_id, graph_id=graph_id)
    keys = {node.id: builder.add_instance(node, call_path=call_path) for node in nodes}
    for edge in sorted(
        (edge for edge in edges if edge.enabled),
        key=incoming_order,
    ):
        builder.add_connection(
            keys[edge.to_node],
            Connection(source=keys[edge.from_node], edge=edge),
        )
    for origin in origins:
        builder.attach_origin(keys[origin.to_node], origin)
    for node_id, generation in refresh_generations.items():
        builder.set_refresh_generation(keys[node_id], generation)
    return builder.build(order)


@dataclass(frozen=True, slots=True)
class FakeFacts:
    """``FingerprintFacts`` stand-in with settable deployment facts.

    Implementation digests are keyed by operator id, cache policies and secret
    revisions by node id: the fake ignores project, graph and call path on
    purpose, so a fact follows what a node runs rather than where it sits.
    """

    implementations: Mapping[str, str] = MappingProxyType({})
    default_implementation: str = "impl-default"
    cache_policies: Mapping[str, NodeCachePolicy] = MappingProxyType({})
    secrets: Mapping[str, Mapping[str, str]] = MappingProxyType({})

    def implementation_digest(self, node: GraphNode) -> str:
        return self.implementations.get(node.operator_id, self.default_implementation)

    def cache_policy(self, node: GraphNode) -> NodeCachePolicy:
        return self.cache_policies.get(node.id, NodeCachePolicy.EXACT)

    def secret_revisions(self, key: InstanceKey) -> Mapping[str, str]:
        return self.secrets.get(key.node_id, {})

    def with_implementation(self, operator_id: str, digest: str) -> "FakeFacts":
        return replace(
            self, implementations={**self.implementations, operator_id: digest}
        )

    def with_cache_policy(
        self,
        node_id: str,
        policy: NodeCachePolicy,
    ) -> "FakeFacts":
        return replace(self, cache_policies={**self.cache_policies, node_id: policy})

    def with_secrets(self, node_id: str, revisions: Mapping[str, str]) -> "FakeFacts":
        return replace(self, secrets={**self.secrets, node_id: revisions})


#: The fake is checked against the pinned protocol at import time.
_FACTS_CONTRACT: FingerprintFacts = FakeFacts()

__all__ = [
    "ARTIFACT_ID_ONE",
    "ARTIFACT_ID_TWO",
    "DEFAULT_GRAPH_ID",
    "DEFAULT_PROJECT_ID",
    "ExpandedGraphBuilder",
    "FakeFacts",
    "CollectionMode",
    "expand_document",
    "incoming_order",
    "make_artifact",
    "make_bindings",
    "make_conversions",
    "make_edge",
    "make_key",
    "make_layout",
    "make_node",
    "make_origin",
    "make_plugs",
    "make_point",
    "make_projection",
]
