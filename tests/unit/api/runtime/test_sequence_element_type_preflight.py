"""Pre-dispatch artifact type checks for sequence element types (issue #84).

Production case: ``llm.openai_compatible.chat_completion@1`` declares its
required ``messages`` port as ``prompt.message@2``, while the graph fed it from a
``sequence.collect`` bound to ``scalar.text@1``. The mismatch reached the Plugin
guest and came back as a generic ``contract_failure`` after a container round
trip. These tests pin the host-side behaviour: compiling the run names the port
and both artifact types, and the Plugin invoker -- the seam that owns the
sandbox container -- is never reached.
"""

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Never
from uuid import UUID, uuid4

import pytest
from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.errors import ArtifactTypeMismatchError
from grafy_api.execution.materializations import MaterializationService
from grafy_api.execution.models import (
    CompiledGraph,
    GraphExecutionResult,
    PreparedGraphExecution,
)
from grafy_api.execution.node_execution import NodeExecutionService
from grafy_api.execution.preflight import GraphRunPreflight
from grafy_api.execution.requests import (
    RunEdgeRequest,
    RunInputPlugRequest,
    RunNodeRequest,
    RunOriginRequest,
    RunRequest,
)
from grafy_api.execution.run_graph import RunGraph
from grafy_api.plugins.runtime.admission import ReleaseExecutionAdmission
from grafy_api.v1.models import (
    ArtifactTypeBindingModel,
    ArtifactTypeKeyResponse,
    PluginReleasePinModel,
)
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
)
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
from grafy_core.domain.modules import GraphModuleDefinition
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginPortContract,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.plugins import PluginRuntimeContext
from grafy_core.ports.modules import GraphModuleExecutionResult
from grafy_core.ports.node_secrets import UnavailableNodeSecretResolver
from grafy_core.prompt_contracts import PROMPT_MESSAGE
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.invocation import InvocationMode
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import ArtifactWriterRegistry, OutputPersister
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationRequest,
    PluginInvocationResult,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_storage import LocalFileObjectStore

from tests.support.system_plugins import (
    TEST_BUILD_DIGEST,
    build_explicit_plugin_registry,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000884")
LLM_SLUG = "external.llm"
CHAT_COMPLETION = "llm.openai_compatible.chat_completion"
TEXT_KEY = ArtifactTypeKey("scalar.text", 1)
PROMPT_MESSAGE_KEY = ArtifactTypeKey("prompt.message", 2)
TEXT_V2 = ArtifactTypeSpec(
    key=ArtifactTypeKey("scalar.text", 2),
    title="Text value v2",
    bundle=TEXT_VALUE.bundle,
)
_ADMISSION = ReleaseExecutionAdmission(
    isolated_adapter_available=True,
    runtime_profile="python-uv",
)


class RecordingPluginInvoker:
    """Stands in for the Plugin invoker that owns the sandbox container."""

    def __init__(self) -> None:
        self.requests: list[PluginInvocationRequest] = []

    async def invoke(
        self,
        request: PluginInvocationRequest,
        /,
    ) -> PluginInvocationResult:
        self.requests.append(request)
        return PluginInvocationResult(outputs={})


class RecordingCoordinator(GraphExecutionCoordinator):
    """Records dispatch so a rejected run can be proven never to have started."""

    def __init__(self, *, node_execution: NodeExecutionService) -> None:
        super().__init__(node_execution=node_execution)
        self.executed: list[PreparedGraphExecution] = []

    async def execute(
        self,
        execution: PreparedGraphExecution,
    ) -> GraphExecutionResult:
        self.executed.append(execution)
        return await super().execute(execution)


class ReleaseLookup:
    def __init__(self, *releases: InstalledPluginRelease) -> None:
        self._releases = releases

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None:
        expected_owner = workspace_id if scope is PluginReleaseScope.WORKSPACE else None
        for release in self._releases:
            if (
                release.installation.scope is scope
                and release.installation.workspace_id == expected_owner
                and release.release.slug == slug
                and release.release.revision == revision
            ):
                return release
        return None

    async def get_selection(
        self,
        workspace_id: UUID,
        slug: str,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> None:
        del workspace_id, slug, scope
        return None

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> None:
        del workspace_id, slug, revision
        return None

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> None:
        del slug, revision
        return None


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


def _chat_release(messages_accepts: ArtifactTypeSpec) -> InstalledPluginRelease:
    """A release whose single node mirrors the production `messages` port."""

    messages = PluginPortContract(
        name="messages",
        title="Messages",
        direction="input",
        artifact_type=PluginArtifactTypeKey(
            id=messages_accepts.key.id,
            schema_version=messages_accepts.key.schema_version,
        ),
        shape=PortShape.MANY,
        accepted_shapes=(PortShape.MANY,),
    )
    completion = PluginPortContract(
        name="completion",
        title="Completion",
        direction="output",
        artifact_type=PluginArtifactTypeKey(
            id=TEXT_KEY.id,
            schema_version=TEXT_KEY.schema_version,
        ),
        shape=PortShape.ONE,
        accepted_shapes=(PortShape.ONE,),
    )
    node = PluginNodeContract(
        operator_id=CHAT_COMPLETION,
        operator_version=1,
        title="Chat completion",
        description="Mirrors the production chat completion contract.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(messages,),
        outputs=(completion,),
    )
    # A plugin owns an artifact type it declares; PROMPT_MESSAGE stays a host
    # dependency the way the shipped llm Plugin declares it. Its payload
    # references image.raster@1, so that type is a dependency too.
    owns_accepted_type = messages_accepts is not PROMPT_MESSAGE
    dependency_specs: list[ArtifactTypeSpec] = [TEXT_VALUE]
    if not owns_accepted_type:
        dependency_specs = [TEXT_VALUE, messages_accepts, RASTER_IMAGE]
    catalog = PluginCatalogManifest(
        slug=LLM_SLUG,
        title="LLM",
        artifact_types=(
            (PluginArtifactTypeContract.from_spec(messages_accepts),)
            if owns_accepted_type
            else ()
        ),
        artifact_type_dependencies=tuple(
            PluginArtifactTypeContract.from_spec(spec) for spec in dependency_specs
        ),
        nodes=(node,),
    )
    capabilities = PluginCapabilityManifest()
    runtime_artifact = PluginRuntimeArtifact(
        object_key="plugin-releases/llm/runtime/r1.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
    )
    release = PluginRelease(
        slug=LLM_SLUG,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/llm/r1.tar.gz",
        source_digest="1" * 64,
        lock_digest="9" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_user_id=WORKSPACE_ID,
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=WORKSPACE_ID,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=WORKSPACE_ID,
            installed_by_platform_actor=None,
        ),
    )


def _context(tmp_path: Path) -> PluginRuntimeContext:
    workspace = tmp_path / "workbench"
    (workspace / "uploads").mkdir(parents=True, exist_ok=True)
    return PluginRuntimeContext(
        workspace=workspace,
        storage=LocalFileObjectStore(workspace / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="test-artifacts",
    )


def _compiler(
    context: PluginRuntimeContext,
    lookup: ReleaseLookup,
    invoker: RecordingPluginInvoker,
) -> GraphCompiler:
    registry = build_explicit_plugin_registry()
    return GraphCompiler(
        plugin_registry=registry,
        plugin_context=context,
        module_library=ModuleLibraryService(_unused_saved_graph_uow, registry),
        canonical_artifact_conversions=CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
        plugin_release_lookup=lookup,
        plugin_invoker=invoker,
        release_admission=_ADMISSION,
        build_digest=TEST_BUILD_DIGEST,
    )


async def _seed_scalar_text_origin(unit_of_work: InMemoryUnitOfWork) -> ArtifactRef:
    """Persist one scalar.text@1 artifact so an origin resolves on dispatch."""

    payload: JsonObject = {"value": "collected"}
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=TEXT_KEY.id,
        schema_version=TEXT_KEY.schema_version,
        content_type="application/json",
        storage_backend="inline",
        inline_payload=payload,
        byte_size=len(content),
        sha256=sha256(content).hexdigest(),
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


def _pipeline(
    context: PluginRuntimeContext,
    lookup: ReleaseLookup,
    invoker: RecordingPluginInvoker,
) -> tuple[RunGraph, RecordingCoordinator]:
    """The full run pipeline, with the sandbox-owning invoker replaced by a spy."""

    registry = build_explicit_plugin_registry()
    resolvers = ResolverRegistry()
    writers = ArtifactWriterRegistry([])
    coordinator = RecordingCoordinator(
        node_execution=NodeExecutionService(
            runtime=NodeRuntime(
                materializer=InputMaterializer(resolvers),
                persister=OutputPersister(writers),
            ),
            edge_values=EdgeValueResolver(
                resolvers=resolvers,
                writers=writers,
                unit_of_work=context.uow,
            ),
            node_secrets=UnavailableNodeSecretResolver(),
        )
    )
    return (
        RunGraph(
            preflight=GraphRunPreflight(
                plugin_registry=registry,
                saved_graphs=None,
                plugin_release_lookup=lookup,
            ),
            compiler=_compiler(context, lookup, invoker),
            coordinator=coordinator,
            materializations=MaterializationService(
                context.uow,
                ArtifactAvailability(context.uow, context.storage),
                None,
            ),
        ),
        coordinator,
    )


def _ref(key: ArtifactTypeKey) -> ArtifactRef:
    return ArtifactRef.from_key(artifact_id=uuid4(), key=key)


def _sequence_to_chat(origin: ArtifactRef) -> RunRequest:
    """A sequence of the origin's artifact type feeding the `messages` port."""

    element = origin.key()
    return RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="collect",
                operator_id="test.sequence.collect",
                operator_version=1,
                input_plugs=[RunInputPlugRequest(id="item", port="items")],
                artifact_type_bindings=[
                    ArtifactTypeBindingModel(
                        variable="T",
                        artifact_type=ArtifactTypeKeyResponse(
                            id=element.id,
                            schema_version=element.schema_version,
                        ),
                    )
                ],
            ),
            RunNodeRequest(
                kind="plugin",
                id="chat",
                operator_id=CHAT_COMPLETION,
                operator_version=1,
                config={},
                plugin_release=PluginReleasePinModel(
                    scope=PluginReleaseScope.WORKSPACE,
                    slug=LLM_SLUG,
                    revision=1,
                ),
            ),
        ],
        edges=[
            RunEdgeRequest(
                from_node="collect",
                from_port="items",
                to_node="chat",
                to_port="messages",
            )
        ],
        origins=[
            RunOriginRequest(
                to_node="collect",
                to_port="items",
                to_plug="item",
                value=origin,
            )
        ],
    )


@pytest.mark.asyncio
async def test_run_rejects_mismatched_sequence_element_type_before_dispatch(
    tmp_path: Path,
) -> None:
    """The production shape fails at compile time and never reaches the sandbox."""

    invoker = RecordingPluginInvoker()
    lookup = ReleaseLookup(_chat_release(PROMPT_MESSAGE))
    context = _context(tmp_path)
    runner, coordinator = _pipeline(context, lookup, invoker)
    origin = await _seed_scalar_text_origin(context.uow)

    with pytest.raises(ArtifactTypeMismatchError) as mismatch:
        await runner.run(WORKSPACE_ID, _sequence_to_chat(origin))

    assert mismatch.value.node_id == "chat"
    assert mismatch.value.port == "messages"
    assert mismatch.value.expected == (PROMPT_MESSAGE_KEY,)
    assert mismatch.value.received == TEXT_KEY
    rendered = str(mismatch.value)
    assert "'chat'.'messages'" in rendered
    assert "prompt.message@2" in rendered
    assert "scalar.text@1" in rendered
    assert invoker.requests == []
    assert coordinator.executed == []


@pytest.mark.asyncio
async def test_compile_rejects_sequence_element_schema_version_drift(
    tmp_path: Path,
) -> None:
    """A matching artifact type id at another schema version is still a mismatch."""

    invoker = RecordingPluginInvoker()
    lookup = ReleaseLookup(_chat_release(TEXT_V2))
    compiler = _compiler(_context(tmp_path), lookup, invoker)

    with pytest.raises(ArtifactTypeMismatchError) as mismatch:
        await compiler.compile(
            _sequence_to_chat(_ref(TEXT_KEY)),
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )

    assert mismatch.value.port == "messages"
    assert mismatch.value.expected == (ArtifactTypeKey("scalar.text", 2),)
    assert mismatch.value.received == TEXT_KEY
    assert invoker.requests == []


@pytest.mark.asyncio
async def test_compile_accepts_a_sequence_whose_element_type_matches_the_port(
    tmp_path: Path,
) -> None:
    """The same shape with the declared element type compiles and dispatches."""

    invoker = RecordingPluginInvoker()
    lookup = ReleaseLookup(_chat_release(PROMPT_MESSAGE))
    compiler = _compiler(_context(tmp_path), lookup, invoker)

    plan: CompiledGraph = await compiler.compile(
        _sequence_to_chat(_ref(PROMPT_MESSAGE_KEY)),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert [node.request.id for node in plan.nodes] == ["collect", "chat"]
    assert plan.nodes[1].invocation.mode is InvocationMode.ONCE
    assert [
        edge.request for edge in plan.edges if isinstance(edge.request, RunEdgeRequest)
    ] == [
        RunEdgeRequest(
            from_node="collect",
            from_port="items",
            to_node="chat",
            to_port="messages",
        )
    ]
