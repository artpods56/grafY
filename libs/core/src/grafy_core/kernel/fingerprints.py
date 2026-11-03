"""Node fingerprints: the address a result is stored under (ADR 0020).

A fingerprint answers one question: would this node instance compute the same
output now as it did when the result was recorded? It is the sha256 of a
canonical JSON document (sorted keys, tight separators, ASCII) over two
sections.

**Identity** — what this node runs as: ``node.kind``, ``operator_id``,
``operator_version``, its configuration, the implementation identity supplied by
``FingerprintFacts``, the active input plugs (the node's own ``input_plugs`` in
the node's own order, restricted to the plugs an edge or an origin actually
feeds), its artifact type bindings, the secret revisions it runs under (only
when there are any), and its refresh generation (only when its cache policy is
``NEVER``, because only then does an explicit refresh change what it computes).

**Inputs** — what arrives, in the order it arrives: each connection in the
instance's own order carrying its ports, plug, collection mode, projection,
conversion path and the *fingerprint of the upstream instance*, then each
origin sorted by ``(to_port, to_plug or "")`` carrying its slot, value,
collection mode and conversion path. The upstream fingerprint is what makes the
digest transitive: an upstream configuration change moves the upstream digest
and therefore every descendant's, while an unchanged subtree keeps its result.

Everything else stays out. Node ids, positions, layout and canvas routing,
edge and origin ids, and the ``InstanceKey`` itself — project, graph, call path,
node id, map index — never enter a digest, so two instances with identical
content and identical upstream fingerprints get the same fingerprint wherever
they sit. That equality is what lets two calls of the same Graph with the same
inputs compute once and share one stored result.

The walk follows ``graph.order``, which is already topological: an instance can
only be fingerprinted once every instance feeding it has been. A connection
whose source is missing from the graph, or whose source sits later in the order
than this instance, raises ``ValueError`` naming the instance rather than
digesting an upstream it never read — the direction that can never claim reuse
for a dependency it could not see.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence

from grafy_core.domain.graph_documents import GraphConversion
from grafy_core.kernel.facts import FingerprintFacts
from grafy_core.kernel.instances import (
    ExpandedGraph,
    ExpandedInstance,
    InstanceKey,
)
from grafy_core.plugins import NodeCachePolicy


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _describe(key: InstanceKey) -> str:
    """Name one instance in an error message (never in a digest)."""
    call_path = "/".join(key.call_path) if key.call_path else "(root)"
    map_index = "" if key.map_index is None else f" map_index={key.map_index}"
    return (
        f"instance node={key.node_id!r} graph={key.graph_id!r} "
        f"call_path={call_path}{map_index}"
    )


def _fed_plugs(instance: ExpandedInstance) -> set[str]:
    """Input plug ids this instance's connections and origins actually feed."""
    fed = {
        connection.edge.to_plug
        for connection in instance.connections
        if connection.edge.to_plug is not None
    }
    fed.update(
        origin.to_plug for origin in instance.origins if origin.to_plug is not None
    )
    return fed


def _identity(
    instance: ExpandedInstance,
    facts: FingerprintFacts,
) -> dict[str, object]:
    node = instance.node
    fed = _fed_plugs(instance)
    identity: dict[str, object] = {
        "kind": node.kind,
        "operator_id": node.operator_id,
        "operator_version": node.operator_version,
        "config": node.config_dict(),
        "implementation": facts.implementation_digest(node),
        # The node's own plug order is execution meaning; only fed plugs count,
        # so a spare plug kept for the node's next member stays out.
        "input_plugs": [
            [plug.id, plug.port] for plug in node.input_plugs if plug.id in fed
        ],
        "artifact_type_bindings": [
            [
                binding.variable,
                binding.artifact_type.id,
                binding.artifact_type.schema_version,
            ]
            for binding in node.artifact_type_bindings
        ],
    }
    # Opaque revisions bind a credential-dependent node to the secret state it
    # ran under: rotation moves the digest without any secret value entering it.
    revisions = facts.secret_revisions(instance.key)
    if revisions:
        identity["secret_revisions"] = dict(revisions)
    # Only a non-deterministic node's explicit refresh changes what it computes,
    # so only that one carries the generation.
    if facts.cache_policy(node) is NodeCachePolicy.NEVER:
        identity["refresh_generation"] = instance.refresh_generation
    return identity


def _conversion_path(
    path: Sequence[GraphConversion],
) -> list[list[str | int]]:
    return [[step.id, step.version] for step in path]


def _inputs(
    instance: ExpandedInstance,
    graph: ExpandedGraph,
    fingerprints: Mapping[InstanceKey, str],
) -> list[object]:
    entries: list[object] = []
    for connection in instance.connections:
        source = connection.source
        if source not in graph.instances:
            raise ValueError(
                f"{_describe(instance.key)} is fed by {_describe(source)}, "
                "which is not an instance of this expanded graph"
            )
        upstream = fingerprints.get(source)
        if upstream is None:
            raise ValueError(
                f"{_describe(instance.key)} is fed by {_describe(source)}, whose "
                "fingerprint has not been computed: graph.order must place every "
                "source before the instances it feeds"
            )
        edge = connection.edge
        entries.append(
            [
                edge.from_port,
                edge.to_port,
                edge.to_plug,
                edge.collection_mode,
                None if edge.projection is None else list(edge.projection.path),
                _conversion_path(edge.conversion_path),
                upstream,
            ]
        )
    for origin in sorted(
        instance.origins,
        key=lambda origin: (origin.to_port, origin.to_plug or ""),
    ):
        # The value union carries no discriminator, so its exact JSON shape is
        # the artifact identity that enters the digest.
        value = origin.value.model_dump(mode="json")
        entries.append(
            [
                origin.to_port,
                origin.to_plug,
                _canonical(value),
                origin.collection_mode,
                _conversion_path(origin.conversion_path),
            ]
        )
    return entries


def compute_fingerprints(
    graph: ExpandedGraph,
    facts: FingerprintFacts,
) -> dict[InstanceKey, str]:
    """Fingerprint every instance of an expanded graph in one topological pass.

    ``graph.order`` is walked as given: it is expected to be a topological order
    over ``connections``, and an instance whose feeder has not been fingerprinted
    yet is a document error, not something to guess past. The result maps each
    instance key to the hex sha256 of its digest; two instances with the same
    content and the same upstream digests map to the same value.
    """
    fingerprints: dict[InstanceKey, str] = {}
    for key in graph.order:
        instance = graph.instances.get(key)
        if instance is None:
            raise ValueError(
                f"{_describe(key)} is listed in graph.order but is not an "
                "instance of this expanded graph"
            )
        document = {
            "identity": _identity(instance, facts),
            "inputs": _inputs(instance, graph, fingerprints),
        }
        fingerprints[key] = hashlib.sha256(
            _canonical(document).encode("utf-8")
        ).hexdigest()
    return fingerprints


__all__ = ["compute_fingerprints"]
