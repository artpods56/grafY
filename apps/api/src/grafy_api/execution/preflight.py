"""Saved-revision and secret-binding preflight for graph runs."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, cast
from uuid import UUID

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.node_secrets import (
    InvalidNodeSecretDependenciesError,
    JsonValue,
    canonical_node_secret_dependencies,
)
from grafy_core.domain.modules import (
    MODULE_BOUNDARY_PORT,
    MODULE_INPUT_OPERATOR_ID,
    ModuleInputConfig,
)
from grafy_core.domain.saved_graphs import (
    SavedGraph,
    SavedGraphEdge,
    SavedGraphNode,
    SavedGraphOrigin,
    SavedGraphRevision,
)
from grafy_core.plugins import NodeRegistration, PluginRegistry

from grafy_api.execution.errors import (
    GraphExecutionError,
    SavedGraphMismatchError,
    SecretBindingError,
    SecretContextRequiredError,
)
from grafy_api.execution.requests import (
    RunEdgeRequest,
    RunNodeRequest,
    RunOriginRequest,
    RunRequest,
)


@dataclass(frozen=True, slots=True)
class GraphRunContext:
    secret_node_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _NodeMismatch:
    """The first submitted node whose saved counterpart is absent or different."""

    node_id: str
    kind: Literal["absent", "mismatch"]


@dataclass(frozen=True, slots=True)
class _MultisetMismatch:
    """How a submitted multiset of edges or origins differs from the saved one."""

    missing_count: int
    unexpected_count: int


@dataclass(frozen=True, slots=True)
class _SecretMismatch:
    """Why a secret-bearing submission may not spend its node's secrets."""

    node_id: str
    kind: Literal["absent", "operator", "configuration", "dependencies", "input"]
    secret_input: str | None = None
    cause: Exception | None = None


@dataclass(slots=True)
class PreflightRun:
    """What one `validate` call has been told and what it has already loaded.

    Checks are stateless and shared between calls, so everything that belongs to a
    single submission lives here: the request, the registrations it resolves
    against, the node ids found to bear secrets, and the saved revisions loaded so
    far. The revision cache is what lets the fragment check and the secret-binding
    check read one document per revision rather than one each.
    """

    workspace_id: UUID
    request: RunRequest
    registrations: dict[tuple[str, int], NodeRegistration]
    saved_graphs: SavedGraphService | None
    secret_node_ids: set[str] = field(default_factory=set)
    _revisions: dict[tuple[UUID, int], SavedGraphRevision] = field(default_factory=dict)

    def secret_registration(self, node: RunNodeRequest) -> NodeRegistration | None:
        """The registration of a submitted node, when its operator bears secrets."""

        registration = self.registrations.get((node.operator_id, node.operator_version))
        if registration is None or not registration.secret_inputs:
            return None
        return registration

    async def revision(self, graph_id: UUID, graph_revision: int) -> SavedGraphRevision:
        """Load one saved revision, or explain that this workbench saves nothing."""

        key = (graph_id, graph_revision)
        if key not in self._revisions:
            if self.saved_graphs is None:
                raise GraphExecutionError(
                    "Saved graph context is not configured for this workbench"
                )
            self._revisions[key] = await self.saved_graphs.get_revision(
                self.workspace_id,
                graph_id,
                graph_revision,
            )
        return self._revisions[key]


class PreflightCheck:
    """One requirement a submitted run must satisfy. A check holds no state.

    `assert_ready` decides from the submission alone whether the run can be checked
    at all. `validate` may load saved revisions. :class:`GraphRunPreflight` gives
    every check its `assert_ready` turn before any check loads anything, so a run
    that is missing a whole context fails without paying for a lookup of it.
    """

    async def assert_ready(self, run: PreflightRun) -> None:
        return

    async def validate(self, run: PreflightRun) -> None:
        return


class SecretContextCheck(PreflightCheck):
    """A secret-bearing node needs the saved graph whose secrets it belongs to.

    The node's secrets are bound to the saved configuration it was created with, so
    running it without saying which saved graph supplies them cannot be answered
    from the submission alone, let alone from a revision lookup.
    """

    async def assert_ready(self, run: PreflightRun) -> None:
        if run.request.secret_graph_id is not None:
            return
        node_ids = sorted(
            node.id for node in run.request.nodes if run.secret_registration(node)
        )
        if not node_ids:
            return
        rendered_node_ids = ", ".join(repr(node_id) for node_id in node_ids)
        raise SecretContextRequiredError(
            "A saved secret graph context is required to run secret-bearing "
            f"nodes: {rendered_node_ids}",
            node_ids=tuple(node_ids),
        )


class SavedFragmentCheck(PreflightCheck):
    """The submitted fragment is the saved revision it names, or it is not run.

    A run executes what the caller submits, so a submitted node, edge or origin that
    the saved revision does not contain would run work nobody saved. The comparison
    is over the whole fragment — nodes, incoming edges, and origins bound to
    artifact values — because each is a separate way to submit more than was saved.
    """

    async def validate(self, run: PreflightRun) -> None:
        request = run.request
        if request.graph_id is None or request.graph_revision is None:
            return
        graph = await run.revision(request.graph_id, request.graph_revision)
        executed_node_ids = {node.id for node in request.nodes}
        expected_edges = _expected_incoming_edges(
            graph, executed_node_ids, _pinned_endpoints(request)
        )
        node_mismatch = _first_node_mismatch(
            graph,
            request.nodes,
            _active_plug_ids_by_node(graph, expected_edges, executed_node_ids),
        )
        if node_mismatch is not None:
            raise self._node_error(graph, node_mismatch)
        edge_mismatch = _edge_mismatch(expected_edges, request.edges)
        if edge_mismatch is not None:
            raise self._multiset_error(
                "Run edges do not match the saved incoming edges for the executed "
                "nodes in graph",
                graph,
                edge_mismatch,
            )
        origin_mismatch = _origin_mismatch(
            graph.document.origins, executed_node_ids, request.origins
        )
        if origin_mismatch is not None:
            raise self._multiset_error(
                "Run origins do not match the saved origins for the executed "
                "nodes in graph",
                graph,
                origin_mismatch,
            )

    @staticmethod
    def _node_error(
        graph: SavedGraph | SavedGraphRevision,
        mismatch: _NodeMismatch,
    ) -> SavedGraphMismatchError:
        if mismatch.kind == "absent":
            message = (
                f"Run node {mismatch.node_id!r} does not belong to saved graph "
                f"{graph.id} revision {graph.revision}"
            )
        else:
            message = (
                f"Run node {mismatch.node_id!r} does not match saved graph "
                f"{graph.id} revision {graph.revision}"
            )
        return SavedGraphMismatchError(
            message,
            graph_id=graph.id,
            revision=graph.revision,
            node_id=mismatch.node_id,
        )

    @staticmethod
    def _multiset_error(
        description: str,
        graph: SavedGraph | SavedGraphRevision,
        mismatch: _MultisetMismatch,
    ) -> SavedGraphMismatchError:
        return SavedGraphMismatchError(
            f"{description} {graph.id} revision {graph.revision}: "
            f"{mismatch.missing_count} missing and "
            f"{mismatch.unexpected_count} unexpected or duplicated",
            graph_id=graph.id,
            revision=graph.revision,
            missing_count=mismatch.missing_count,
            unexpected_count=mismatch.unexpected_count,
        )


class SecretBindingCheck(PreflightCheck):
    """A secret-bearing node may name secrets only its saved configuration earned.

    Stored node secrets are sealed against the values of the configuration they
    were declared for, so a run that keeps the node id while rewriting the
    dependency those secrets are keyed on would ask the vault for a credential
    under false pretences. The saved graph is re-read and the dependencies
    compared, and only nodes that pass are reported as secret-bearing.
    """

    async def validate(self, run: PreflightRun) -> None:
        request = run.request
        if request.secret_graph_id is None or request.secret_graph_revision is None:
            return
        graph = await run.revision(
            request.secret_graph_id, request.secret_graph_revision
        )
        saved_nodes = {node.id: node for node in graph.document.nodes}
        for node in request.nodes:
            registration = run.secret_registration(node)
            if registration is None:
                continue
            mismatch = _secret_node_mismatch(
                node, saved_nodes.get(node.id), registration
            )
            if mismatch is not None:
                error = self._error(graph, mismatch)
                if mismatch.cause is None:
                    raise error
                raise error from mismatch.cause
            run.secret_node_ids.add(node.id)

    @staticmethod
    def _error(
        graph: SavedGraph | SavedGraphRevision,
        mismatch: _SecretMismatch,
    ) -> SecretBindingError:
        node = f"Secret-bearing run node {mismatch.node_id!r}"
        if mismatch.kind == "absent":
            message = (
                f"{node} does not belong to saved graph {graph.id} "
                f"revision {graph.revision}"
            )
        elif mismatch.kind == "operator":
            message = (
                f"{node} does not match the saved operator in graph {graph.id} "
                f"revision {graph.revision}"
            )
        elif mismatch.kind == "configuration":
            message = f"{node} has invalid configuration"
        elif mismatch.kind == "dependencies":
            message = f"{node} has invalid secret configuration dependencies"
        else:
            message = (
                f"{node} does not match the saved configuration required by "
                f"secret input {mismatch.secret_input!r}"
            )
        return SecretBindingError(
            message,
            node_id=mismatch.node_id,
            graph_id=graph.id,
            revision=graph.revision,
            secret_input=mismatch.secret_input,
        )


class GraphRunPreflight:
    """Authorize a submitted fragment against its saved graph contexts.

    The checks are built once, hold nothing, and run in two passes: every
    `assert_ready` first, then every `validate`. The first failure raises
    `GraphExecutionError`, and a later check may assume the earlier ones passed —
    which is why the secret-context requirement is an `assert_ready` and never
    reaches a saved-graph lookup.
    """

    def __init__(
        self,
        *,
        plugin_registry: PluginRegistry,
        saved_graphs: SavedGraphService | None,
    ) -> None:
        self._registrations = {
            registration.key: registration for registration in plugin_registry.nodes
        }
        self._saved_graphs = saved_graphs
        self._checks: tuple[PreflightCheck, ...] = (
            SecretContextCheck(),
            SavedFragmentCheck(),
            SecretBindingCheck(),
        )

    async def validate(
        self,
        workspace_id: UUID,
        request: RunRequest,
    ) -> GraphRunContext:
        run = PreflightRun(
            workspace_id=workspace_id,
            request=request,
            registrations=self._registrations,
            saved_graphs=self._saved_graphs,
        )
        for check in self._checks:
            await check.assert_ready(run)
        for check in self._checks:
            await check.validate(run)
        return GraphRunContext(secret_node_ids=frozenset(run.secret_node_ids))


def _pinned_endpoints(request: RunRequest) -> set[tuple[str, str]]:
    return {(pinned.from_node, pinned.from_port) for pinned in request.pinned_outputs}


def _expected_incoming_edges(
    graph: SavedGraph | SavedGraphRevision,
    executed_node_ids: set[str],
    pinned_endpoints: set[tuple[str, str]],
) -> tuple[SavedGraphEdge, ...]:
    """Enabled saved edges into executed nodes, minus omitted optional inputs.

    An optional module input the run supplies as a pinned output instead of an edge
    is filled either way, so its saved edge is not something the run must echo.
    """

    saved_nodes = {node.id: node for node in graph.document.nodes}
    boundary_node_ids = {
        edge.from_node
        for edge in graph.document.edges
        if edge.enabled
        and edge.to_node in executed_node_ids
        and edge.from_port == MODULE_BOUNDARY_PORT
        and saved_nodes[edge.from_node].operator_id == MODULE_INPUT_OPERATOR_ID
    }
    omitted_endpoints: set[tuple[str, str]] = set()
    for boundary_node_id in boundary_node_ids:
        try:
            boundary_config = ModuleInputConfig.model_validate(
                saved_nodes[boundary_node_id].config_dict()
            )
        except ValueError as exc:
            raise GraphExecutionError(
                f"Saved graph {graph.id} revision {graph.revision} module input "
                f"boundary {boundary_node_id!r} has invalid configuration"
            ) from exc
        endpoint = (boundary_node_id, MODULE_BOUNDARY_PORT)
        if not boundary_config.required and endpoint not in pinned_endpoints:
            omitted_endpoints.add(endpoint)
    return tuple(
        edge
        for edge in graph.document.edges
        if edge.enabled
        and edge.to_node in executed_node_ids
        and (edge.from_node, edge.from_port) not in omitted_endpoints
    )


def _active_plug_ids_by_node(
    graph: SavedGraph | SavedGraphRevision,
    expected_edges: Iterable[SavedGraphEdge],
    executed_node_ids: set[str],
) -> dict[str, set[str]]:
    """Input plugs the saved fragment actually feeds, by edge or by origin."""

    plug_ids: dict[str, set[str]] = {}
    for edge in expected_edges:
        if edge.to_plug is not None:
            plug_ids.setdefault(edge.to_node, set()).add(edge.to_plug)
    for origin in graph.document.origins:
        if origin.to_node in executed_node_ids and origin.to_plug is not None:
            plug_ids.setdefault(origin.to_node, set()).add(origin.to_plug)
    return plug_ids


def _first_node_mismatch(
    graph: SavedGraph | SavedGraphRevision,
    nodes: list[RunNodeRequest],
    active_plug_ids_by_node: dict[str, set[str]],
) -> _NodeMismatch | None:
    saved_nodes = {node.id: node for node in graph.document.nodes}
    for node in nodes:
        saved_node = saved_nodes.get(node.id)
        if saved_node is None:
            return _NodeMismatch(node_id=node.id, kind="absent")
        if not _node_matches_saved(
            node,
            saved_node,
            active_plug_ids_by_node.get(node.id, set()),
        ):
            return _NodeMismatch(node_id=node.id, kind="mismatch")
    return None


def _node_matches_saved(
    node: RunNodeRequest,
    saved_node: SavedGraphNode,
    active_plug_ids: set[str],
) -> bool:
    submitted_plugs = tuple((plug.id, plug.port) for plug in node.input_plugs)
    saved_plugs = tuple(
        (plug.id, plug.port)
        for plug in saved_node.input_plugs
        if plug.id in active_plug_ids
    )
    submitted_bindings = {
        binding.variable: binding.artifact_type.to_key()
        for binding in node.artifact_type_bindings
    }
    saved_bindings = {
        binding.variable: binding.artifact_type
        for binding in saved_node.artifact_type_bindings
    }
    return (
        node.kind == saved_node.kind
        and node.operator_id == saved_node.operator_id
        and node.operator_version == saved_node.operator_version
        and node.config == saved_node.config_dict()
        and submitted_plugs == saved_plugs
        and submitted_bindings == saved_bindings
    )


def _edge_mismatch(
    expected_edges: Iterable[SavedGraphEdge],
    submitted_edges: Iterable[RunEdgeRequest],
) -> _MultisetMismatch | None:
    return _multiset_mismatch(
        (_edge_key(edge) for edge in expected_edges),
        (_edge_key(edge) for edge in submitted_edges),
    )


def _origin_mismatch(
    saved_origins: Iterable[SavedGraphOrigin],
    executed_node_ids: set[str],
    submitted_origins: Iterable[RunOriginRequest],
) -> _MultisetMismatch | None:
    return _multiset_mismatch(
        (
            _origin_key(origin)
            for origin in saved_origins
            if origin.to_node in executed_node_ids
        ),
        (_origin_key(origin) for origin in submitted_origins),
    )


def _multiset_mismatch(
    expected: Iterable[tuple[object, ...]],
    submitted: Iterable[tuple[object, ...]],
) -> _MultisetMismatch | None:
    """Compare two multisets, so a duplicated edge is not mistaken for two edges."""

    expected_counts = Counter(expected)
    submitted_counts = Counter(submitted)
    if submitted_counts == expected_counts:
        return None
    return _MultisetMismatch(
        missing_count=sum((expected_counts - submitted_counts).values()),
        unexpected_count=sum((submitted_counts - expected_counts).values()),
    )


def _edge_key(edge: SavedGraphEdge | RunEdgeRequest) -> tuple[object, ...]:
    return (
        edge.from_node,
        edge.from_port,
        edge.to_node,
        edge.to_port,
        edge.to_plug,
        edge.collection_mode,
        tuple(edge.projection.path) if edge.projection is not None else None,
        tuple((step.id, step.version) for step in edge.conversion_path),
    )


def _origin_key(origin: SavedGraphOrigin | RunOriginRequest) -> tuple[object, ...]:
    return (
        origin.to_node,
        origin.to_port,
        origin.to_plug,
        origin.value.model_dump_json(),
        origin.collection_mode,
        tuple((step.id, step.version) for step in origin.conversion_path),
    )


def _secret_node_mismatch(
    node: RunNodeRequest,
    saved_node: SavedGraphNode | None,
    registration: NodeRegistration,
) -> _SecretMismatch | None:
    if saved_node is None:
        return _SecretMismatch(node_id=node.id, kind="absent")
    if (
        saved_node.operator_id != node.operator_id
        or saved_node.operator_version != node.operator_version
    ):
        return _SecretMismatch(node_id=node.id, kind="operator")

    config_model = registration.node_class.config_contract.model
    try:
        submitted_config = config_model.model_validate(node.config).model_dump(
            mode="json"
        )
        saved_config = config_model.model_validate(saved_node.config_dict()).model_dump(
            mode="json"
        )
    except ValueError as exc:
        return _SecretMismatch(node_id=node.id, kind="configuration", cause=exc)

    for declaration in registration.secret_inputs:
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
            return _SecretMismatch(node_id=node.id, kind="dependencies", cause=exc)
        if not dependencies_match:
            return _SecretMismatch(
                node_id=node.id,
                kind="input",
                secret_input=declaration.name,
            )
    return None


__all__ = ["GraphRunContext", "GraphRunPreflight"]
