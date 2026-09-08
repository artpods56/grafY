"""Saved-revision and secret-binding preflight for graph runs."""

from collections import Counter
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.node_secrets import (
    InvalidNodeSecretDependenciesError,
    JsonValue,
    canonical_node_secret_dependencies,
)
from grafy_core.domain.modules import (
    GRAPH_MODULE_OPERATOR_PREFIX,
    MODULE_BOUNDARY_PORT,
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
    ModuleInputConfig,
)
from grafy_core.domain.saved_graphs import SavedGraph, SavedGraphRevision
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginNodeContract,
    PluginReleaseScope,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import PluginRegistry

from grafy_api.plugins.runtime.network_policy import (
    NetworkPolicy,
    resolve_http_egress_authority,
)

from grafy_api.execution.requests import (
    RunEdgeRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.execution.errors import GraphExecutionError


@dataclass(frozen=True, slots=True)
class GraphRunContext:
    secret_node_ids: frozenset[str]


class PreflightPluginReleaseLookup(Protocol):
    """Exact release-contract lookup needed for secret preflight."""

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None: ...


class GraphRunPreflight:
    """Authorize a submitted fragment against its saved graph contexts."""

    def __init__(
        self,
        *,
        plugin_registry: PluginRegistry,
        saved_graphs: SavedGraphService | None,
        plugin_release_lookup: PreflightPluginReleaseLookup | None = None,
        network_policy: NetworkPolicy | None = None,
    ) -> None:
        self._registrations = {
            registration.key: registration for registration in plugin_registry.nodes
        }
        self._plugin_registry = plugin_registry
        self._saved_graphs = saved_graphs
        self._plugin_release_lookup = plugin_release_lookup
        self._network_policy = network_policy or NetworkPolicy()

    async def validate(
        self,
        workspace_id: UUID,
        request: RunRequest,
    ) -> GraphRunContext:
        submitted_secret_nodes: set[str] = set()
        release_contracts: dict[
            tuple[PluginReleaseScope, str, int],
            InstalledPluginRelease | None,
        ] = {}
        release_contracts_by_node: dict[str, PluginNodeContract] = {}
        for node in request.nodes:
            registration = self._registrations.get(
                (node.operator_id, node.operator_version)
            )
            pin = node.plugin_release
            if pin is None:
                if registration is not None and registration.secret_inputs:
                    submitted_secret_nodes.add(node.id)
                continue
            if node.operator_id.startswith(GRAPH_MODULE_OPERATOR_PREFIX):
                raise GraphExecutionError(
                    f"Node {node.id!r} pins Plugin release {pin.slug!r} revision "
                    f"{pin.revision}, but operator {node.operator_id}@"
                    f"{node.operator_version} is a graph module; modules cannot "
                    "carry a Plugin release pin"
                )
            if node.operator_id in {
                MODULE_INPUT_OPERATOR_ID,
                MODULE_OUTPUT_OPERATOR_ID,
            }:
                raise GraphExecutionError(
                    f"Node {node.id!r} pins Plugin release {pin.slug!r} revision "
                    f"{pin.revision}, but operator {node.operator_id}@"
                    f"{node.operator_version} is a module boundary; module "
                    "boundaries cannot carry a Plugin release pin"
                )
            if self._plugin_release_lookup is None:
                raise GraphExecutionError(
                    f"Node {node.id!r} pins {pin.scope.value.title()} Plugin "
                    f"release {pin.slug!r} revision {pin.revision}, but exact "
                    "Plugin release preflight is not configured for this workbench"
                )
            release_key = (pin.scope, pin.slug, pin.revision)
            if release_key not in release_contracts:
                release_contracts[
                    release_key
                ] = await self._plugin_release_lookup.get_by_revision(
                    workspace_id,
                    pin.slug,
                    pin.revision,
                    scope=pin.scope,
                )
            release = release_contracts[release_key]
            if release is None:
                if pin.scope is PluginReleaseScope.WORKSPACE:
                    owner_context = "in this workspace"
                else:
                    owner_context = "in the System Plugin catalog"
                raise GraphExecutionError(
                    f"Node {node.id!r} pins {pin.scope.value.title()} Plugin "
                    f"release {pin.slug!r} revision {pin.revision}, which does "
                    f"not exist {owner_context}"
                )
            contract = next(
                (
                    declared
                    for declared in release.catalog.nodes
                    if declared.operator_id == node.operator_id
                    and declared.operator_version == node.operator_version
                ),
                None,
            )
            if contract is None:
                raise GraphExecutionError(
                    f"Node {node.id!r} pins {pin.scope.value.title()} Plugin "
                    f"release {pin.slug!r} revision {pin.revision}, which does "
                    f"not declare operator {node.operator_id}@"
                    f"{node.operator_version}"
                )
            release_contracts_by_node[node.id] = contract
            self._validate_network_preflight(node, release, contract)
            if contract.secret_inputs:
                submitted_secret_nodes.add(node.id)
        if submitted_secret_nodes and request.secret_graph_id is None:
            rendered_node_ids = ", ".join(
                repr(node_id) for node_id in sorted(submitted_secret_nodes)
            )
            raise GraphExecutionError(
                "A saved secret graph context is required to run secret-bearing "
                f"nodes: {rendered_node_ids}"
            )

        saved_graph_context: SavedGraphRevision | None = None
        if request.graph_id is not None and request.graph_revision is not None:
            saved_graph_context = await self._saved_graph_revision(
                workspace_id,
                request.graph_id,
                request.graph_revision,
            )
            _validate_saved_graph_fragment(
                saved_graph_context,
                request.nodes,
                request.edges,
                {
                    (pinned_output.from_node, pinned_output.from_port)
                    for pinned_output in request.pinned_outputs
                },
            )

        secret_node_ids: set[str] = set()
        if (
            request.secret_graph_id is not None
            and request.secret_graph_revision is not None
        ):
            secret_graph = saved_graph_context
            if secret_graph is None:
                secret_graph = await self._saved_graph_revision(
                    workspace_id,
                    request.secret_graph_id,
                    request.secret_graph_revision,
                )
            secret_node_ids = _validate_secret_graph_bindings(
                secret_graph,
                request.nodes,
                self._plugin_registry,
                release_contracts_by_node,
            )
        return GraphRunContext(secret_node_ids=frozenset(secret_node_ids))

    def _validate_network_preflight(
        self,
        node: RunNodeRequest,
        release: InstalledPluginRelease,
        contract: PluginNodeContract,
    ) -> None:
        """Deny invocations whose effective network authority cannot be met."""

        if (
            PluginRuntimeCapability.NETWORK_EGRESS
            not in set(contract.required_capabilities)
        ):
            return
        resolution = resolve_http_egress_authority(
            self._network_policy,
            scope=release.scope,
            workspace_id=release.workspace_id,
            slug=release.slug,
            revision=release.revision,
            contract=contract,
            config=node.config,
        )
        if resolution.allowed:
            return
        profile_name = (
            "none"
            if resolution.profile is None
            else resolution.profile.name
        )
        raise GraphExecutionError(
            f"Node {node.id!r} ({contract.operator_id}@"
            f"{contract.operator_version}) cannot run under network profile "
            f"{profile_name!r}: {resolution.reason.value}: {resolution.detail}"
        )

    async def _saved_graph_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
    ) -> SavedGraphRevision:
        if self._saved_graphs is None:
            raise GraphExecutionError(
                "Saved graph context is not configured for this workbench"
            )
        return await self._saved_graphs.get_revision(
            workspace_id,
            graph_id,
            graph_revision,
        )


def _validate_saved_graph_fragment(
    graph: SavedGraph | SavedGraphRevision,
    nodes: list[RunNodeRequest],
    edges: list[RunEdgeRequest],
    pinned_output_endpoints: set[tuple[str, str]],
) -> None:
    saved_nodes = {node.id: node for node in graph.document.nodes}
    executed_node_ids = {node.id for node in nodes}
    optional_unpinned_boundary_endpoints: set[tuple[str, str]] = set()
    relevant_boundary_node_ids = {
        edge.from_node
        for edge in graph.document.edges
        if edge.enabled
        and edge.to_node in executed_node_ids
        and edge.from_port == MODULE_BOUNDARY_PORT
        and saved_nodes[edge.from_node].operator_id == MODULE_INPUT_OPERATOR_ID
    }
    for boundary_node_id in relevant_boundary_node_ids:
        boundary_node = saved_nodes[boundary_node_id]
        try:
            boundary_config = ModuleInputConfig.model_validate(
                boundary_node.config_dict()
            )
        except ValueError as exc:
            raise GraphExecutionError(
                f"Saved graph {graph.id} revision {graph.revision} module input "
                f"boundary {boundary_node_id!r} has invalid configuration"
            ) from exc
        endpoint = (boundary_node_id, MODULE_BOUNDARY_PORT)
        if not boundary_config.required and endpoint not in pinned_output_endpoints:
            optional_unpinned_boundary_endpoints.add(endpoint)

    expected_saved_incoming_edges = tuple(
        edge
        for edge in graph.document.edges
        if edge.enabled
        and edge.to_node in executed_node_ids
        and (edge.from_node, edge.from_port) not in optional_unpinned_boundary_endpoints
    )
    active_saved_plug_ids_by_node: dict[str, set[str]] = {}
    for edge in expected_saved_incoming_edges:
        if edge.to_plug is None:
            continue
        active_saved_plug_ids_by_node.setdefault(edge.to_node, set()).add(edge.to_plug)

    for node in nodes:
        saved_node = saved_nodes.get(node.id)
        if saved_node is None:
            raise GraphExecutionError(
                f"Run node {node.id!r} does not belong to saved graph {graph.id} "
                f"revision {graph.revision}"
            )
        active_saved_plug_ids = active_saved_plug_ids_by_node.get(node.id, set())
        submitted_release = (
            None
            if node.plugin_release is None
            else (
                node.plugin_release.scope,
                node.plugin_release.slug,
                node.plugin_release.revision,
            )
        )
        saved_release = (
            None
            if saved_node.plugin_release_pin is None
            else (
                saved_node.plugin_release_pin.scope,
                saved_node.plugin_release_pin.slug,
                saved_node.plugin_release_pin.revision,
            )
        )
        if (
            node.operator_id != saved_node.operator_id
            or node.operator_version != saved_node.operator_version
            or node.config != saved_node.config_dict()
            or tuple((plug.id, plug.port) for plug in node.input_plugs)
            != tuple(
                (plug.id, plug.port)
                for plug in saved_node.input_plugs
                if plug.id in active_saved_plug_ids
            )
            or {
                binding.variable: binding.artifact_type.to_key()
                for binding in node.artifact_type_bindings
            }
            != {
                binding.variable: binding.artifact_type
                for binding in saved_node.artifact_type_bindings
            }
            or submitted_release != saved_release
        ):
            raise GraphExecutionError(
                f"Run node {node.id!r} does not match saved graph {graph.id} "
                f"revision {graph.revision}"
            )

    saved_incoming_edges = Counter(
        (
            edge.from_node,
            edge.from_port,
            edge.to_node,
            edge.to_port,
            edge.to_plug,
            edge.collection_mode,
            tuple(edge.projection.path) if edge.projection is not None else None,
            tuple(
                (conversion.id, conversion.version)
                for conversion in edge.conversion_path
            ),
        )
        for edge in expected_saved_incoming_edges
    )
    submitted_edges = Counter(
        (
            edge.from_node,
            edge.from_port,
            edge.to_node,
            edge.to_port,
            edge.to_plug,
            edge.collection_mode,
            tuple(edge.projection.path) if edge.projection is not None else None,
            tuple(
                (conversion.id, conversion.version)
                for conversion in edge.conversion_path
            ),
        )
        for edge in edges
    )
    if submitted_edges != saved_incoming_edges:
        missing_count = sum((saved_incoming_edges - submitted_edges).values())
        unexpected_count = sum((submitted_edges - saved_incoming_edges).values())
        raise GraphExecutionError(
            "Run edges do not match the saved incoming edges for the executed "
            f"nodes in graph {graph.id} revision {graph.revision}: "
            f"{missing_count} missing and {unexpected_count} unexpected or duplicated"
        )


def _validate_secret_graph_bindings(
    graph: SavedGraph | SavedGraphRevision,
    nodes: list[RunNodeRequest],
    plugin_registry: PluginRegistry,
    release_contracts_by_node: dict[str, PluginNodeContract],
) -> set[str]:
    registrations = {
        registration.key: registration for registration in plugin_registry.nodes
    }
    saved_nodes = {node.id: node for node in graph.document.nodes}
    validated_node_ids: set[str] = set()

    for node in nodes:
        registration = registrations.get((node.operator_id, node.operator_version))
        release_contract = release_contracts_by_node.get(node.id)
        if release_contract is not None and release_contract.secret_inputs:
            secret_inputs = release_contract.secret_inputs
        elif registration is not None and registration.secret_inputs:
            secret_inputs = registration.secret_inputs
        else:
            continue
        saved_node = saved_nodes.get(node.id)
        if saved_node is None:
            raise GraphExecutionError(
                f"Secret-bearing run node {node.id!r} does not belong to saved "
                f"graph {graph.id} revision {graph.revision}"
            )
        if (
            saved_node.operator_id != node.operator_id
            or saved_node.operator_version != node.operator_version
        ):
            raise GraphExecutionError(
                f"Secret-bearing run node {node.id!r} does not match the saved "
                f"operator in graph {graph.id} revision {graph.revision}"
            )

        if release_contract is None and registration is not None:
            config_model = registration.node_class.config_contract.model
            try:
                submitted_config = config_model.model_validate(node.config).model_dump(
                    mode="json"
                )
                saved_config = config_model.model_validate(
                    saved_node.config_dict()
                ).model_dump(mode="json")
            except ValueError as exc:
                raise GraphExecutionError(
                    f"Secret-bearing run node {node.id!r} has invalid configuration"
                ) from exc
        else:
            submitted_config = node.config
            saved_config = saved_node.config_dict()

        for declaration in secret_inputs:
            try:
                submitted_dependencies = {
                    dependency: cast(JsonValue, submitted_config[dependency])
                    for dependency in declaration.config_dependencies
                }
                saved_dependencies = {
                    dependency: cast(JsonValue, saved_config[dependency])
                    for dependency in declaration.config_dependencies
                }
                dependencies_match = canonical_node_secret_dependencies(
                    submitted_dependencies
                ) == canonical_node_secret_dependencies(saved_dependencies)
            except (InvalidNodeSecretDependenciesError, KeyError) as exc:
                raise GraphExecutionError(
                    f"Secret-bearing run node {node.id!r} has invalid secret "
                    "configuration dependencies"
                ) from exc
            if not dependencies_match:
                raise GraphExecutionError(
                    f"Secret-bearing run node {node.id!r} does not match the "
                    f"saved configuration required by secret input "
                    f"{declaration.name!r}"
                )
        validated_node_ids.add(node.id)

    return validated_node_ids


__all__ = ["GraphRunContext", "GraphRunPreflight"]
