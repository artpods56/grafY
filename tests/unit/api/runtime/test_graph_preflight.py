from typing import override
from uuid import UUID, uuid4

import pytest

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.artifacts import (
    ArtifactTypeKey,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraph,
    SavedGraphArtifactTypeBinding,
    SavedGraphConversion,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphInputPlug,
    SavedGraphNode,
    SavedGraphPluginReleasePin,
    SavedGraphProjection,
    SavedGraphRevision,
)
from grafy_core.domain.plugin_releases import PluginReleaseScope
from grafy_core.domain.modules import (
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
    Plugin,
    PluginRegistry,
)

from grafy_api.v1.models import (
    ArtifactTypeBindingModel,
    ArtifactTypeKeyResponse,
    PluginReleasePinModel,
)
from grafy_api.plugins.runtime.network_policy import (
    NetworkAccessPlane,
    NetworkAccessProfile,
    NetworkPolicy,
    NetworkProfileAssignment,
    NetworkProfileMode,
)
from grafy_api.plugins.runtime.egress import PluginEgressDestination
from grafy_api.execution.requests import (
    ArtifactConversionRequest,
    FieldProjectionRequest,
    RunEdgeRequest,
    RunInputPlugRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.preflight import GraphRunPreflight
from tests.support.system_plugins import build_selected_system_plugin_deployment


class SecretConfig(NodeConfig):
    base_url: str
    model: str = "default-model"


class EmptyInput(NodeInput):
    pass


class EmptyOutput(NodeOutput):
    pass


PREFLIGHT_PLUGIN = Plugin(
    slug="test.graph-preflight",
    title="Graph preflight test",
)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


@PREFLIGHT_PLUGIN.node(
    operator_id="test.graph-preflight.secret",
    version=1,
    title="Secret node",
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            title="API key",
            config_dependencies=("base_url",),
        ),
    ),
    required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
)
class SecretNode(Node[SecretConfig, EmptyInput, EmptyOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: SecretConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        raise AssertionError("Preflight tests must not execute nodes")


@PREFLIGHT_PLUGIN.node(
    operator_id="test.graph-preflight.plain",
    version=1,
    title="Plain node",
)
class PlainNode(Node[NodeConfig, EmptyInput, EmptyOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NodeConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        raise AssertionError("Preflight tests must not execute nodes")


PLUGIN_REGISTRY = PluginRegistry()
PLUGIN_REGISTRY.install(PREFLIGHT_PLUGIN)
PLUGIN_REGISTRY.freeze()


class _RecordingSavedGraphs(SavedGraphService):
    def __init__(self, *revisions: SavedGraphRevision) -> None:
        self._revisions = {
            (revision.id, revision.revision): revision for revision in revisions
        }
        self.calls: list[tuple[UUID, int]] = []

    @override
    async def get_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        revision: int,
    ) -> SavedGraphRevision:
        del workspace_id
        self.calls.append((graph_id, revision))
        return self._revisions[(graph_id, revision)]


def _fragment_case() -> tuple[SavedGraphRevision, RunRequest]:
    bound_type = ArtifactTypeKey("test.graph-preflight.value", 1)
    saved_input = SavedGraphEdge(
        id="source-to-target",
        from_node="source",
        from_port="response",
        to_node="target",
        to_port="items",
        to_plug="payload",
        collection_mode="map",
        projection=SavedGraphProjection(path=("payload",)),
        conversion_path=(SavedGraphConversion(id="test.convert", version=2),),
    )
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Saved fragment",
        document=SavedGraphDocument(
            nodes=(
                SavedGraphNode(
                    kind="builtin",
                    id="source",
                    operator_id="test.graph-preflight.plain",
                    operator_version=1,
                    config={},
                    position=GraphPoint(x=0, y=0),
                ),
                SavedGraphNode(
                    kind="builtin",
                    id="target",
                    operator_id="test.graph-preflight.plain",
                    operator_version=1,
                    config={"nested": {"strict": True}},
                    position=GraphPoint(x=100, y=0),
                    input_plugs=(SavedGraphInputPlug(id="payload", port="items"),),
                    artifact_type_bindings=(
                        SavedGraphArtifactTypeBinding(
                            variable="T",
                            artifact_type=bound_type,
                        ),
                    ),
                ),
                SavedGraphNode(
                    kind="builtin",
                    id="downstream",
                    operator_id="test.graph-preflight.plain",
                    operator_version=1,
                    config={},
                    position=GraphPoint(x=200, y=0),
                ),
            ),
            edges=(
                saved_input,
                SavedGraphEdge(
                    id="target-to-downstream",
                    from_node="target",
                    from_port="result",
                    to_node="downstream",
                    to_port="value",
                ),
            ),
        ),
    ).snapshot()
    request = RunRequest(
        graph_id=graph.id,
        graph_revision=graph.revision,
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="target",
                operator_id="test.graph-preflight.plain",
                operator_version=1,
                config={"nested": {"strict": True}},
                input_plugs=[RunInputPlugRequest(id="payload", port="items")],
                artifact_type_bindings=[
                    ArtifactTypeBindingModel(
                        variable="T",
                        artifact_type=ArtifactTypeKeyResponse(
                            id=bound_type.id,
                            schema_version=bound_type.schema_version,
                        ),
                    )
                ],
            )
        ],
        edges=[
            RunEdgeRequest(
                from_node=saved_input.from_node,
                from_port=saved_input.from_port,
                to_node=saved_input.to_node,
                to_port=saved_input.to_port,
                to_plug=saved_input.to_plug,
                collection_mode=saved_input.collection_mode,
                projection=FieldProjectionRequest(path=["payload"]),
                conversion_path=[
                    ArtifactConversionRequest(id="test.convert", version=2)
                ],
            )
        ],
    )
    return graph, request


def _secret_revision() -> SavedGraphRevision:
    return SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Saved secret binding",
        document=SavedGraphDocument(
            nodes=(
                SavedGraphNode(
                    kind="builtin",
                    id="secret",
                    operator_id="test.graph-preflight.secret",
                    operator_version=1,
                    config={
                        "base_url": "https://provider.example/v1",
                        "model": "saved-model",
                    },
                    position=GraphPoint(x=0, y=0),
                ),
            )
        ),
    ).snapshot()


def _module_input_fragment(*, required: bool) -> tuple[SavedGraphRevision, RunRequest]:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Module input fragment",
        document=SavedGraphDocument(
            nodes=(
                SavedGraphNode(
                    kind="module",
                    id="module-input",
                    operator_id="module.input",
                    operator_version=1,
                    config={"public_name": "value", "required": required},
                    position=GraphPoint(x=0, y=0),
                ),
                SavedGraphNode(
                    kind="builtin",
                    id="target",
                    operator_id="test.graph-preflight.plain",
                    operator_version=1,
                    config={},
                    position=GraphPoint(x=100, y=0),
                ),
            ),
            edges=(
                SavedGraphEdge(
                    id="input-to-target",
                    from_node="module-input",
                    from_port="value",
                    to_node="target",
                    to_port="value",
                ),
            ),
        ),
    ).snapshot()
    request = RunRequest(
        graph_id=graph.id,
        graph_revision=graph.revision,
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="target",
                operator_id="test.graph-preflight.plain",
                operator_version=1,
            )
        ],
    )
    return graph, request


@pytest.mark.asyncio
async def test_saved_fragment_matches_exact_node_and_incoming_edge_state() -> None:
    graph, request = _fragment_case()
    saved_graphs = _RecordingSavedGraphs(graph)
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=saved_graphs,
    )

    context = await preflight.validate(WORKSPACE_ID, request)

    assert context.secret_node_ids == frozenset()
    assert saved_graphs.calls == [(graph.id, graph.revision)]


@pytest.mark.asyncio
async def test_saved_fragment_rejects_node_and_edge_drift() -> None:
    graph, matching = _fragment_case()
    saved_graphs = _RecordingSavedGraphs(graph)
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=saved_graphs,
    )
    changed_node = matching.nodes[0].model_copy(
        update={"config": {"nested": {"strict": False}}}
    )
    changed_edge = matching.edges[0].model_copy(update={"conversion_path": []})

    with pytest.raises(GraphExecutionError, match="does not match saved graph"):
        await preflight.validate(
            WORKSPACE_ID, matching.model_copy(update={"nodes": [changed_node]})
        )
    with pytest.raises(
        GraphExecutionError,
        match="1 missing and 1 unexpected or duplicated",
    ):
        await preflight.validate(
            WORKSPACE_ID, matching.model_copy(update={"edges": [changed_edge]})
        )


@pytest.mark.asyncio
async def test_saved_fragment_ignores_disabled_incoming_edges() -> None:
    graph, submitted = _fragment_case()
    disabled_document = graph.document.model_copy(
        update={
            "edges": (
                graph.document.edges[0].model_copy(update={"enabled": False}),
                graph.document.edges[1],
            )
        }
    )
    disabled_graph = SavedGraphRevision(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.graph_id,
        revision=graph.revision,
        name=graph.name,
        document=disabled_document,
        created_at=graph.created_at,
    )
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=_RecordingSavedGraphs(disabled_graph),
    )
    active_node = submitted.nodes[0].model_copy(update={"input_plugs": []})
    active_request = submitted.model_copy(update={"nodes": [active_node], "edges": []})

    await preflight.validate(WORKSPACE_ID, active_request)

    with pytest.raises(
        GraphExecutionError,
        match="0 missing and 1 unexpected or duplicated",
    ):
        await preflight.validate(
            WORKSPACE_ID, active_request.model_copy(update={"edges": submitted.edges})
        )


@pytest.mark.asyncio
async def test_optional_unpinned_module_input_edge_may_be_omitted() -> None:
    graph, request = _module_input_fragment(required=False)
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=_RecordingSavedGraphs(graph),
    )

    context = await preflight.validate(WORKSPACE_ID, request)

    assert context.secret_node_ids == frozenset()


@pytest.mark.asyncio
async def test_required_unpinned_module_input_edge_must_not_be_omitted() -> None:
    graph, request = _module_input_fragment(required=True)
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=_RecordingSavedGraphs(graph),
    )

    with pytest.raises(
        GraphExecutionError,
        match="1 missing and 0 unexpected or duplicated",
    ):
        await preflight.validate(WORKSPACE_ID, request)


@pytest.mark.asyncio
async def test_dirty_secret_context_checks_only_saved_secret_dependencies() -> None:
    graph = _secret_revision()
    saved_graphs = _RecordingSavedGraphs(graph)
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=saved_graphs,
    )
    request = RunRequest(
        secret_graph_id=graph.id,
        secret_graph_revision=graph.revision,
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="secret",
                operator_id="test.graph-preflight.secret",
                operator_version=1,
                config={
                    "base_url": "https://provider.example/v1",
                    "model": "dirty-unsaved-model",
                },
            ),
            RunNodeRequest(
                kind="builtin",
                id="unsaved-plain",
                operator_id="test.graph-preflight.plain",
                operator_version=1,
            ),
        ],
    )

    context = await preflight.validate(WORKSPACE_ID, request)

    assert context.secret_node_ids == frozenset({"secret"})
    assert saved_graphs.calls == [(graph.id, graph.revision)]


@pytest.mark.asyncio
async def test_secret_context_rejects_changed_dependency_binding() -> None:
    graph = _secret_revision()
    saved_graphs = _RecordingSavedGraphs(graph)
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=saved_graphs,
    )

    with pytest.raises(
        GraphExecutionError,
        match="saved configuration required by secret input 'api_key'",
    ):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                secret_graph_id=graph.id,
                secret_graph_revision=graph.revision,
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="secret",
                        operator_id="test.graph-preflight.secret",
                        operator_version=1,
                        config={
                            "base_url": "https://changed.example/v1",
                            "model": "saved-model",
                        },
                    )
                ],
            ),
        )


@pytest.mark.asyncio
async def test_secret_nodes_require_explicit_secret_context_before_graph_lookup() -> (
    None
):
    graph = _secret_revision()
    saved_graphs = _RecordingSavedGraphs(graph)
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=saved_graphs,
    )

    with pytest.raises(
        GraphExecutionError,
        match="saved secret graph context.*'alpha', 'zeta'",
    ):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                graph_id=graph.id,
                graph_revision=graph.revision,
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id=node_id,
                        operator_id="test.graph-preflight.secret",
                        operator_version=1,
                        config={"base_url": "https://provider.example/v1"},
                    )
                    for node_id in ("zeta", "alpha")
                ],
            ),
        )
    assert saved_graphs.calls == []


@pytest.mark.asyncio
async def test_saved_context_requires_configured_saved_graph_service() -> None:
    graph = _secret_revision()
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=None,
    )

    with pytest.raises(
        GraphExecutionError,
        match="Saved graph context is not configured for this workbench",
    ):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                graph_id=graph.id,
                graph_revision=graph.revision,
                nodes=[],
            ),
        )


@pytest.mark.asyncio
async def test_saved_fragment_requires_the_exact_plugin_release_pin() -> None:
    graph, matching = _fragment_case()
    deployment = build_selected_system_plugin_deployment((PREFLIGHT_PLUGIN,))
    pinned_document = graph.document.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(
                    update={
                        "kind": "plugin",
                        "plugin_release_pin": SavedGraphPluginReleasePin(
                            scope=PluginReleaseScope.SYSTEM,
                            slug=PREFLIGHT_PLUGIN.slug,
                            revision=1,
                        ),
                    }
                )
                if node.id == "target"
                else node
                for node in graph.document.nodes
            )
        }
    )
    pinned_graph = SavedGraphRevision(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.graph_id,
        revision=graph.revision,
        name=graph.name,
        document=pinned_document,
        created_at=graph.created_at,
    )
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=_RecordingSavedGraphs(pinned_graph),
        plugin_release_lookup=deployment.release_lookup,
    )

    # The exact same pin is accepted.
    pinned_node = matching.nodes[0].model_copy(
        update={
            "kind": "plugin",
            "plugin_release": PluginReleasePinModel(
                scope=PluginReleaseScope.SYSTEM,
                slug=PREFLIGHT_PLUGIN.slug,
                revision=1,
            ),
        }
    )
    await preflight.validate(
        WORKSPACE_ID,
        matching.model_copy(update={"nodes": [pinned_node]}),
    )

    # Any drift to an unavailable exact release is rejected before graph lookup.
    for drifted in (
        PluginReleasePinModel(
            scope=PluginReleaseScope.SYSTEM,
            slug=PREFLIGHT_PLUGIN.slug,
            revision=2,
        ),
        PluginReleasePinModel(
            scope=PluginReleaseScope.SYSTEM,
            slug="other",
            revision=1,
        ),
    ):
        changed = matching.nodes[0].model_copy(
            update={"kind": "plugin", "plugin_release": drifted}
        )
        with pytest.raises(GraphExecutionError, match="does not exist"):
            await preflight.validate(
                WORKSPACE_ID,
                matching.model_copy(update={"nodes": [changed]}),
            )

    unpinned = matching.nodes[0].model_copy(update={"plugin_release": None})
    with pytest.raises(GraphExecutionError, match="does not match saved graph"):
        await preflight.validate(
            WORKSPACE_ID,
            matching.model_copy(update={"nodes": [unpinned]}),
        )


@pytest.mark.asyncio
async def test_isolated_secret_detection_uses_one_exact_serialized_release_read() -> (
    None
):
    deployment = build_selected_system_plugin_deployment((PREFLIGHT_PLUGIN,))
    empty_registry = PluginRegistry()
    empty_registry.freeze()
    preflight = GraphRunPreflight(
        plugin_registry=empty_registry,
        saved_graphs=None,
        plugin_release_lookup=deployment.release_lookup,
    )
    pin = PluginReleasePinModel(
        scope=PluginReleaseScope.SYSTEM,
        slug=PREFLIGHT_PLUGIN.slug,
        revision=1,
    )

    with pytest.raises(
        GraphExecutionError,
        match="saved secret graph context.*'alpha', 'zeta'",
    ):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="plugin",
                        id=node_id,
                        operator_id="test.graph-preflight.secret",
                        operator_version=1,
                        config={"base_url": "https://provider.example/v1"},
                        plugin_release=pin,
                    )
                    for node_id in ("zeta", "alpha")
                ]
            ),
        )

    assert deployment.release_lookup.release_reads == 1


@pytest.mark.asyncio
async def test_isolated_secret_bindings_use_the_serialized_release_contract() -> None:
    deployment = build_selected_system_plugin_deployment((PREFLIGHT_PLUGIN,))
    empty_registry = PluginRegistry()
    empty_registry.freeze()
    graph = _secret_revision()
    pinned_document = graph.document.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(
                    update={
                        "kind": "plugin",
                        "plugin_release_pin": SavedGraphPluginReleasePin(
                            scope=PluginReleaseScope.SYSTEM,
                            slug=PREFLIGHT_PLUGIN.slug,
                            revision=1,
                        ),
                    }
                )
                for node in graph.document.nodes
            )
        }
    )
    pinned_graph = SavedGraphRevision(
        workspace_id=WORKSPACE_ID,
        graph_id=graph.graph_id,
        revision=graph.revision,
        name=graph.name,
        document=pinned_document,
        created_at=graph.created_at,
    )
    preflight = GraphRunPreflight(
        plugin_registry=empty_registry,
        saved_graphs=_RecordingSavedGraphs(pinned_graph),
        plugin_release_lookup=deployment.release_lookup,
    )
    pin = PluginReleasePinModel(
        scope=PluginReleaseScope.SYSTEM,
        slug=PREFLIGHT_PLUGIN.slug,
        revision=1,
    )
    matching = RunRequest(
        secret_graph_id=pinned_graph.id,
        secret_graph_revision=pinned_graph.revision,
        nodes=[
            RunNodeRequest(
                kind="plugin",
                id="secret",
                operator_id="test.graph-preflight.secret",
                operator_version=1,
                config={
                    "base_url": "https://provider.example/v1",
                    "model": "dirty-model",
                },
                plugin_release=pin,
            )
        ],
    )

    context = await preflight.validate(WORKSPACE_ID, matching)
    assert context.secret_node_ids == frozenset({"secret"})

    changed = matching.nodes[0].model_copy(
        update={"config": {"base_url": "https://changed.example/v1"}}
    )
    with pytest.raises(
        GraphExecutionError,
        match="saved configuration required by secret input 'api_key'",
    ):
        await preflight.validate(
            WORKSPACE_ID,
            matching.model_copy(update={"nodes": [changed]}),
        )


@pytest.mark.parametrize(
    "operator_id, error_fragment",
    [
        (MODULE_INPUT_OPERATOR_ID, "module boundaries cannot carry"),
        (MODULE_OUTPUT_OPERATOR_ID, "module boundaries cannot carry"),
        (f"graph.module.{uuid4()}", "modules cannot carry"),
    ],
)
@pytest.mark.asyncio
async def test_pinned_module_operators_fail_before_exact_release_lookup(
    operator_id: str,
    error_fragment: str,
) -> None:
    deployment = build_selected_system_plugin_deployment((PREFLIGHT_PLUGIN,))
    preflight = GraphRunPreflight(
        plugin_registry=PLUGIN_REGISTRY,
        saved_graphs=None,
        plugin_release_lookup=deployment.release_lookup,
    )

    with pytest.raises(GraphExecutionError, match=error_fragment):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="plugin",
                        id="module",
                        operator_id=operator_id,
                        operator_version=1,
                        plugin_release=PluginReleasePinModel(
                            scope=PluginReleaseScope.SYSTEM,
                            slug=PREFLIGHT_PLUGIN.slug,
                            revision=1,
                        ),
                    )
                ]
            ),
        )

    assert deployment.release_lookup.release_reads == 0


EGRESS_PLUGIN = Plugin(
    slug="test.graph-preflight.egress",
    title="Egress preflight test",
)


class EgressConfig(NodeConfig):
    base_url: str


@EGRESS_PLUGIN.node(
    operator_id="test.graph-preflight.egress.configured",
    version=1,
    title="Configured egress node",
    required_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
    http_egress=NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="base_url"),)
    ),
)
class EgressConfiguredNode(Node[EgressConfig, EmptyInput, EmptyOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: EgressConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        raise AssertionError("Preflight tests must not execute nodes")


@EGRESS_PLUGIN.node(
    operator_id="test.graph-preflight.egress.dynamic",
    version=1,
    title="Dynamic egress node",
    required_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
    http_egress=NodeHttpEgressContract(dynamic_destinations=True),
)
class EgressDynamicNode(Node[NodeConfig, EmptyInput, EmptyOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NodeConfig,
        _inputs: EmptyInput,
        /,
    ) -> EmptyOutput:
        raise AssertionError("Preflight tests must not execute nodes")


def _egress_preflight(
    policy: NetworkPolicy | None,
) -> tuple[GraphRunPreflight, PluginReleasePinModel]:
    deployment = build_selected_system_plugin_deployment((EGRESS_PLUGIN,))
    preflight = GraphRunPreflight(
        plugin_registry=deployment.registry,
        saved_graphs=None,
        plugin_release_lookup=deployment.release_lookup,
        network_policy=policy,
    )
    return preflight, PluginReleasePinModel(
        scope=PluginReleaseScope.SYSTEM,
        slug=EGRESS_PLUGIN.slug,
        revision=1,
    )


def _egress_policy(
    *,
    profile: NetworkAccessProfile,
    slug: str | None = EGRESS_PLUGIN.slug,
) -> NetworkPolicy:
    return NetworkPolicy(
        profiles={(profile.plane, profile.name): profile},
        assignments=(
            NetworkProfileAssignment(
                plane=profile.plane,
                profile=profile.name,
                scope=PluginReleaseScope.SYSTEM,
                slug=slug,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_preflight_denies_network_node_under_the_default_offline_profile() -> (
    None
):
    preflight, pin = _egress_preflight(None)

    with pytest.raises(GraphExecutionError, match="network_profile_disabled"):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="plugin",
                        id="egress",
                        operator_id="test.graph-preflight.egress.configured",
                        operator_version=1,
                        config={"base_url": "https://api.example.com/v1"},
                        plugin_release=pin,
                    )
                ]
            ),
        )


@pytest.mark.asyncio
async def test_preflight_allows_configured_egress_under_assigned_profile() -> None:
    profile = NetworkAccessProfile(
        name="public",
        plane=NetworkAccessPlane.PLUGIN_EXECUTION,
        mode=NetworkProfileMode.CONFIGURED_PUBLIC,
    )
    preflight, pin = _egress_preflight(_egress_policy(profile=profile))

    context = await preflight.validate(
        WORKSPACE_ID,
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="plugin",
                    id="egress",
                    operator_id="test.graph-preflight.egress.configured",
                    operator_version=1,
                    config={"base_url": "https://api.example.com/v1"},
                    plugin_release=pin,
                )
            ]
        ),
    )
    assert context is not None


@pytest.mark.asyncio
async def test_preflight_denies_configured_egress_outside_curated_allowlist() -> (
    None
):
    profile = NetworkAccessProfile(
        name="curated",
        plane=NetworkAccessPlane.PLUGIN_EXECUTION,
        mode=NetworkProfileMode.CURATED,
        allowed_origins=(
            PluginEgressDestination.parse("https://approved.example.com:443"),
        ),
    )
    preflight, pin = _egress_preflight(_egress_policy(profile=profile))

    with pytest.raises(
        GraphExecutionError,
        match="network_destination_not_allowlisted",
    ):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="plugin",
                        id="egress",
                        operator_id="test.graph-preflight.egress.configured",
                        operator_version=1,
                        config={"base_url": "https://intruder.example.com/v1"},
                        plugin_release=pin,
                    )
                ]
            ),
        )


@pytest.mark.asyncio
async def test_preflight_denies_dynamic_destinations_in_first_release() -> None:
    profile = NetworkAccessProfile(
        name="public",
        plane=NetworkAccessPlane.PLUGIN_EXECUTION,
        mode=NetworkProfileMode.CONFIGURED_PUBLIC,
    )
    preflight, pin = _egress_preflight(_egress_policy(profile=profile))

    with pytest.raises(
        GraphExecutionError,
        match="network_dynamic_destination_denied",
    ):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="plugin",
                        id="dynamic",
                        operator_id="test.graph-preflight.egress.dynamic",
                        operator_version=1,
                        plugin_release=pin,
                    )
                ]
            ),
        )


@pytest.mark.asyncio
async def test_preflight_denies_configured_node_without_url_value() -> None:
    profile = NetworkAccessProfile(
        name="public",
        plane=NetworkAccessPlane.PLUGIN_EXECUTION,
        mode=NetworkProfileMode.CONFIGURED_PUBLIC,
    )
    preflight, pin = _egress_preflight(_egress_policy(profile=profile))

    with pytest.raises(GraphExecutionError, match="network_destination_undeclared"):
        await preflight.validate(
            WORKSPACE_ID,
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="plugin",
                        id="egress",
                        operator_id="test.graph-preflight.egress.configured",
                        operator_version=1,
                        config={},
                        plugin_release=pin,
                    )
                ]
            ),
        )
