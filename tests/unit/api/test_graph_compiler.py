from collections.abc import Mapping
from pathlib import Path
from typing import Never
from uuid import UUID, uuid4

import pytest

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    InMemoryUnitOfWork,
)
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentPortDirection,
    BuildArtifactSet,
    CapabilityManifest,
    GeneratedNodeManifest,
    GeneratedNodePort,
    NodeRelease,
    RuntimeArtifactReference,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.modules import GraphModuleDefinition
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.operators.generated import GeneratedNode
from grafy_core.plugins import PluginRuntimeContext
from grafy_core.ports.generated_execution import (
    GeneratedNodeExecutionRequest,
    GeneratedNodeExecutionResult,
)
from grafy_core.ports.modules import GraphModuleExecutionResult
from grafy_core.runtime.invocation import InvocationMode
from grafy_core.source_bundles import GeneratedNodeBuildDocument
from grafy_storage import LocalFileObjectStore

from grafy_api.builtins import builtin_plugins
from grafy_api.plugin_discovery import build_plugin_registry
from grafy_api.v1.routes.executions.models import (
    ArtifactConversionRequest,
    PinnedOutputRequest,
    RunEdgeRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.v1.routes.catalog.services import GraphModuleCatalog
from grafy_api.v1.routes.executions.runtime.compiler import GraphCompiler
from grafy_api.v1.routes.executions.runtime.errors import GraphExecutionError


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
GENERATED_NODE_ID = UUID("00000000-0000-0000-0000-000000000107")


class _UnusedModuleExecutor:
    async def execute_module(
        self,
        _definition: GraphModuleDefinition,
        _context: NodeExecutionContext,
        _inputs: Mapping[str, ArtifactRef],
        /,
    ) -> GraphModuleExecutionResult:
        raise AssertionError("Compiler test unexpectedly executed a graph module")


class _GeneratedReleaseCatalog:
    def __init__(self, release: NodeRelease | None) -> None:
        self._release = release
        self.lookups: list[tuple[UUID, UUID, int]] = []

    async def get_release(
        self,
        *,
        workspace_id: UUID,
        node_id: UUID,
        revision: int,
    ) -> NodeRelease:
        self.lookups.append((workspace_id, node_id, revision))
        release = self._release
        if (
            release is None
            or release.workspace_id != workspace_id
            or release.node_id != node_id
            or release.revision != revision
        ):
            raise NotFoundError("Generated node release", f"{node_id}@{revision}")
        return release


class _UnusedGeneratedExecutor:
    async def execute(
        self,
        _request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        raise AssertionError("Compiler test unexpectedly executed a generated node")


def _unused_saved_graph_uow() -> Never:
    raise AssertionError("Compiler test unexpectedly queried saved graphs")


def _compiler(
    tmp_path: Path,
    *,
    generated_releases: _GeneratedReleaseCatalog | None = None,
) -> GraphCompiler:
    registry = build_plugin_registry(builtin_plugins(), external_plugins=())
    unit_of_work = InMemoryUnitOfWork()
    workspace = tmp_path / "workbench"
    uploads_dir = workspace / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    plugin_context = PluginRuntimeContext(
        workspace=workspace,
        uploads_dir=uploads_dir,
        storage=LocalFileObjectStore(workspace / "objects"),
        uow=unit_of_work,
        bucket="test-artifacts",
    )
    saved_graphs = SavedGraphService(_unused_saved_graph_uow, registry)
    return GraphCompiler(
        plugin_registry=registry,
        plugin_context=plugin_context,
        module_catalog=GraphModuleCatalog(saved_graphs, registry),
        generated_releases=generated_releases,
        generated_executor=(
            _UnusedGeneratedExecutor() if generated_releases is not None else None
        ),
    )


def _generated_release() -> NodeRelease:
    manifest = GeneratedNodeManifest(
        title="Triple values",
        description="Multiply each integer by three.",
        inputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.INPUT,
                name="values",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.MANY,
            ),
        ),
        outputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.OUTPUT,
                name="result",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.MANY,
            ),
        ),
    )
    capabilities = CapabilityManifest()
    runtime_artifact = RuntimeArtifactReference(
        provider="docker-trusted-development",
        ref="snapshot/triple-values-v1",
        digest="8" * 64,
    )
    document = GeneratedNodeBuildDocument(
        source_digest="a" * 64,
        lock_digest="b" * 64,
        tests_digest="c" * 64,
        implementation_digest="d" * 64,
        manifest=manifest,
        capabilities=capabilities,
        runtime_image_digest="e" * 64,
        profile_digest="f" * 64,
        runtime_artifact=runtime_artifact,
    )
    return NodeRelease(
        workspace_id=WORKSPACE_ID,
        node_id=GENERATED_NODE_ID,
        revision=2,
        draft_node_id=uuid4(),
        build_attempt_id=uuid4(),
        thread_id=uuid4(),
        environment_id=uuid4(),
        manifest=manifest,
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        artifacts=BuildArtifactSet(
            source_bundle_key="generated/sources/triple-values.tar.gz",
            source_digest="a" * 64,
            lock_digest="b" * 64,
            tests_digest="c" * 64,
            build_digest=document.digest,
            implementation_digest="d" * 64,
            runtime_image_digest="e" * 64,
            profile_digest="f" * 64,
            runtime_artifact=runtime_artifact,
            tests_passed=True,
        ),
        capability_approval_id=uuid4(),
        approved_by_user_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_compiler_orders_nodes_and_resolves_declared_conversions(
    tmp_path: Path,
) -> None:
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                id="replace",
                operator_id="text.replace",
                operator_version=1,
                config={"search": "1", "replacement": "one"},
            ),
            RunNodeRequest(
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
        request,
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
async def test_compiler_derives_map_invocation_from_the_incoming_edge(
    tmp_path: Path,
) -> None:
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                id="replace",
                operator_id="text.replace",
                operator_version=1,
                config={"search": "a", "replacement": "A"},
            ),
            RunNodeRequest(
                id="split",
                operator_id="text.split",
                operator_version=1,
                config={"separator": "|"},
            ),
            RunNodeRequest(
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
        request,
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
        request,
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert compiled.pinned_outputs == {("upstream", "text"): pinned_ref}
    assert [node.request.id for node in compiled.nodes] == ["replace"]


@pytest.mark.asyncio
async def test_compiler_resolves_exact_workspace_generated_release(
    tmp_path: Path,
) -> None:
    release = _generated_release()
    catalog = _GeneratedReleaseCatalog(release)
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                id="generated",
                operator_id=release.operator_id,
                operator_version=release.operator_version,
                config={},
            )
        ],
        edges=[
            RunEdgeRequest(
                from_node="upstream",
                from_port="values",
                to_node="generated",
                to_port="values",
            )
        ],
        pinned_outputs=[
            PinnedOutputRequest(
                from_node="upstream",
                from_port="values",
                value=ArtifactRefSequence.from_key(
                    key=ArtifactTypeKey("scalar.integer", 1),
                    item_refs=[],
                ),
            )
        ],
    )

    compiled = await _compiler(
        tmp_path,
        generated_releases=catalog,
    ).compile(
        request,
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert catalog.lookups == [(WORKSPACE_ID, GENERATED_NODE_ID, 2)]
    assert isinstance(compiled.nodes[0].node, GeneratedNode)
    assert compiled.nodes[0].registration is None
    assert compiled.nodes[0].resolved_contracts.input_contract.ports[
        "values"
    ].shape is PortShape.MANY


@pytest.mark.asyncio
async def test_compiler_rejects_missing_or_malformed_generated_release(
    tmp_path: Path,
) -> None:
    missing_catalog = _GeneratedReleaseCatalog(None)
    missing = RunRequest(
        nodes=[
            RunNodeRequest(
                id="generated",
                operator_id=f"generated.node.{GENERATED_NODE_ID}",
                operator_version=7,
                config={},
            )
        ],
        edges=[],
    )
    with pytest.raises(GraphExecutionError, match="cannot be executed"):
        await _compiler(
            tmp_path,
            generated_releases=missing_catalog,
        ).compile(
            missing,
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )

    malformed = RunRequest(
        nodes=[
            RunNodeRequest(
                id="generated",
                operator_id="generated.node.not-a-uuid",
                operator_version=1,
                config={},
            )
        ],
        edges=[],
    )
    with pytest.raises(GraphExecutionError, match="invalid node UUID"):
        await _compiler(tmp_path).compile(
            malformed,
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )
