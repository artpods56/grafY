import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from grafy_core.domain.artifact_outputs import (
    ArtifactOutputEnvelope,
    ArtifactOutputValue,
    artifact_outputs_from_storage,
    artifact_outputs_to_storage,
    normalize_artifact_outputs,
)

if TYPE_CHECKING:
    from grafy_core.domain.saved_graphs import (
        SavedGraphDocument,
        SavedGraphEdge,
        SavedGraphNode,
        SavedGraphOrigin,
    )


# Compatibility aliases for existing callers while the shared artifact-output
# vocabulary becomes the persistence boundary used by both materializations and
# invocation-cache entries.
MaterializedOutputValue = ArtifactOutputValue
MaterializedOutputEnvelope = ArtifactOutputEnvelope


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _node_execution_signature(node: "SavedGraphNode") -> tuple[object, ...]:
    pin = node.plugin_release_pin
    # JSON keeps booleans, integers, and floats distinct unlike Python equality.
    config = json.dumps(node.config_dict(), sort_keys=True, separators=(",", ":"))
    return (
        node.kind,
        node.operator_id,
        node.operator_version,
        config,
        tuple((plug.id, plug.port) for plug in node.input_plugs),
        None if pin is None else (pin.scope, pin.slug, pin.revision),
        tuple(
            (
                binding.variable,
                binding.artifact_type.id,
                binding.artifact_type.schema_version,
            )
            for binding in node.artifact_type_bindings
        ),
    )


def _incoming_edge_signature(edge: "SavedGraphEdge") -> tuple[object, ...]:
    projection = None
    if edge.projection is not None:
        projection = tuple(edge.projection.path)
    return (
        edge.from_node,
        edge.from_port,
        edge.to_node,
        edge.to_port,
        edge.to_plug,
        edge.collection_mode,
        projection,
        tuple((step.id, step.version) for step in edge.conversion_path),
    )


def _incoming_origin_signature(origin: "SavedGraphOrigin") -> tuple[object, ...]:
    # The value union carries no discriminator, so compare its exact JSON shape.
    value = json.dumps(
        origin.value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "origin",
        origin.id,
        origin.to_port,
        origin.to_plug,
        value,
        tuple((step.id, step.version) for step in origin.conversion_path),
    )


def _incoming_edges_by_target(
    document: "SavedGraphDocument",
) -> dict[str, tuple[tuple[object, ...], ...]]:
    grouped: dict[str, list[tuple[object, ...]]] = {}
    # Unplugged variadic inputs use saved edge order; explicit plugs own their order.
    for edge in sorted(
        document.edges, key=lambda edge: (edge.to_port, edge.to_plug or "")
    ):
        if not edge.enabled:
            continue
        grouped.setdefault(edge.to_node, []).append(_incoming_edge_signature(edge))
    for origin in sorted(
        document.origins, key=lambda origin: (origin.to_port, origin.to_plug or "")
    ):
        grouped.setdefault(origin.to_node, []).append(
            _incoming_origin_signature(origin)
        )
    return {node_id: tuple(signatures) for node_id, signatures in grouped.items()}


def materializations_for_compatible_nodes(
    *,
    previous_document: "SavedGraphDocument",
    next_document: "SavedGraphDocument",
    previous_materializations: Sequence["MaterializedNodeOutputs"],
    next_revision: int,
) -> list["MaterializedNodeOutputs"]:
    """Copy pins forward for nodes whose execution identity is unchanged.

    Position, layout, and presentation may change across a saved revision without
    invalidating already materialized outputs. A change to a node's execution
    identity or enabled inputs (edges and origins) invalidates that node and every
    descendant along enabled edges. Earlier revision bindings are retained
    unchanged.
    """
    if next_revision < 1:
        raise ValueError("Materialized output graph revision must be at least 1")

    previous_nodes = {node.id: node for node in previous_document.nodes}
    next_nodes = {node.id: node for node in next_document.nodes}
    previous_incoming = _incoming_edges_by_target(previous_document)
    next_incoming = _incoming_edges_by_target(next_document)

    invalidated: set[str] = set()
    for node_id, next_node in next_nodes.items():
        previous_node = previous_nodes.get(node_id)
        if (
            previous_node is None
            or _node_execution_signature(previous_node)
            != _node_execution_signature(next_node)
            or previous_incoming.get(node_id) != next_incoming.get(node_id)
        ):
            invalidated.add(node_id)

    downstream_nodes: dict[str, list[str]] = {}
    for edge in next_document.edges:
        if edge.enabled:
            downstream_nodes.setdefault(edge.from_node, []).append(edge.to_node)

    pending = deque(invalidated)
    while pending:
        node_id = pending.popleft()
        for downstream_node_id in downstream_nodes.get(node_id, ()):
            if downstream_node_id not in invalidated:
                invalidated.add(downstream_node_id)
                pending.append(downstream_node_id)

    carried: list[MaterializedNodeOutputs] = []
    for materialization in previous_materializations:
        if (
            materialization.node_id not in next_nodes
            or materialization.node_id in invalidated
        ):
            continue
        carried.append(
            replace(
                materialization,
                graph_revision=next_revision,
            )
        )
    return carried


@dataclass
class MaterializedNodeOutputs:
    workspace_id: UUID
    graph_id: UUID
    graph_revision: int
    node_id: str
    workflow_run_id: UUID
    outputs: dict[str, MaterializedOutputValue]
    materialized_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.graph_revision < 1:
            raise ValueError("Materialized output graph revision must be at least 1")
        self.node_id = self.node_id.strip()
        if self.node_id == "":
            raise ValueError("Materialized output node id must not be blank")
        if len(self.node_id) > 255:
            raise ValueError(
                "Materialized output node id must be at most 255 characters"
            )
        if self.materialized_at.tzinfo is None:
            raise ValueError("Materialized output timestamp must be timezone-aware")

        self.outputs = normalize_artifact_outputs(self.outputs)

    def storage_envelopes(self) -> list[dict[str, object]]:
        return self.outputs_to_storage(self.outputs)

    @staticmethod
    def outputs_to_storage(
        outputs: dict[str, MaterializedOutputValue],
    ) -> list[dict[str, object]]:
        return artifact_outputs_to_storage(outputs)

    @staticmethod
    def outputs_from_storage(
        value: object,
    ) -> dict[str, MaterializedOutputValue]:
        return artifact_outputs_from_storage(value)
