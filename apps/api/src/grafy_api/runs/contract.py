"""Bind one expanded instance to the operator, contracts and inputs it runs with.

``execution/compiler.py`` compiled a whole submitted ``RunRequest``: it ordered
nodes, checked every edge against the contracts of both endpoints and produced a
plan for one graph run. A computation under ADR 0020 is one instance whose
upstream outputs are already stored, so the same work narrows to one node: build
its operator, resolve its artifact type bindings and contracts, decide ONCE or
MAP from the collection modes that arrive, and turn each incoming connection and
origin into an ``InputSlot`` saying what value feeds which input and how that
value is projected and converted on the way in.

Because the upstream node does not run here, its artifact type and shape are read
from the reference its stored result holds rather than from its compiled output
port: the value that arrived is what actually arrives. Whole-graph concerns --
ordering, cycles, which instances to run at all -- belong to the kernel, not to
this module.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from grafy_core.artifacts import (
    ArtifactFieldProjection,
    ArtifactRefSequence,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
)
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
from grafy_core.conversions import (
    MAX_ARTIFACT_CONVERSION_HOPS,
    ArtifactConversionKey,
    Conversion,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.graph_documents import (
    GraphConversion,
    GraphEdge,
    GraphNode,
    GraphOrigin,
)
from grafy_core.kernel.instances import ExpandedInstance, InstanceKey
from grafy_core.kernel.project import (
    GRAPH_INPUT_OPERATOR_ID,
    GRAPH_OUTPUT_OPERATOR_ID,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InputPortSpec,
    Node,
    NodeContractResolutionError,
    PortShape,
    ResolvedNodeContracts,
    resolve_node_contracts,
)
from grafy_core.plugins import (
    NodeRegistration,
    PluginRegistry,
    PluginRuntimeContext,
    UnknownOperatorError,
)
from grafy_core.runtime.invocation import (
    InvocationError,
    InvocationMode,
    NodeInvocation,
    ResolvedNodeContractView,
    effective_input_shape,
    validate_invocation,
)

from grafy_api.runs.errors import NodeComputationError


#: The boundary nodes are not registered operators: a Graph's own input and
#: output pass their single value straight through (ADR 0020).
BOUNDARY_OPERATOR_IDS: frozenset[str] = frozenset(
    {GRAPH_INPUT_OPERATOR_ID, GRAPH_OUTPUT_OPERATOR_ID}
)

_ORIGIN_SOURCE_ID = "origin"
_ORIGIN_SOURCE_PORT = "value"


def is_boundary(instance: ExpandedInstance) -> bool:
    """Whether this instance is a Graph's own input or output."""

    return instance.node.operator_id in BOUNDARY_OPERATOR_IDS


@dataclass(frozen=True, slots=True)
class InputPortPlan:
    """How one input port collects the values that feed it."""

    name: str
    variadic: bool = False
    instance_plugs: bool = False
    #: The ids of this port's input plugs, in the order the node declares them. A
    #: port that keeps spare plugs lists only the ones a connection feeds.
    plugs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InputSlot:
    """One incoming value, with the transformation its connection applies to it.

    ``projection`` and ``conversion_path`` are resolved against the artifact type
    that actually arrived, so applying them needs no contract again. ``label``
    names the connection in a failure message.
    """

    to_port: str
    to_plug: str | None
    value: ArtifactOutputValue
    projection: ArtifactFieldProjection | None
    conversion_path: tuple[Conversion[Any, Any], ...]
    map_driven: bool
    label: str
    source_node_id: str
    source_port: str
    target_node_id: str


@dataclass(frozen=True, slots=True)
class ServiceFeed:
    """One service output the consumer's runner builds from the connected instance.

    The object is not a stored result. ``source`` is the provider instance the
    edge points at, and the ports name the field to take and the input to fill.
    """

    source: ExpandedInstance
    from_port: str
    to_port: str


@dataclass(frozen=True, slots=True)
class BoundNode:
    """One instance ready to run with the values its upstream instances stored."""

    node: Node[Any, Any, Any]
    registration: NodeRegistration
    resolved_contracts: ResolvedNodeContracts
    invocation: NodeInvocation
    config: JsonObject
    artifact_type_bindings: Mapping[str, ArtifactTypeKey]
    ports: tuple[InputPortPlan, ...]
    slots: tuple[InputSlot, ...]
    service_feeds: tuple[ServiceFeed, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(
            self,
            "artifact_type_bindings",
            MappingProxyType(dict(self.artifact_type_bindings)),
        )


@dataclass(frozen=True, slots=True)
class _Incoming:
    """One connection or origin before its edge transformations are resolved."""

    to_port: str
    to_plug: str | None
    value: ArtifactOutputValue
    projection_path: tuple[str, ...] | None
    conversion_path: tuple[GraphConversion, ...]
    map_driven: bool
    label: str
    source_node_id: str
    source_port: str
    target_node_id: str


class NodeContractBinder:
    """Resolve the operator, contracts and input slots of one instance.

    The registry is read once, in the constructor, for the artifact types it
    declares and can project. A call to :meth:`bind` reads nothing but its
    arguments, so a runner may bind any number of instances concurrently.
    """

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        plugin_context: PluginRuntimeContext | None = None,
    ) -> None:
        self._registry = registry
        self._plugin_context = plugin_context
        self._artifact_types = {
            artifact_type.key
            for artifact_type in (
                *registry.artifact_types,
                *registry.artifact_type_dependencies,
            )
        }
        self._projectable_artifact_types = {
            artifact_type.key: artifact_type
            for artifact_type in registry.artifact_types
            if artifact_type.field_projections
        }

    def bind(
        self,
        instance: ExpandedInstance,
        upstream: Mapping[InstanceKey, Mapping[str, ArtifactOutputValue]],
        service_sources: Mapping[InstanceKey, ExpandedInstance] | None = None,
    ) -> BoundNode:
        graph_node = instance.node
        node, registration = self.build_node(graph_node)
        bindings = graph_node.artifact_type_binding_map()
        for variable, artifact_type in bindings.items():
            if artifact_type in self._artifact_types:
                continue
            raise NodeComputationError(
                f"Node {graph_node.id!r} artifact type variable {variable!r} is "
                f"bound to unavailable artifact type {artifact_type.id}@"
                f"{artifact_type.schema_version}"
            )
        try:
            resolved_contracts = resolve_node_contracts(
                node,
                bindings,
                graph_node.config_dict(),
            )
        except NodeContractResolutionError as exc:
            raise NodeComputationError(
                f"Node {graph_node.id!r} ({node.operator_id}@"
                f"{node.operator_version}) has invalid artifact type "
                f"bindings: {exc}"
            ) from exc
        view = ResolvedNodeContractView.of(node.operator_id, resolved_contracts)
        providers = {} if service_sources is None else service_sources
        self._reject_service_origins(instance, resolved_contracts)
        self._reject_stored_service_feeds(instance, resolved_contracts, providers)
        artifact_instance = replace(
            instance,
            connections=tuple(
                connection
                for connection in instance.connections
                if connection.source not in providers
            ),
        )
        incoming = self._incoming(artifact_instance, upstream)
        invocation = _derive_invocation(view, graph_node.id, incoming)
        self._validate_input_plugs(node, graph_node, incoming)

        slots: list[InputSlot] = []
        connections_by_port: dict[str, int] = {}
        for item in incoming:
            port = resolved_contracts.input_contract.ports.get(item.to_port)
            if port is None:
                raise NodeComputationError(
                    f"{item.label} references unknown input port "
                    f"{item.to_port!r} on node {graph_node.id!r}"
                )
            slot = self._slot(item)
            _check_target(slot, port, view, invocation)
            connections_by_port[slot.to_port] = (
                connections_by_port.get(slot.to_port, 0) + 1
            )
            if not port.variadic and connections_by_port[slot.to_port] > 1:
                raise NodeComputationError(
                    f"Node {graph_node.id!r} input {slot.to_port!r} accepts one "
                    f"connection, got {connections_by_port[slot.to_port]}"
                )
            slots.append(slot)
        service_feeds = self._service_feeds(
            instance,
            resolved_contracts,
            providers,
            connections_by_port,
        )
        for name, port in resolved_contracts.input_contract.ports.items():
            if port.required and connections_by_port.get(name, 0) == 0:
                raise NodeComputationError(
                    f"Node {graph_node.id!r} ({node.operator_id}@"
                    f"{node.operator_version}) required input {name!r} has no "
                    "incoming connection"
                )

        fed_plugs = {item.to_plug for item in incoming if item.to_plug is not None}
        return BoundNode(
            node=node,
            registration=registration,
            resolved_contracts=resolved_contracts,
            invocation=invocation,
            config=graph_node.config_dict(),
            artifact_type_bindings=bindings,
            ports=tuple(
                InputPortPlan(
                    name=name,
                    variadic=port.variadic,
                    instance_plugs=port.instance_plugs,
                    plugs=tuple(
                        plug.id
                        for plug in graph_node.input_plugs
                        if plug.port == name
                        and (not port.spare_plugs or plug.id in fed_plugs)
                    ),
                )
                for name, port in resolved_contracts.input_contract.ports.items()
            ),
            slots=tuple(slots),
            service_feeds=service_feeds,
        )

    def build_node(
        self,
        graph_node: GraphNode,
    ) -> tuple[Node[Any, Any, Any], NodeRegistration]:
        return self._build_node(graph_node)

    def _reject_service_origins(
        self,
        instance: ExpandedInstance,
        resolved_contracts: ResolvedNodeContracts,
    ) -> None:
        ports = resolved_contracts.input_contract.ports
        for origin in instance.origins:
            port = ports.get(origin.to_port)
            if port is None or port.kind != "service":
                continue
            raise NodeComputationError(
                f"Node {instance.key.node_id!r} service input {origin.to_port!r} "
                "cannot be fed by an origin"
            )

    def _reject_stored_service_feeds(
        self,
        instance: ExpandedInstance,
        resolved_contracts: ResolvedNodeContracts,
        providers: Mapping[InstanceKey, ExpandedInstance],
    ) -> None:
        ports = resolved_contracts.input_contract.ports
        for connection in instance.connections:
            if connection.source in providers:
                continue
            port = ports.get(connection.edge.to_port)
            if port is None or port.kind != "service":
                continue
            raise NodeComputationError(
                f"Node {instance.key.node_id!r} service input "
                f"{connection.edge.to_port!r} cannot be fed by a stored output"
            )

    def _service_feeds(
        self,
        instance: ExpandedInstance,
        resolved_contracts: ResolvedNodeContracts,
        providers: Mapping[InstanceKey, ExpandedInstance],
        connections_by_port: dict[str, int],
    ) -> tuple[ServiceFeed, ...]:
        """Count each service edge as fed, without reading a stored result."""

        ports = resolved_contracts.input_contract.ports
        feeds: list[ServiceFeed] = []
        for connection in instance.connections:
            source = providers.get(connection.source)
            if source is None:
                continue
            edge = connection.edge
            port = ports.get(edge.to_port)
            if port is None:
                raise NodeComputationError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} references unknown input "
                    f"port {edge.to_port!r} on node {instance.key.node_id!r}"
                )
            if port.kind != "service":
                raise NodeComputationError(
                    f"Node {instance.key.node_id!r} input {edge.to_port!r} is not "
                    f"a service input; the service output of node "
                    f"{source.key.node_id!r} feeds only a service input"
                )
            source_node, _registration = self._build_node(source.node)
            source_port = source_node.output_contract.ports.get(edge.from_port)
            if source_port is None or source_port.kind != "service":
                raise NodeComputationError(
                    f"Node {source.key.node_id!r} output {edge.from_port!r} is "
                    "not a service output"
                )
            if set(port.service_contracts).isdisjoint(source_port.service_contracts):
                raise NodeComputationError(
                    f"Node {instance.key.node_id!r} input {edge.to_port!r} does "
                    f"not accept the service contract produced by node "
                    f"{source.key.node_id!r} output {edge.from_port!r}"
                )
            connections_by_port[edge.to_port] = (
                connections_by_port.get(edge.to_port, 0) + 1
            )
            if not port.variadic and connections_by_port[edge.to_port] > 1:
                raise NodeComputationError(
                    f"Node {instance.key.node_id!r} input {edge.to_port!r} accepts "
                    f"one connection, got {connections_by_port[edge.to_port]}"
                )
            feeds.append(
                ServiceFeed(
                    source=source,
                    from_port=edge.from_port,
                    to_port=edge.to_port,
                )
            )
        return tuple(feeds)

    def boundary_input(
        self,
        instance: ExpandedInstance,
        upstream: Mapping[InstanceKey, Mapping[str, ArtifactOutputValue]],
    ) -> InputSlot:
        """Resolve the single value a Graph input or output passes on.

        A boundary node is no registered operator and declares no contract, so
        its one connection or origin keeps the artifact type it carries: the
        Graph's interface is what typed that port when the document was written.
        """

        incoming = self._incoming(instance, upstream)
        if not incoming:
            raise NodeComputationError(
                f"Boundary node {instance.key.node_id!r} of graph "
                f"{instance.key.graph_id!r} has no incoming connection or origin"
            )
        if len(incoming) > 1:
            raise NodeComputationError(
                f"Boundary node {instance.key.node_id!r} of graph "
                f"{instance.key.graph_id!r} is fed by {len(incoming)} connections; "
                "one Graph interface port carries one value"
            )
        return self._slot(next(iter(incoming)))

    def _build_node(
        self,
        graph_node: GraphNode,
    ) -> tuple[Node[Any, Any, Any], NodeRegistration]:
        operator_id = graph_node.operator_id
        operator_version = graph_node.operator_version
        try:
            registration = self._registry.node_registration(
                operator_id,
                operator_version,
            )
        except UnknownOperatorError as exc:
            raise NodeComputationError(
                f"Node {graph_node.id!r} references unavailable operator "
                f"{operator_id}@{operator_version}"
            ) from exc
        if registration.factory is None:
            try:
                return registration.node_class(), registration
            except TypeError as exc:
                raise NodeComputationError(
                    f"Node {graph_node.id!r} operator {operator_id}@"
                    f"{operator_version} cannot be built without the runtime "
                    "services a plugin context carries"
                ) from exc
        if self._plugin_context is None:
            raise NodeComputationError(
                f"Node {graph_node.id!r} operator {operator_id}@{operator_version} "
                "needs runtime services this runner has no plugin context for"
            )
        return registration.factory(self._plugin_context), registration

    def _incoming(
        self,
        instance: ExpandedInstance,
        upstream: Mapping[InstanceKey, Mapping[str, ArtifactOutputValue]],
    ) -> tuple[_Incoming, ...]:
        """Read every connection's upstream result and every origin's value.

        Connections keep the instance's own order and origins follow, sorted by
        the input slot they fill: that is the order a variadic input receives.
        """

        incoming: list[_Incoming] = []
        for connection in instance.connections:
            edge = connection.edge
            source = _source_outputs(instance, connection.source, upstream)
            value = source.get(edge.from_port)
            if value is None:
                raise NodeComputationError(
                    f"Node {instance.key.node_id!r} input {edge.to_port!r} reads "
                    f"{edge.from_port!r} of {_describe(connection.source)}, whose "
                    "stored result has no such output"
                )
            incoming.append(
                _Incoming(
                    to_port=edge.to_port,
                    to_plug=edge.to_plug,
                    value=value,
                    projection_path=(
                        None if edge.projection is None else tuple(edge.projection.path)
                    ),
                    conversion_path=edge.conversion_path,
                    map_driven=edge.collection_mode == "map",
                    label=_edge_label(edge),
                    source_node_id=edge.from_node,
                    source_port=edge.from_port,
                    target_node_id=edge.to_node,
                )
            )
        for origin in sorted(
            instance.origins,
            key=lambda origin: (origin.to_port, origin.to_plug or ""),
        ):
            incoming.append(
                _Incoming(
                    to_port=origin.to_port,
                    to_plug=origin.to_plug,
                    value=origin.value,
                    projection_path=None,
                    conversion_path=origin.conversion_path,
                    map_driven=origin.collection_mode == "map",
                    label=_origin_label(origin),
                    source_node_id=_ORIGIN_SOURCE_ID,
                    source_port=_ORIGIN_SOURCE_PORT,
                    target_node_id=origin.to_node,
                )
            )
        return tuple(incoming)

    def _slot(self, item: _Incoming) -> InputSlot:
        artifact_type = _value_key(item.value)
        projection: ArtifactFieldProjection | None = None
        if item.projection_path is not None:
            projection = self._projection_for(item, artifact_type)
            if projection is None:
                raise NodeComputationError(
                    f"{item.label} requests undeclared projection "
                    f"{'.'.join(item.projection_path)!r} on {artifact_type.id}@"
                    f"{artifact_type.schema_version}"
                )
            artifact_type = projection.target
        conversion_path, artifact_type = self._conversions_for(item, artifact_type)
        return InputSlot(
            to_port=item.to_port,
            to_plug=item.to_plug,
            value=item.value,
            projection=projection,
            conversion_path=conversion_path,
            map_driven=item.map_driven,
            label=item.label,
            source_node_id=item.source_node_id,
            source_port=item.source_port,
            target_node_id=item.target_node_id,
        )

    def _projection_for(
        self,
        item: _Incoming,
        artifact_type: ArtifactTypeKey,
    ) -> ArtifactFieldProjection | None:
        path = item.projection_path
        if path is None:
            return None
        spec = self._projectable_artifact_types.get(artifact_type)
        if spec is None:
            return None
        return _field_projection_for(spec, path)

    def _conversions_for(
        self,
        item: _Incoming,
        artifact_type: ArtifactTypeKey,
    ) -> tuple[tuple[Conversion[Any, Any], ...], ArtifactTypeKey]:
        if len(item.conversion_path) > MAX_ARTIFACT_CONVERSION_HOPS:
            raise NodeComputationError(
                f"{item.label} conversion path exceeds the maximum of "
                f"{MAX_ARTIFACT_CONVERSION_HOPS} steps"
            )
        seen = {artifact_type}
        conversions: list[Conversion[Any, Any]] = []
        source = artifact_type
        for step_index, step in enumerate(item.conversion_path):
            key = ArtifactConversionKey(id=step.id, version=step.version)
            conversion = CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY.get(key)
            if conversion is None:
                raise NodeComputationError(
                    f"{item.label} requests undeclared conversion {key.id!r}@"
                    f"{key.version} at step {step_index + 1}"
                )
            source_key = conversion.source.spec.key
            target_key = conversion.target.spec.key
            if source_key != source:
                raise NodeComputationError(
                    f"{item.label} applies conversion step {step_index + 1} "
                    f"{conversion.id!r}@{conversion.version}, which expects "
                    f"{source_key.id}@{source_key.schema_version}, to "
                    f"{source.id}@{source.schema_version}"
                )
            if target_key in seen:
                raise NodeComputationError(
                    f"{item.label} conversion path repeats artifact type "
                    f"{target_key.id}@{target_key.schema_version} "
                    f"at step {step_index + 1}"
                )
            conversions.append(conversion)
            seen.add(target_key)
            source = target_key
        return tuple(conversions), source

    def _validate_input_plugs(
        self,
        node: Node[Any, Any, Any],
        graph_node: GraphNode,
        incoming: Sequence[_Incoming],
    ) -> None:
        plugs: dict[str, str] = {}
        for plug in graph_node.input_plugs:
            if plug.id in plugs:
                raise NodeComputationError(
                    "This step has two slots with the same identity. "
                    "Remove the extra slot and add it again."
                )
            target_port = node.input_contract.ports.get(plug.port)
            if target_port is None:
                raise NodeComputationError(
                    "A slot on this step points at an input that no longer "
                    "exists. Remove the step and add it again."
                )
            if not target_port.instance_plugs:
                raise NodeComputationError(
                    "This input cannot take more than one connection."
                )
            plugs[plug.id] = plug.port

        for port_name, port in node.input_contract.ports.items():
            if not port.instance_plugs or not port.required:
                continue
            if any(plug.port == port_name for plug in graph_node.input_plugs):
                continue
            label = (port.title or "").strip() or port_name.replace("_", " ")
            raise NodeComputationError(f"Add at least one slot on “{label}”.")

        connections_by_plug: dict[str, int] = {}
        for item in incoming:
            target_port = node.input_contract.ports.get(item.to_port)
            if target_port is None:
                continue
            if not target_port.instance_plugs:
                if item.to_plug is not None:
                    raise NodeComputationError(
                        "That connection was aimed at a slot this input does not have."
                    )
                continue
            if item.map_driven:
                raise NodeComputationError(
                    "This input takes slots one by one. It cannot take a mapped list."
                )
            if item.to_plug is None:
                raise NodeComputationError("This connection is not aimed at a slot.")
            plug_port = plugs.get(item.to_plug)
            if plug_port is None:
                raise NodeComputationError(
                    "This connection points at a slot that was removed."
                )
            if plug_port != item.to_port:
                raise NodeComputationError(
                    "This connection is aimed at a slot on a different input."
                )
            connections_by_plug[item.to_plug] = (
                connections_by_plug.get(item.to_plug, 0) + 1
            )

        for plug_id, port_name in plugs.items():
            connections = connections_by_plug.get(plug_id, 0)
            if connections == 1:
                continue
            if connections == 0 and node.input_contract.ports[port_name].spare_plugs:
                continue
            raise NodeComputationError(
                "Each slot needs exactly one connection. An empty extra slot, "
                "or two connections into one slot, blocks the run."
            )


def _check_target(
    slot: InputSlot,
    port: InputPortSpec,
    view: ResolvedNodeContractView,
    invocation: NodeInvocation,
) -> None:
    """Say what the target input accepts against what its connection delivers."""

    accepted = port.accepted_types
    if not accepted:
        if isinstance(port.accepts, ArtifactTypeVariable):
            raise NodeComputationError(
                f"Node {slot.target_node_id!r} input {slot.to_port!r} retained "
                f"unresolved artifact type variable {port.accepts.name!r}"
            )
        raise NodeComputationError(
            f"Node {slot.target_node_id!r} input {slot.to_port!r} declares no "
            "accepted artifact types"
        )
    delivered = _value_key(slot.value)
    if slot.conversion_path:
        delivered = slot.conversion_path[-1].target.spec.key
    elif slot.projection is not None:
        delivered = slot.projection.target
    if delivered not in accepted:
        raise NodeComputationError(
            f"{slot.label} delivers {delivered.id}@{delivered.schema_version} to "
            f"node {slot.target_node_id!r} input {slot.to_port!r}, which accepts "
            f"{_artifact_types_label(accepted)}"
        )
    source_shape = _value_shape(slot.value)
    if slot.map_driven and source_shape is not PortShape.MANY:
        raise NodeComputationError(
            f"{slot.label} uses collection mode 'map', which requires a source "
            f"with shape {PortShape.MANY.value!r}; source is {source_shape.value!r}"
        )
    if slot.map_driven and slot.to_port in invocation.map_inputs:
        accepted_shapes: tuple[PortShape, ...] = (
            effective_input_shape(view, invocation, slot.to_port),
        )
    else:
        accepted_shapes = port.accepted_shapes
    if source_shape not in accepted_shapes:
        expected = ", ".join(repr(shape.value) for shape in accepted_shapes)
        raise NodeComputationError(
            f"{slot.label} has incompatible shapes: source is "
            f"{source_shape.value!r}, node {slot.target_node_id!r} input "
            f"{slot.to_port!r} accepts one of {expected}"
        )


def _derive_invocation(
    view: ResolvedNodeContractView,
    node_id: str,
    incoming: Sequence[_Incoming],
) -> NodeInvocation:
    """Decide ONCE or MAP from the collection modes that arrive at this node."""

    drivers: dict[str, _Incoming] = {}
    for item in incoming:
        if not item.map_driven:
            continue
        if item.to_port.strip() == "":
            raise NodeComputationError(
                f"{item.label} cannot drive mapped execution without a target port"
            )
        existing = drivers.get(item.to_port)
        if existing is not None:
            raise NodeComputationError(
                f"Node {node_id!r} has more than one map connection into input "
                f"{item.to_port!r}: {existing.label} and {item.label}; only one "
                "connection per input may drive mapped execution"
            )
        drivers[item.to_port] = item
    if not drivers:
        return NodeInvocation()

    port_order = list(view.input_contract.ports)
    map_inputs = tuple(
        sorted(
            drivers,
            key=lambda name: (
                port_order.index(name) if name in port_order else len(port_order)
            ),
        )
    )
    invocation = NodeInvocation(mode=InvocationMode.MAP, map_inputs=map_inputs)
    try:
        validate_invocation(view, invocation)
    except InvocationError as exc:
        raise NodeComputationError(
            f"Node {node_id!r} cannot run the mapped execution its connections "
            f"ask for: {exc}"
        ) from exc
    return invocation


def _source_outputs(
    instance: ExpandedInstance,
    source: InstanceKey,
    upstream: Mapping[InstanceKey, Mapping[str, ArtifactOutputValue]],
) -> Mapping[str, ArtifactOutputValue]:
    outputs = upstream.get(source)
    if outputs is None:
        raise NodeComputationError(
            f"Node {instance.key.node_id!r} is fed by {_describe(source)}, whose "
            "result this computation was not given a fingerprint for"
        )
    return outputs


def _describe(key: InstanceKey) -> str:
    call_path = "/".join(key.call_path) if key.call_path else "(root)"
    return f"instance node={key.node_id!r} graph={key.graph_id!r} call_path={call_path}"


def _edge_label(edge: GraphEdge) -> str:
    return (
        f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
        f"{edge.to_node!r}.{edge.to_port!r}"
    )


def _origin_label(origin: GraphOrigin) -> str:
    return f"Origin {origin.to_node!r}.{origin.to_port!r}"


def _value_key(value: ArtifactOutputValue) -> ArtifactTypeKey:
    if not isinstance(value, ArtifactRefSequence):
        return value.key()
    return ArtifactTypeKey(value.artifact_type, value.schema_version)


def _value_shape(value: ArtifactOutputValue) -> PortShape:
    if isinstance(value, ArtifactRefSequence):
        return PortShape.MANY
    return PortShape.ONE


def _artifact_types_label(keys: Sequence[ArtifactTypeKey]) -> str:
    return ", ".join(f"{key.id}@{key.schema_version}" for key in keys)


def _field_projection_for(
    artifact_type: ArtifactTypeSpec,
    path: tuple[str, ...],
) -> ArtifactFieldProjection | None:
    for projection in artifact_type.field_projections:
        if projection.path == path:
            return projection
    return None


__all__: Sequence[str] = [
    "BoundNode",
    "InputPortPlan",
    "InputSlot",
    "NodeContractBinder",
    "is_boundary",
]
