"""A tool call is a computation with no instance to record (ADR 0021).

An Agent calls a node as a tool by giving some of its inputs a value. The kernel
treats that as a temporary copy of the node's instance whose argument ports hold
the model's values as origins instead of whatever fed them in the document. The
copy is fingerprinted like any instance, so a repeated call with the same
arguments finds its result in the store, and it is planned and scheduled like any
other computation, so it is single-flight with canvas Runs and shares the
Project's concurrency budget.

What a tool call must never do is move an instance pointer: the node keeps
showing its own result, not the model's. The computation is therefore planned with
no instances to record, while the upstream computations it needs (the inputs the
document wires to it) keep theirs, because those results *are* what those nodes
currently compute.
"""

from collections.abc import Sequence
from dataclasses import replace
from types import MappingProxyType

from grafy_core.domain.graph_documents import GraphOrigin
from grafy_core.kernel.instances import ExpandedGraph, ExpandedInstance, InstanceKey
from grafy_core.kernel.scheduler import ComputationPlan, RunPlan


class UnknownToolInstanceError(ValueError):
    """The instance a tool call names is not in the expanded graph."""


def with_arguments(
    graph: ExpandedGraph,
    key: InstanceKey,
    arguments: Sequence[GraphOrigin],
) -> ExpandedGraph:
    """The graph with ``key``'s instance reading ``arguments`` on their ports.

    An argument replaces whatever fed its ``(to_port, to_plug)`` slot: an incoming
    connection or an origin the document held. Every other slot is untouched, so
    inputs wired from upstream stay fixed. Removing a connection cannot break the
    topological order, so ``order`` is kept as it is.
    """
    instance = graph.instances.get(key)
    if instance is None:
        raise UnknownToolInstanceError(
            f"node {key.node_id!r} of graph {key.graph_id!r} is not an instance "
            f"at call path {'/'.join(key.call_path) or '(root)'}"
        )
    slots = {(origin.to_port, origin.to_plug) for origin in arguments}
    kept_connections = tuple(
        connection
        for connection in instance.connections
        if (connection.edge.to_port, connection.edge.to_plug) not in slots
    )
    kept_origins = tuple(
        origin
        for origin in instance.origins
        if (origin.to_port, origin.to_plug) not in slots
    )
    called: ExpandedInstance = replace(
        instance,
        connections=kept_connections,
        origins=(*kept_origins, *arguments),
    )
    return ExpandedGraph(
        project_id=graph.project_id,
        graph_id=graph.graph_id,
        instances=MappingProxyType({**graph.instances, key: called}),
        order=graph.order,
    )


def without_pointer(plan: RunPlan, fingerprint: str) -> RunPlan:
    """``plan`` with the computation for ``fingerprint`` recording no instance."""
    computations = dict(plan.computations)
    computation = computations.get(fingerprint)
    if computation is not None:
        computations[fingerprint] = ComputationPlan(
            fingerprint=computation.fingerprint,
            representative=computation.representative,
            instances=(),
            depends_on=computation.depends_on,
            upstream_fingerprints=computation.upstream_fingerprints,
        )
    return RunPlan(targets=plan.targets, computations=computations)


__all__ = ["UnknownToolInstanceError", "with_arguments", "without_pointer"]
