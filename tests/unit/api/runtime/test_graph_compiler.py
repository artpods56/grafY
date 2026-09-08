from collections.abc import Mapping
from pathlib import Path
from typing import Never
from uuid import UUID, uuid4

import pytest

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey, InMemoryUnitOfWork
from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.canonical_conversions import (
    CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
    CanonicalArtifactConversionMap,
)
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.domain.modules import GraphModuleDefinition
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import Plugin, PluginRegistry, PluginRuntimeContext
from grafy_core.ports.modules import GraphModuleExecutionResult
from grafy_core.runtime.invocation import InvocationMode
from grafy_storage import LocalFileObjectStore

from grafy_api.execution.requests import (
    ArtifactConversionRequest,
    PinnedOutputRequest,
    RunEdgeRequest,
    RunNodeRequest,
    RunRequest,
)
from tests.support.system_plugins import (
    TEST_BUILD_DIGEST,
    TEST_SYSTEM_PLUGINS,
    build_explicit_plugin_registry,
    build_selected_system_plugin_deployment,
)
from grafy_core.application.modules import ModuleLibraryService
from grafy_api.plugins.runtime.admission import ReleaseExecutionAdmission
from grafy_api.execution.compiler import (
    GraphCompiler,
    _topological_order,
)
from grafy_api.execution.errors import GraphExecutionError


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
SYSTEM_DEPLOYMENT = build_selected_system_plugin_deployment()


def _ambient_integer_to_text(value: int) -> str:
    return str(value)


AMBIENT_INTEGER_TO_TEXT = ArtifactConversion(
    key=ArtifactConversionKey("test.ambient.integer_to_text", 1),
    source=INTEGER_VALUE.key,
    target=TEXT_VALUE.key,
    source_type=int,
    target_type=str,
    title="Ambient integer as text",
    convert=_ambient_integer_to_text,
)


class _UnusedModuleExecutor:
    async def execute_module(
        self,
        _definition: GraphModuleDefinition,
        _context: NodeExecutionContext,
        _inputs: Mapping[str, ArtifactRef],
        /,
    ) -> GraphModuleExecutionResult:
        raise AssertionError("Compiler test unexpectedly executed a graph module")


def _unused_saved_graph_uow() -> Never:
    raise AssertionError("Compiler test unexpectedly queried saved graphs")


def _compiler(
    tmp_path: Path,
    *,
    registry: PluginRegistry | None = None,
    canonical_artifact_conversions: CanonicalArtifactConversionMap = (
        CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
    ),
) -> GraphCompiler:
    resolved_registry = registry or build_explicit_plugin_registry()
    unit_of_work = InMemoryUnitOfWork()
    workspace = tmp_path / "workbench"
    uploads_dir = workspace / "uploads"
    uploads_dir.mkdir(parents=True)
    plugin_context = PluginRuntimeContext(
        workspace=workspace,
        uploads_dir=uploads_dir,
        storage=LocalFileObjectStore(workspace / "objects"),
        uow=unit_of_work,
        bucket="test-artifacts",
    )
    return GraphCompiler(
        plugin_registry=resolved_registry,
        plugin_context=plugin_context,
        module_library=ModuleLibraryService(_unused_saved_graph_uow, resolved_registry),
        canonical_artifact_conversions=canonical_artifact_conversions,
        plugin_release_lookup=SYSTEM_DEPLOYMENT.release_lookup,
        release_admission=ReleaseExecutionAdmission(
            isolated_adapter_available=False,
            runtime_profile=None,
            system_host_bindings=SYSTEM_DEPLOYMENT.host_bindings,
        ),
        build_digest=TEST_BUILD_DIGEST,
    )


def _pin_system_plugins(request: RunRequest) -> RunRequest:
    return request.model_copy(
        update={"nodes": [SYSTEM_DEPLOYMENT.pin_node(node) for node in request.nodes]}
    )


@pytest.mark.asyncio
async def test_compiler_orders_nodes_and_resolves_declared_conversions(
    tmp_path: Path,
) -> None:
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="replace",
                operator_id="text.replace",
                operator_version=1,
                config={"search": "1", "replacement": "one"},
            ),
            RunNodeRequest(
                kind="builtin",
                id="number",
                operator_id="arithmetic.number",
                operator_version=1,
                config={"value": 12},
            ),
        ],
        edges=[
            RunEdgeRequest(
                from_node="number",
                from_port="value",
                to_node="replace",
                to_port="text",
                conversion_path=[
                    ArtifactConversionRequest(
                        id="builtin.scalar.integer_to_text",
                        version=1,
                    )
                ],
            )
        ],
    )

    compiled = await _compiler(tmp_path).compile(
        _pin_system_plugins(request),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert [node.request.id for node in compiled.nodes] == ["number", "replace"]
    assert compiled.nodes[0].registration is not None
    assert compiled.nodes[1].resolved_contracts.input_contract.ports[
        "text"
    ].accepts == (ArtifactTypeKey("scalar.text", 1))
    assert len(compiled.edges) == 1
    assert compiled.edges[0].projection is None
    assert [conversion.key.id for conversion in compiled.edges[0].conversion_path] == [
        "builtin.scalar.integer_to_text"
    ]


@pytest.mark.asyncio
async def test_compiler_does_not_resolve_mutable_plugin_registry_conversions(
    tmp_path: Path,
) -> None:
    ambient_plugin = Plugin(slug="test.ambient", title="Ambient conversion")
    ambient_plugin.register_artifact_type_dependency(INTEGER_VALUE)
    ambient_plugin.register_artifact_type_dependency(TEXT_VALUE)
    ambient_plugin.register_artifact_conversion(AMBIENT_INTEGER_TO_TEXT)
    registry = build_explicit_plugin_registry((*TEST_SYSTEM_PLUGINS, ambient_plugin))
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="number",
                operator_id="arithmetic.number",
                operator_version=1,
                config={"value": 12},
            ),
            RunNodeRequest(
                kind="builtin",
                id="replace",
                operator_id="text.replace",
                operator_version=1,
                config={"search": "1", "replacement": "one"},
            ),
        ],
        edges=[
            RunEdgeRequest(
                from_node="number",
                from_port="value",
                to_node="replace",
                to_port="text",
                conversion_path=[
                    ArtifactConversionRequest(
                        id=AMBIENT_INTEGER_TO_TEXT.key.id,
                        version=AMBIENT_INTEGER_TO_TEXT.key.version,
                    )
                ],
            )
        ],
    )

    with pytest.raises(GraphExecutionError, match="requests undeclared conversion"):
        await _compiler(tmp_path, registry=registry).compile(
            _pin_system_plugins(request),
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_compiler_derives_map_invocation_from_the_incoming_edge(
    tmp_path: Path,
) -> None:
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="replace",
                operator_id="text.replace",
                operator_version=1,
                config={"search": "a", "replacement": "A"},
            ),
            RunNodeRequest(
                kind="builtin",
                id="split",
                operator_id="text.split",
                operator_version=1,
                config={"separator": "|"},
            ),
            RunNodeRequest(
                kind="builtin",
                id="source",
                operator_id="text.input",
                operator_version=1,
                config={"text": "a|ba"},
            ),
        ],
        edges=[
            RunEdgeRequest(
                from_node="source",
                from_port="text",
                to_node="split",
                to_port="text",
            ),
            RunEdgeRequest(
                from_node="split",
                from_port="parts",
                to_node="replace",
                to_port="text",
                collection_mode="map",
            ),
        ],
    )

    compiled = await _compiler(tmp_path).compile(
        _pin_system_plugins(request),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    replace = next(node for node in compiled.nodes if node.request.id == "replace")
    assert replace.invocation.mode is InvocationMode.MAP
    assert replace.invocation.map_input == "text"
    assert compiled.edges[1].request.collection_mode == "map"


@pytest.mark.asyncio
async def test_compiler_accepts_an_external_edge_only_with_its_exact_pin(
    tmp_path: Path,
) -> None:
    pinned_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=ArtifactTypeKey("scalar.text", 1),
    )
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="replace",
                operator_id="text.replace",
                operator_version=1,
                config={"search": "a", "replacement": "A"},
            )
        ],
        edges=[
            RunEdgeRequest(
                from_node="upstream",
                from_port="text",
                to_node="replace",
                to_port="text",
            )
        ],
        pinned_outputs=[
            PinnedOutputRequest(
                from_node="upstream",
                from_port="text",
                value=pinned_ref,
            )
        ],
    )

    compiled = await _compiler(tmp_path).compile(
        _pin_system_plugins(request),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert compiled.pinned_outputs == {("upstream", "text"): pinned_ref}
    assert [node.request.id for node in compiled.nodes] == ["replace"]


def _node(node_id: str) -> RunNodeRequest:
    return RunNodeRequest(
        kind="builtin",
        id=node_id,
        operator_id="text.input",
        operator_version=1,
        config={"text": "x"},
    )


def _edge(from_node: str, to_node: str) -> RunEdgeRequest:
    return RunEdgeRequest(
        from_node=from_node,
        from_port="text",
        to_node=to_node,
        to_port="text",
    )


def test_topological_order_handles_fan_in_fan_out_and_duplicate_edges() -> None:
    """Phase-local adjacency ordering preserves zero-indegree, fan-in/fan-out,
    and parallel-edge multiplicity."""

    nodes = [_node("a"), _node("b"), _node("c"), _node("d")]
    # a fans out to b and c; both b and c fan in to d; duplicate a->d edge.
    edges = [
        _edge("a", "b"),
        _edge("a", "c"),
        _edge("b", "d"),
        _edge("c", "d"),
        _edge("a", "d"),
    ]
    ordered = _topological_order(nodes, edges)
    assert [node.id for node in ordered] == ["a", "b", "c", "d"]

    # A duplicate edge into d must still be decremented twice (it is one extra
    # indegree), so d appears after b and c even when the duplicate is present.
    nodes2 = [_node("x"), _node("y"), _node("z")]
    edges2 = [_edge("x", "y"), _edge("x", "y"), _edge("y", "z")]
    ordered2 = _topological_order(nodes2, edges2)
    assert [node.id for node in ordered2] == ["x", "y", "z"]


def test_topological_order_rejects_cycles() -> None:
    nodes = [_node("a"), _node("b"), _node("c")]
    edges = [_edge("a", "b"), _edge("b", "c"), _edge("c", "a")]
    with pytest.raises(GraphExecutionError, match="cycle"):
        _topological_order(nodes, edges)


def test_topological_order_on_large_sparse_dag() -> None:
    """A large sparse DAG with a long chain and many parallel branches sorts
    correctly without rescanning every edge per node."""

    chain = 200
    nodes = [_node(f"n{i}") for i in range(chain)] + [
        _node(f"branch{i}") for i in range(100)
    ]
    edges: list[RunEdgeRequest] = []
    for i in range(chain - 1):
        edges.append(_edge(f"n{i}", f"n{i + 1}"))
    # Every chain node feeds a distinct branch leaf; every branch leaf fans in
    # to the final chain node.
    for i in range(100):
        edges.append(_edge(f"n{i % (chain - 1)}", f"branch{i}"))
        edges.append(_edge(f"branch{i}", f"n{chain - 1}"))
    ordered = _topological_order(nodes, edges)
    ids = [node.id for node in ordered]
    assert len(ids) == len(nodes)
    # Chain order is preserved: n{i} appears before n{i+1}.
    for i in range(chain - 1):
        assert ids.index(f"n{i}") < ids.index(f"n{i + 1}")
    # Every branch leaf depends on the chain, so it must not precede its chain
    # parent, and must precede the final chain node.
    for i in range(100):
        parent = f"n{i % (chain - 1)}"
        assert ids.index(parent) < ids.index(f"branch{i}")
        assert ids.index(f"branch{i}") < ids.index(f"n{chain - 1}")
