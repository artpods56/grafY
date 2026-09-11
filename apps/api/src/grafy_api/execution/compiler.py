from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from grafy_core.artifacts import (
    ArtifactFieldProjection,
    ArtifactRefSequence,
    ArtifactTypeKey,
    ArtifactTypeSpec,
)
from grafy_core.canonical_conversions import CanonicalArtifactConversionMap
from grafy_core.conversions import (
    MAX_ARTIFACT_CONVERSION_HOPS,
    ArtifactConversion,
    ArtifactConversionKey,
    conversion_runtime_types_are_compatible,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.implementation import (
    BuiltinImplementationIdentity,
    ImplementationIdentity,
    PluginImplementationIdentity,
)
from grafy_core.domain.modules import (
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
    GraphModuleReference,
    GraphModuleReferenceError,
)
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginReleaseIdentity,
    PluginReleaseScope,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.domain.saved_graphs import SavedGraphPluginReleasePin
from grafy_core.nodes import (
    ArtifactTypeVariable,
    Node,
    NodeContractResolutionError,
    PortShape,
    ResolvedNodeContracts,
    resolve_node_contracts,
)
from grafy_core.operators.modules import GraphModuleNode
from grafy_core.plugins import (
    NodeRegistration,
    PluginRegistrationError,
    PluginRegistry,
    PluginRuntimeContext,
    UnknownOperatorError,
)
from grafy_core.ports.modules import GraphModuleExecutorPort
from grafy_core.runtime.invocation import (
    InvocationError,
    InvocationMode,
    NodeInvocation,
    effective_input_shape,
    effective_output_shape,
    validate_invocation,
)
from grafy_core.runtime.plugin_invocation import (
    PluginInvoker,
    PluginReleaseNode,
)

from grafy_api.plugins.runtime.admission import (
    ReleaseExecutionAdmission,
    ReleaseExecutionRejection,
    ReleaseExecutionRoute,
)
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.modules import GraphModuleDefinitionError

from grafy_api.execution.requests import (
    PinnedOutputRequest,
    RunEdgeRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.releases import (
    ExactPluginReleaseLookup,
    ReleaseContractKey,
    ResolvedPluginRelease,
    resolve_plugin_release,
)
from grafy_api.execution.models import (
    CompiledEdge,
    CompiledGraph,
    CompiledNode,
    OutputEndpoint,
)


class PluginReleaseLookup(ExactPluginReleaseLookup, Protocol):
    """Exact release contracts and current execution-admission state."""

    async def get_selection(
        self,
        workspace_id: UUID,
        slug: str,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> PluginReleaseSelection | None: ...

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None: ...

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None: ...


@dataclass(frozen=True, slots=True)
class _ReleaseExecutionSnapshot:
    release: InstalledPluginRelease
    selection: PluginReleaseSelection | None
    revocation: PluginReleaseRevocation | None


class GraphCompiler:
    def __init__(
        self,
        *,
        plugin_registry: PluginRegistry,
        plugin_context: PluginRuntimeContext,
        module_library: ModuleLibraryService | None,
        canonical_artifact_conversions: CanonicalArtifactConversionMap,
        plugin_release_lookup: PluginReleaseLookup | None = None,
        plugin_invoker: PluginInvoker | None = None,
        release_admission: ReleaseExecutionAdmission | None = None,
        build_digest: str,
    ) -> None:
        self._plugin_registry = plugin_registry
        self._plugin_context = plugin_context
        self._module_library = module_library
        self._plugin_release_lookup = plugin_release_lookup
        self._plugin_invoker = plugin_invoker
        self._release_admission = release_admission
        self._build_digest = build_digest
        self._reserved_builtin_operator_ids = frozenset(
            registration.node_class.operator_id
            for registration in plugin_registry.nodes
            if registration.plugin_slug != "graph.module"
        )
        self._artifact_types = {
            artifact_type.key for artifact_type in plugin_registry.artifact_types
        }
        self._declared_artifact_contracts = {
            artifact_type.key: PluginArtifactTypeContract.from_spec(artifact_type)
            for artifact_type in (
                *plugin_registry.declared_artifact_types,
                *plugin_registry.artifact_type_dependencies,
            )
        }
        self._projectable_artifact_types = {
            artifact_type.key: artifact_type
            for artifact_type in plugin_registry.artifact_types
            if artifact_type.field_projections
        }
        self._artifact_conversions = dict(canonical_artifact_conversions)
        for key, conversion in self._artifact_conversions.items():
            if key != conversion.key:
                raise ValueError(
                    f"Canonical artifact conversion map key {key.id}@{key.version} "
                    f"does not match declaration {conversion.key.id}@"
                    f"{conversion.key.version}"
                )

    async def compile(
        self,
        request: RunRequest,
        module_executor: GraphModuleExecutorPort,
        *,
        workspace_id: UUID,
        resolved_releases: Mapping[ReleaseContractKey, ResolvedPluginRelease]
        | None = None,
    ) -> CompiledGraph:
        release_contracts = dict(resolved_releases or {})
        ordered_requests = _topological_order(request.nodes, request.edges)
        pinned_outputs = _pinned_outputs_by_endpoint(
            request.nodes,
            request.edges,
            request.pinned_outputs,
        )

        nodes_by_id: dict[str, Node[Any, Any, Any]] = {}
        registrations_by_id: dict[str, NodeRegistration | None] = {}
        releases_by_id: dict[str, PluginReleaseIdentity | None] = {}
        implementations_by_id: dict[str, ImplementationIdentity | None] = {}
        release_snapshots: dict[
            tuple[PluginReleaseScope, str, int],
            _ReleaseExecutionSnapshot,
        ] = {}
        for node_request in ordered_requests:
            (
                node,
                registration,
                release_identity,
                implementation,
            ) = await self._build_node(
                node_request,
                module_executor,
                workspace_id=workspace_id,
                release_snapshots=release_snapshots,
                release_contracts=release_contracts,
            )
            nodes_by_id[node_request.id] = node
            registrations_by_id[node_request.id] = registration
            releases_by_id[node_request.id] = release_identity
            implementations_by_id[node_request.id] = implementation

        artifact_types = set(self._artifact_types)
        artifact_contracts = dict(self._declared_artifact_contracts)
        projectable_artifact_types = dict(self._projectable_artifact_types)
        for snapshot in release_snapshots.values():
            release = snapshot.release
            for contract in (
                *release.release.catalog.artifact_types,
                *release.release.catalog.artifact_type_dependencies,
            ):
                key = ArtifactTypeKey(contract.key.id, contract.key.schema_version)
                existing = artifact_contracts.get(key)
                if existing is not None and existing != contract:
                    raise GraphExecutionError(
                        f"Exact {release.installation.scope.value.title()} Plugin release "
                        f"{release.release.slug!r} revision {release.release.revision} artifact "
                        f"contract {key.id}@{key.schema_version} conflicts with "
                        "another available exact artifact contract"
                    )
                if existing is not None:
                    continue
                artifact_contracts[key] = contract
                artifact_types.add(key)
                if contract.field_projections:
                    projectable_artifact_types[key] = ArtifactTypeSpec(
                        key=key,
                        title=contract.title,
                        field_projections=tuple(
                            ArtifactFieldProjection(
                                path=projection.path,
                                target=ArtifactTypeKey(
                                    projection.target.id,
                                    projection.target.schema_version,
                                ),
                                title=projection.title,
                            )
                            for projection in contract.field_projections
                        ),
                    )

        bindings_by_node: dict[str, dict[str, ArtifactTypeKey]] = {}
        resolved_contracts_by_node: dict[str, ResolvedNodeContracts] = {}
        for node_request in ordered_requests:
            bindings = {
                binding.variable: binding.artifact_type.to_key()
                for binding in node_request.artifact_type_bindings
            }
            node = nodes_by_id[node_request.id]
            try:
                resolved_contracts = resolve_node_contracts(node, bindings)
            except NodeContractResolutionError as exc:
                raise GraphExecutionError(
                    f"Node {node_request.id!r} ({node.operator_id}@"
                    f"{node.operator_version}) has invalid artifact type "
                    f"bindings: {exc}"
                ) from exc
            for variable, artifact_type in bindings.items():
                if artifact_type in artifact_types:
                    continue
                raise GraphExecutionError(
                    f"Node {node_request.id!r} artifact type variable "
                    f"{variable!r} is bound to unavailable artifact type "
                    f"{artifact_type.id}@{artifact_type.schema_version}"
                )
            bindings_by_node[node_request.id] = bindings
            resolved_contracts_by_node[node_request.id] = resolved_contracts

        _validate_input_plugs(nodes_by_id, request.nodes, request.edges)
        invocations_by_id = _derive_invocations(nodes_by_id, request.edges)
        compiled_edges = _compile_edges(
            nodes_by_id=nodes_by_id,
            resolved_contracts_by_node=resolved_contracts_by_node,
            invocations_by_id=invocations_by_id,
            edges=request.edges,
            projectable_artifact_types=projectable_artifact_types,
            artifact_conversions=self._artifact_conversions,
            pinned_outputs=pinned_outputs,
        )

        return CompiledGraph(
            nodes=tuple(
                CompiledNode(
                    request=node_request,
                    node=nodes_by_id[node_request.id],
                    registration=registrations_by_id[node_request.id],
                    resolved_contracts=resolved_contracts_by_node[node_request.id],
                    invocation=invocations_by_id[node_request.id],
                    artifact_type_bindings=bindings_by_node[node_request.id],
                    plugin_release=releases_by_id[node_request.id],
                    implementation=implementations_by_id[node_request.id],
                )
                for node_request in ordered_requests
            ),
            edges=compiled_edges,
            pinned_outputs=pinned_outputs,
        )

    async def _build_node(
        self,
        request: RunNodeRequest,
        module_executor: GraphModuleExecutorPort,
        *,
        workspace_id: UUID,
        release_snapshots: dict[
            tuple[PluginReleaseScope, str, int],
            _ReleaseExecutionSnapshot,
        ],
        release_contracts: dict[ReleaseContractKey, ResolvedPluginRelease],
    ) -> tuple[
        Node[Any, Any, Any],
        NodeRegistration | None,
        PluginReleaseIdentity | None,
        ImplementationIdentity | None,
    ]:
        try:
            module_reference = GraphModuleReference.try_from_operator_identity(
                request.operator_id,
                request.operator_version,
            )
        except GraphModuleReferenceError as exc:
            raise GraphExecutionError(str(exc)) from exc
        is_module_boundary = request.operator_id in {
            MODULE_INPUT_OPERATOR_ID,
            MODULE_OUTPUT_OPERATOR_ID,
        }

        if request.kind == "module":
            return await self._build_module_node(
                request,
                module_executor,
                workspace_id=workspace_id,
                module_reference=module_reference,
                is_module_boundary=is_module_boundary,
            )
        if request.kind == "builtin":
            return self._build_builtin_node(
                request,
                module_reference=module_reference,
                is_module_boundary=is_module_boundary,
            )
        return await self._build_plugin_node(
            request,
            workspace_id=workspace_id,
            release_snapshots=release_snapshots,
            release_contracts=release_contracts,
        )

    async def _build_module_node(
        self,
        request: RunNodeRequest,
        module_executor: GraphModuleExecutorPort,
        *,
        workspace_id: UUID,
        module_reference: GraphModuleReference | None,
        is_module_boundary: bool,
    ) -> tuple[
        Node[Any, Any, Any],
        NodeRegistration | None,
        PluginReleaseIdentity | None,
        ImplementationIdentity | None,
    ]:
        if request.plugin_release is not None:
            raise GraphExecutionError(
                f"Node {request.id!r} is a module and cannot carry a Plugin release pin"
            )
        if module_reference is not None:
            if self._module_library is None:
                raise GraphExecutionError(
                    "Saved graph modules are not configured for this workbench"
                )
            try:
                definition = await self._module_library.resolve_definition(
                    module_reference,
                    workspace_id=workspace_id,
                )
            except NotFoundError as exc:
                raise NotFoundError(
                    "Saved graph module",
                    f"{module_reference.graph_id}@{module_reference.revision}",
                ) from exc
            except GraphModuleDefinitionError as exc:
                raise GraphExecutionError(
                    f"Saved graph {module_reference.graph_id} revision "
                    f"{module_reference.revision} is not a valid module: {exc}"
                ) from exc
            return (
                GraphModuleNode(definition, module_executor),
                None,
                None,
                None,
            )
        if not is_module_boundary:
            raise GraphExecutionError(
                f"Node {request.id!r} ({request.operator_id}@"
                f"{request.operator_version}) is not a module operator"
            )
        try:
            node = self._plugin_registry.build_node(
                request.operator_id,
                request.operator_version,
                self._plugin_context,
            )
            registration = self._plugin_registry.node_registration(
                request.operator_id,
                request.operator_version,
            )
        except UnknownOperatorError as exc:
            raise GraphExecutionError(
                f"Node {request.id!r} references unavailable module boundary "
                f"{request.operator_id}@{request.operator_version}: {exc}"
            ) from exc
        return node, registration, None, None

    def _build_builtin_node(
        self,
        request: RunNodeRequest,
        *,
        module_reference: GraphModuleReference | None,
        is_module_boundary: bool,
    ) -> tuple[
        Node[Any, Any, Any],
        NodeRegistration | None,
        PluginReleaseIdentity | None,
        ImplementationIdentity | None,
    ]:
        if request.plugin_release is not None:
            raise GraphExecutionError(
                f"Node {request.id!r} is a builtin and cannot carry a Plugin "
                "release pin"
            )
        if module_reference is not None or is_module_boundary:
            raise GraphExecutionError(
                f"Node {request.id!r} ({request.operator_id}@"
                f"{request.operator_version}) is a module; use kind=module"
            )
        try:
            node = self._plugin_registry.build_node(
                request.operator_id,
                request.operator_version,
                self._plugin_context,
            )
            registration = self._plugin_registry.node_registration(
                request.operator_id,
                request.operator_version,
            )
        except UnknownOperatorError as exc:
            raise GraphExecutionError(
                f"Unknown builtin operator {request.operator_id}@"
                f"{request.operator_version}"
            ) from exc
        except PluginRegistrationError as exc:
            raise GraphExecutionError(
                f"Could not build builtin operator {request.operator_id}@"
                f"{request.operator_version}"
            ) from exc
        return (
            node,
            registration,
            None,
            BuiltinImplementationIdentity(build_digest=self._build_digest),
        )

    async def _build_plugin_node(
        self,
        request: RunNodeRequest,
        *,
        workspace_id: UUID,
        release_snapshots: dict[
            tuple[PluginReleaseScope, str, int],
            _ReleaseExecutionSnapshot,
        ],
        release_contracts: dict[ReleaseContractKey, ResolvedPluginRelease],
    ) -> tuple[
        Node[Any, Any, Any],
        NodeRegistration | None,
        PluginReleaseIdentity | None,
        ImplementationIdentity | None,
    ]:
        if request.plugin_release is None:
            raise GraphExecutionError(
                f"Node {request.id!r} is a Plugin and must pin one exact "
                "Plugin release with scope, slug, and revision"
            )
        if request.operator_id in self._reserved_builtin_operator_ids:
            raise GraphExecutionError(
                f"Node {request.id!r} pins a published Plugin, but "
                f"{request.operator_id}@{request.operator_version} is a "
                "reserved builtin operator"
            )
        if self._plugin_release_lookup is None or self._release_admission is None:
            raise GraphExecutionError(
                f"Node {request.id!r} pins "
                f"{request.plugin_release.scope.value.title()} Plugin release "
                f"{request.plugin_release.slug!r} revision "
                f"{request.plugin_release.revision}, but exact Plugin release "
                "execution is not configured for this workbench"
            )
        snapshot_key = (
            request.plugin_release.scope,
            request.plugin_release.slug,
            request.plugin_release.revision,
        )
        resolved = await resolve_plugin_release(
            workspace_id,
            request,
            self._plugin_release_lookup,
            release_contracts,
        )
        snapshot = release_snapshots.get(snapshot_key)
        if snapshot is None:
            release = resolved.release
            selection = await self._plugin_release_lookup.get_selection(
                workspace_id,
                release.release.slug,
                scope=release.installation.scope,
            )
            if release.installation.scope is PluginReleaseScope.WORKSPACE:
                revocation = await self._plugin_release_lookup.get_revocation(
                    workspace_id=workspace_id,
                    slug=release.release.slug,
                    revision=release.release.revision,
                )
            else:
                revocation = await self._plugin_release_lookup.get_system_revocation(
                    slug=release.release.slug,
                    revision=release.release.revision,
                )
            snapshot = _ReleaseExecutionSnapshot(
                release=release,
                selection=selection,
                revocation=revocation,
            )
            release_snapshots[snapshot_key] = snapshot
        release = snapshot.release
        contract = resolved.contract_for(request)
        decision = self._release_admission.decide(
            release,
            node_contract=contract,
            selection=snapshot.selection,
            revocation=snapshot.revocation,
        )
        if isinstance(decision, ReleaseExecutionRejection):
            raise GraphExecutionError(
                f"Node {request.id!r} pins Plugin release "
                f"{release.release.slug!r} revision {release.release.revision}, but that "
                f"node is not runnable ({decision.reason}): "
                f"{decision.detail}"
            )
        if decision is not ReleaseExecutionRoute.ISOLATED:
            raise GraphExecutionError(
                f"Node {request.id!r} pins Plugin release "
                f"{release.release.slug!r} revision {release.release.revision}, but published "
                "Plugins execute only in an isolated worker"
            )
        if self._plugin_invoker is None:
            raise GraphExecutionError(
                f"Node {request.id!r} selected isolated Plugin execution, "
                "but its invoker is not configured for this workbench"
            )
        artifact = release.release.runtime_artifact
        image_digest = release.release.runtime_image_digest
        if artifact is None or image_digest is None:
            raise GraphExecutionError(
                f"Node {request.id!r} pins Plugin release "
                f"{release.release.slug!r} revision {release.release.revision}, but that "
                "release has no immutable image digest"
            )
        proxy: PluginReleaseNode[Any, Any, Any] = PluginReleaseNode(
            release,
            contract,
            self._plugin_invoker,
            artifact_type_bindings={
                binding.variable: binding.artifact_type.to_key()
                for binding in request.artifact_type_bindings
            },
        )
        return (
            proxy,
            None,
            proxy.release_identity,
            PluginImplementationIdentity(
                plugin_release_pin=SavedGraphPluginReleasePin(
                    scope=release.installation.scope,
                    slug=release.release.slug,
                    revision=release.release.revision,
                ),
                manifest_digest=artifact.manifest_digest,
                image_digest=image_digest,
            ),
        )


def _topological_order(
    nodes: list[RunNodeRequest],
    edges: list[RunEdgeRequest],
) -> list[RunNodeRequest]:
    by_id = {node.id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise GraphExecutionError("Duplicate node ids in graph")
    for edge in edges:
        if edge.to_node not in by_id:
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} references unknown target "
                f"node {edge.to_node!r}"
            )

    incoming_count = {node.id: 0 for node in nodes}
    # Phase-local adjacency index: group internal edges by source node once so
    # topological traversal touches only each node's outgoing edges instead of
    # rescanning the whole edge list per dequeued node.
    outgoing_by_node: dict[str, list[RunEdgeRequest]] = {}
    for edge in edges:
        if edge.from_node in by_id:
            incoming_count[edge.to_node] += 1
            outgoing_by_node.setdefault(edge.from_node, []).append(edge)

    queue = deque(node for node in nodes if incoming_count[node.id] == 0)
    ordered: list[RunNodeRequest] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        for edge in outgoing_by_node.get(node.id, ()):
            if edge.to_node not in by_id:
                continue
            incoming_count[edge.to_node] -= 1
            if incoming_count[edge.to_node] == 0:
                queue.append(by_id[edge.to_node])

    if len(ordered) != len(nodes):
        raise GraphExecutionError("Graph contains a cycle")
    return ordered


def _pinned_outputs_by_endpoint(
    nodes: list[RunNodeRequest],
    edges: list[RunEdgeRequest],
    pinned_outputs: list[PinnedOutputRequest],
) -> dict[OutputEndpoint, ArtifactOutputValue]:
    node_ids = {node.id for node in nodes}
    by_endpoint: dict[OutputEndpoint, ArtifactOutputValue] = {}
    for pinned_output in pinned_outputs:
        endpoint = (pinned_output.from_node, pinned_output.from_port)
        if endpoint in by_endpoint:
            raise GraphExecutionError(
                f"Duplicate pinned output for {pinned_output.from_node!r}."
                f"{pinned_output.from_port!r}"
            )
        if pinned_output.from_node in node_ids:
            raise GraphExecutionError(
                f"Pinned output {pinned_output.from_node!r}."
                f"{pinned_output.from_port!r} is invalid because source node "
                f"{pinned_output.from_node!r} is also being executed"
            )
        by_endpoint[endpoint] = pinned_output.value

    external_endpoints: set[OutputEndpoint] = set()
    for edge in edges:
        if edge.from_node in node_ids:
            continue
        endpoint = (edge.from_node, edge.from_port)
        external_endpoints.add(endpoint)
        if endpoint not in by_endpoint:
            raise GraphExecutionError(
                f"External edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} requires a pinned output"
            )

    for from_node, from_port in by_endpoint:
        if (from_node, from_port) not in external_endpoints:
            raise GraphExecutionError(
                f"Pinned output {from_node!r}.{from_port!r} is not used by any "
                "incoming edge"
            )
    return by_endpoint


def _validate_input_plugs(
    nodes_by_id: dict[str, Node[Any, Any, Any]],
    node_requests: list[RunNodeRequest],
    edges: list[RunEdgeRequest],
) -> None:
    plugs_by_node: dict[str, dict[str, str]] = {}
    for node_request in node_requests:
        node = nodes_by_id[node_request.id]
        plugs: dict[str, str] = {}
        for plug in node_request.input_plugs:
            if plug.id in plugs:
                raise GraphExecutionError(
                    f"Node {node_request.id!r} has duplicate input plug id {plug.id!r}"
                )
            target_port = node.input_contract.ports.get(plug.port)
            if target_port is None:
                raise GraphExecutionError(
                    f"Node {node_request.id!r} input plug {plug.id!r} references "
                    f"unknown input port {plug.port!r}"
                )
            if not target_port.instance_plugs:
                raise GraphExecutionError(
                    f"Node {node_request.id!r} input port {plug.port!r} does not "
                    "accept instance plugs"
                )
            plugs[plug.id] = plug.port
        plugs_by_node[node_request.id] = plugs

        for port_name, port in node.input_contract.ports.items():
            if not port.instance_plugs or not port.required:
                continue
            if any(plug.port == port_name for plug in node_request.input_plugs):
                continue
            raise GraphExecutionError(
                f"Node {node_request.id!r} ({node.operator_id}@"
                f"{node.operator_version}) required instance-plug input "
                f"{port_name!r} has no submitted plugs"
            )

    incoming_by_plug: Counter[tuple[str, str]] = Counter()
    for edge in edges:
        target_node = nodes_by_id[edge.to_node]
        target_port = target_node.input_contract.ports.get(edge.to_port)
        if target_port is None:
            continue
        if not target_port.instance_plugs:
            if edge.to_plug is not None:
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} declares input plug "
                    f"{edge.to_plug!r}, but the target port does not accept "
                    "instance plugs"
                )
            continue
        if edge.collection_mode == "map":
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} cannot use collection mode "
                "'map' with an instance-plug input"
            )
        if edge.to_plug is None:
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} must target an input plug"
            )
        plug_port = plugs_by_node[edge.to_node].get(edge.to_plug)
        if plug_port is None:
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} targets unknown input plug "
                f"{edge.to_plug!r}"
            )
        if plug_port != edge.to_port:
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} targets input plug "
                f"{edge.to_plug!r}, which belongs to port {plug_port!r}"
            )
        plug_key = (edge.to_node, edge.to_plug)
        incoming_by_plug[plug_key] += 1
        if incoming_by_plug[plug_key] > 1:
            raise GraphExecutionError(
                f"Node {edge.to_node!r} input plug {edge.to_plug!r} requires "
                "exactly one incoming edge"
            )

    for node_id, plugs in plugs_by_node.items():
        for plug_id in plugs:
            if incoming_by_plug[(node_id, plug_id)] == 1:
                continue
            raise GraphExecutionError(
                f"Node {node_id!r} input plug {plug_id!r} requires exactly one "
                "incoming edge"
            )


def _artifact_type_keys_label(keys: Sequence[ArtifactTypeKey]) -> str:
    return ", ".join(f"{key.id}@{key.schema_version}" for key in keys)


def _compile_edges(
    *,
    nodes_by_id: dict[str, Node[Any, Any, Any]],
    resolved_contracts_by_node: dict[str, ResolvedNodeContracts],
    invocations_by_id: dict[str, NodeInvocation],
    edges: list[RunEdgeRequest],
    projectable_artifact_types: dict[ArtifactTypeKey, ArtifactTypeSpec],
    artifact_conversions: dict[
        ArtifactConversionKey,
        ArtifactConversion[Any, Any],
    ],
    pinned_outputs: dict[OutputEndpoint, ArtifactOutputValue],
) -> tuple[CompiledEdge, ...]:
    incoming_counts: dict[tuple[str, str], int] = {}
    compiled_edges: list[CompiledEdge] = []
    for edge in edges:
        target_node = nodes_by_id[edge.to_node]
        target_port = resolved_contracts_by_node[edge.to_node].input_contract.ports.get(
            edge.to_port
        )
        if target_port is None:
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} references unknown input "
                f"port {edge.to_port!r} on node {edge.to_node!r}"
            )
        target_keys = target_port.accepted_types
        if not target_keys:
            if isinstance(target_port.accepts, ArtifactTypeVariable):
                raise GraphExecutionError(
                    f"Node {edge.to_node!r} input {edge.to_port!r} retained "
                    f"unresolved artifact type variable "
                    f"{target_port.accepts.name!r}"
                )
            raise GraphExecutionError(
                f"Node {edge.to_node!r} input {edge.to_port!r} declares no "
                "accepted artifact types"
            )
        target_label = _artifact_type_keys_label(target_keys)

        source_node = nodes_by_id.get(edge.from_node)
        if source_node is None:
            pinned_value = pinned_outputs[(edge.from_node, edge.from_port)]
            source_shape = (
                PortShape.MANY
                if isinstance(pinned_value, ArtifactRefSequence)
                else PortShape.ONE
            )
            source_key = _value_key(pinned_value)
        else:
            source_port = resolved_contracts_by_node[
                edge.from_node
            ].output_contract.ports.get(edge.from_port)
            if source_port is None:
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} references unknown output "
                    f"port {edge.from_port!r} on node {edge.from_node!r}"
                )
            source_shape = effective_output_shape(
                source_node,
                invocations_by_id[edge.from_node],
                edge.from_port,
            )
            source_key = source_port.produces
            if not isinstance(source_key, ArtifactTypeKey):
                raise GraphExecutionError(
                    f"Node {edge.from_node!r} output {edge.from_port!r} retained "
                    f"unresolved artifact type variable {source_key.name!r}"
                )
        if edge.collection_mode == "map" and source_shape is not PortShape.MANY:
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} uses collection mode 'map', "
                f"which requires a source with shape {PortShape.MANY.value!r}; "
                f"source is {source_shape.value!r}"
            )

        incoming_key = (edge.to_node, edge.to_port)
        incoming_counts[incoming_key] = incoming_counts.get(incoming_key, 0) + 1
        if not target_port.variadic and incoming_counts[incoming_key] > 1:
            raise GraphExecutionError(
                f"Node {edge.to_node!r} input {edge.to_port!r} accepts one "
                f"connection, got {incoming_counts[incoming_key]}"
            )

        resolved_projection: ArtifactFieldProjection | None = None
        effective_source_key = source_key
        if edge.projection is not None:
            requested_path = tuple(edge.projection.path)
            resolved_projection = _field_projection_for(
                projectable_artifact_types,
                effective_source_key,
                requested_path,
            )
            if resolved_projection is None:
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} requests undeclared "
                    f"projection {'.'.join(requested_path)!r} on "
                    f"{effective_source_key.id}@"
                    f"{effective_source_key.schema_version}"
                )
            effective_source_key = resolved_projection.target

        if len(edge.conversion_path) > MAX_ARTIFACT_CONVERSION_HOPS:
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} conversion path exceeds "
                f"the maximum of {MAX_ARTIFACT_CONVERSION_HOPS} steps"
            )
        seen_artifact_keys = {effective_source_key}
        resolved_conversions: list[ArtifactConversion[Any, Any]] = []
        for step_index, requested_conversion in enumerate(edge.conversion_path):
            conversion_key = ArtifactConversionKey(
                id=requested_conversion.id,
                version=requested_conversion.version,
            )
            conversion = artifact_conversions.get(conversion_key)
            if conversion is None:
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} requests undeclared "
                    f"conversion {conversion_key.id!r}@{conversion_key.version} "
                    f"at step {step_index + 1}"
                )
            if conversion.source != effective_source_key:
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} applies conversion step "
                    f"{step_index + 1} "
                    f"{conversion.key.id!r}@{conversion.key.version}, which expects "
                    f"{conversion.source.id}@{conversion.source.schema_version}, "
                    f"to {effective_source_key.id}@"
                    f"{effective_source_key.schema_version}"
                )
            if resolved_conversions and not conversion_runtime_types_are_compatible(
                resolved_conversions[-1].target_type,
                conversion.source_type,
            ):
                previous = resolved_conversions[-1]
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} conversion steps "
                    f"{step_index} and {step_index + 1} have incompatible runtime "
                    f"types: {previous.target_type} does not match "
                    f"{conversion.source_type}"
                )
            if conversion.target in seen_artifact_keys:
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} conversion path repeats "
                    f"artifact type {conversion.target.id}@"
                    f"{conversion.target.schema_version} at step {step_index + 1}"
                )
            resolved_conversions.append(conversion)
            effective_source_key = conversion.target
            seen_artifact_keys.add(effective_source_key)

        if effective_source_key not in target_keys:
            if resolved_conversions:
                conversion_path = " -> ".join(
                    f"{conversion.key.id}@{conversion.key.version}"
                    for conversion in resolved_conversions
                )
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} converts through "
                    f"{conversion_path} as "
                    f"{effective_source_key.id}@"
                    f"{effective_source_key.schema_version}, but target expects "
                    f"{target_label}"
                )
            if edge.projection is not None:
                raise GraphExecutionError(
                    f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                    f"{edge.to_node!r}.{edge.to_port!r} projects "
                    f"{'.'.join(edge.projection.path)!r} as "
                    f"{effective_source_key.id}@"
                    f"{effective_source_key.schema_version}, but target expects "
                    f"{target_label}"
                )
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} cannot connect "
                f"{effective_source_key.id}@"
                f"{effective_source_key.schema_version} to "
                f"{target_label} "
                "without a declared field projection or conversion"
            )

        invocation = invocations_by_id[edge.to_node]
        if (
            invocation.mode is InvocationMode.MAP
            and invocation.map_input == edge.to_port
        ):
            accepted_shapes = (
                effective_input_shape(
                    target_node,
                    invocation,
                    edge.to_port,
                ),
            )
        else:
            accepted_shapes = target_port.accepted_shapes
        if source_shape not in accepted_shapes:
            expected_shapes = ", ".join(repr(shape.value) for shape in accepted_shapes)
            if len(accepted_shapes) == 1:
                target_shapes = f"expects {expected_shapes}"
            else:
                target_shapes = f"accepts one of {expected_shapes}"
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} has incompatible shapes: "
                f"source is {source_shape.value!r}, target {target_shapes}"
            )

        compiled_edges.append(
            CompiledEdge(
                request=edge,
                projection=resolved_projection,
                conversion_path=tuple(resolved_conversions),
            )
        )

    for node_id, resolved_contracts in resolved_contracts_by_node.items():
        node = nodes_by_id[node_id]
        for port_name, port in resolved_contracts.input_contract.ports.items():
            if not port.required:
                continue
            if incoming_counts.get((node_id, port_name), 0) > 0:
                continue
            raise GraphExecutionError(
                f"Node {node_id!r} ({node.operator_id}@"
                f"{node.operator_version}) required input {port_name!r} has no "
                "incoming edge"
            )

    return tuple(compiled_edges)


def _derive_invocations(
    nodes_by_id: dict[str, Node[Any, Any, Any]],
    edges: list[RunEdgeRequest],
) -> dict[str, NodeInvocation]:
    map_edges_by_target: dict[str, RunEdgeRequest] = {}
    for edge in edges:
        if edge.collection_mode != "map":
            continue
        if edge.to_port.strip() == "":
            raise GraphExecutionError(
                f"Edge {edge.from_node!r}.{edge.from_port!r} -> "
                f"{edge.to_node!r}.{edge.to_port!r} cannot drive mapped "
                "execution without a target port"
            )
        existing = map_edges_by_target.get(edge.to_node)
        if existing is not None:
            raise GraphExecutionError(
                f"Node {edge.to_node!r} has more than one map edge: "
                f"{existing.from_node!r}.{existing.from_port!r} -> "
                f"{existing.to_port!r} and {edge.from_node!r}.{edge.from_port!r} "
                f"-> {edge.to_port!r}; exactly one edge may drive mapped "
                "execution"
            )
        map_edges_by_target[edge.to_node] = edge

    invocations: dict[str, NodeInvocation] = {}
    for node_id, node in nodes_by_id.items():
        map_edge = map_edges_by_target.get(node_id)
        if map_edge is None:
            invocations[node_id] = NodeInvocation()
            continue

        invocation = NodeInvocation(
            mode=InvocationMode.MAP,
            map_input=map_edge.to_port,
        )
        try:
            validate_invocation(node, invocation)
        except InvocationError as exc:
            raise GraphExecutionError(
                f"Edge {map_edge.from_node!r}.{map_edge.from_port!r} -> "
                f"{map_edge.to_node!r}.{map_edge.to_port!r} cannot drive "
                f"mapped execution: {exc}"
            ) from exc
        invocations[node_id] = invocation
    return invocations


def _field_projection_for(
    projectable_artifact_types: dict[ArtifactTypeKey, ArtifactTypeSpec],
    artifact_type: ArtifactTypeKey,
    path: tuple[str, ...],
) -> ArtifactFieldProjection | None:
    artifact_spec = projectable_artifact_types.get(artifact_type)
    if artifact_spec is None:
        return None
    for projection in artifact_spec.field_projections:
        if projection.path == path:
            return projection
    return None


def _value_key(value: ArtifactOutputValue) -> ArtifactTypeKey:
    if not isinstance(value, ArtifactRefSequence):
        return value.key()
    return ArtifactTypeKey(
        value.artifact_type,
        value.schema_version,
    )


__all__ = ["GraphCompiler", "PluginReleaseLookup"]
