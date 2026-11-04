"""Run planning: the stale part of the upstream closure of a Run's targets.

ADR 0020: a Run is a demand for its targets to become fresh, so it schedules
nothing more than what must be recomputed. Starting at the targets, the walk
follows ``connections[*].source`` upstream. An instance whose current
fingerprint already has a result in the store is fresh: it is not planned and
the walk stops there, because a fresh result needs nothing upstream of it.
Every other reached instance is stale and is planned.

Planned instances are grouped by fingerprint into one ``ComputationPlan`` per
fingerprint, so two calls of the same Graph with the same inputs share one
computation and one result. ``instances`` holds *every* instance of the graph
whose fingerprint is that one, in ``graph.order`` order, so all of them get
their result pointer recorded; ``representative`` is the first of those.
``upstream_fingerprints`` comes from the representative's connections, and
``depends_on`` lists only the upstream fingerprints that are themselves
planned computations: fresh upstreams are already satisfied by the store and
never enter it, and neither does the computation's own fingerprint.
"""

from collections import deque
from collections.abc import Mapping, Sequence

from grafy_core.kernel.instances import ExpandedGraph, InstanceKey
from grafy_core.kernel.results import ResultStore
from grafy_core.kernel.scheduler import ComputationPlan, RunPlan


def _describe(key: InstanceKey) -> str:
    """Name one instance in an error message."""
    call_path = "/".join(key.call_path) if key.call_path else "(root)"
    map_index = "" if key.map_index is None else f" map_index={key.map_index}"
    return (
        f"instance node={key.node_id!r} graph={key.graph_id!r} "
        f"call_path={call_path}{map_index}"
    )


async def plan_run(
    *,
    graph: ExpandedGraph,
    fingerprints: Mapping[InstanceKey, str],
    targets: Sequence[InstanceKey],
    store: ResultStore,
) -> RunPlan:
    """Plan the stale computations a Run needs for ``targets``.

    ``fingerprints`` must cover the targets and every instance the walk can
    reach; a target or a reached instance without one is a ``ValueError``
    naming the key, never a silently skipped dependency. The store is queried
    once per distinct fingerprint. A fully fresh target set yields a plan with
    no computations.
    """
    deduped_targets: list[InstanceKey] = []
    seen_targets: set[InstanceKey] = set()
    for target in targets:
        if target not in graph.instances:
            raise ValueError(
                f"target {_describe(target)} is not an instance of this expanded graph"
            )
        if target not in fingerprints:
            raise ValueError(f"target {_describe(target)} has no fingerprint")
        if target not in seen_targets:
            seen_targets.add(target)
            deduped_targets.append(target)

    # Freshness is a property of the fingerprint, so one store query per
    # distinct fingerprint answers every instance that shares it. The walk
    # itself is per instance: a second instance of one stale fingerprint is
    # reached by a different path and its own edges must be followed too.
    fresh: set[str] = set()
    stale: set[str] = set()
    expanded: set[InstanceKey] = set()
    frontier = deque(deduped_targets)
    while frontier:
        key = frontier.popleft()
        if key in expanded:
            continue
        expanded.add(key)
        fingerprint = fingerprints.get(key)
        if fingerprint is None:
            raise ValueError(
                f"{_describe(key)}, reached upstream of a target, has no "
                "fingerprint: every reachable instance must be fingerprinted"
            )
        if fingerprint in fresh:
            continue
        if fingerprint not in stale:
            if await store.get_result(fingerprint) is not None:
                # Fresh: not planned, and nothing above it is reached.
                fresh.add(fingerprint)
                continue
            stale.add(fingerprint)
        for connection in graph.instances[key].connections:
            source = connection.source
            if source not in graph.instances:
                raise ValueError(
                    f"{_describe(key)} is fed by {_describe(source)}, which is "
                    "not an instance of this expanded graph"
                )
            frontier.append(source)

    # Group by fingerprint over the whole graph in one pass over ``order``:
    # an instance that shares a planned fingerprint shares its computation,
    # whoever reached it. The first fingerprint sighting fixes both the
    # representative and the dict position, so the plan is deterministic.
    members: dict[str, list[InstanceKey]] = {}
    for key in graph.order:
        fingerprint = fingerprints.get(key)
        if fingerprint is None or fingerprint not in stale:
            continue
        bucket = members.get(fingerprint)
        if bucket is None:
            members[fingerprint] = [key]
        else:
            bucket.append(key)

    def fingerprint_of(key: InstanceKey) -> str:
        fingerprint = fingerprints.get(key)
        if fingerprint is None:
            raise ValueError(
                f"{_describe(key)}, upstream of a planned computation, has no "
                "fingerprint"
            )
        return fingerprint

    computations: dict[str, ComputationPlan] = {}
    for fingerprint, group in members.items():
        representative = graph.instances[group[0]]
        upstream_fingerprints = {
            connection.source: fingerprint_of(connection.source)
            for connection in representative.connections
        }
        depends_on: set[str] = set()
        for member_key in group:
            for connection in graph.instances[member_key].connections:
                source_fingerprint = fingerprint_of(connection.source)
                if source_fingerprint == fingerprint:
                    continue
                if source_fingerprint in stale:
                    depends_on.add(source_fingerprint)
        computations[fingerprint] = ComputationPlan(
            fingerprint=fingerprint,
            representative=representative,
            instances=tuple(group),
            depends_on=frozenset(depends_on),
            upstream_fingerprints=upstream_fingerprints,
        )

    for fingerprint, computation in computations.items():
        unresolved = computation.depends_on - computations.keys()
        if unresolved or fingerprint in computation.depends_on:
            named = ", ".join(sorted(unresolved)) or fingerprint
            raise RuntimeError(
                f"Computation {fingerprint!r} depends on {named!r}, which is "
                "not a computation of this plan: a plan must be closed under "
                "its dependencies"
            )

    return RunPlan(targets=tuple(deduped_targets), computations=computations)


__all__ = ["plan_run"]
