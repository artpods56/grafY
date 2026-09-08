import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal, cast, override
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    InMemoryUnitOfWork,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginRelease,
    PluginReleaseIdentity,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    PluginSecretInputContract,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.nodes import (
    InPort,
    NodeExecutionContext,
    NodeProgressReporter,
    OutPort,
    UserFacingNodeError,
    resolve_node_contracts,
)
from grafy_core.plugins import NodeCachePolicy, Plugin, PluginRegistry, PluginRuntimeContext
from grafy_core.ports.node_secrets import UnavailableNodeSecretResolver
from grafy_core.runtime.execution import NodeRunError, NodeRuntime
from grafy_core.runtime.invocation import NodeInvocation
from grafy_core.runtime.invocation_cache import InvocationCachePort
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.plugin_guest import execute_plugin_invocation
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginInvocationRequest,
    PluginInvocationResult,
    PluginReleaseNodeConfig,
    PluginReleaseNode,
)
from grafy_core.runtime.plugin_loader import PluginGuestLoaderManifest
from grafy_core.runtime.plugin_protocol import (
    PluginFailureCode,
    PluginInvocationLimits,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_workbench.text.nodes import TextValueOutputWriter, TextValueResolver
from grafy_storage import LocalFileObjectStore

from grafy_api.execution.requests import RunNodeRequest
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.models import (
    CompiledGraph,
    CompiledNode,
    GraphExecutionResult,
    PreparedGraphExecution,
)
from grafy_api.execution.node_execution import NodeExecutionService
from grafy_api.plugins.runtime.artifacts import ArtifactBundlePluginInvoker


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000972")
INPUT_ID = UUID("00000000-0000-4000-8000-000000000973")
LOADER_TARGET = (
    "tests.unit.api.runtime.test_system_adapter_parity:PARITY_PLUGIN"
)


class ParityConfig(NodeConfig):
    behavior: Literal["success", "failure", "safe_failure", "block"] = "success"


class ParityInput(NodeInput):
    text: Annotated[str, InPort(TEXT_VALUE)]


class ParityOutput(NodeOutput):
    text: Annotated[str, OutPort(TEXT_VALUE)]


PARITY_PLUGIN = Plugin(slug="test.parity", title="Adapter parity")
_calls: dict[str, int] = {}
_block_started: dict[str, asyncio.Event] = {}
_block_release: dict[str, asyncio.Event] = {}


@PARITY_PLUGIN.function_node(
    operator_id="parity.transform",
    version=1,
    title="Parity transform",
    cache_policy=NodeCachePolicy.EXACT,
)
async def parity_transform(
    context: NodeExecutionContext,
    config: ParityConfig,
    inputs: ParityInput,
) -> ParityOutput:
    node_id = context.node_id or "missing-node"
    _calls[node_id] = _calls.get(node_id, 0) + 1
    await context.progress("started", current=1, total=2)
    if config.behavior == "failure":
        raise RuntimeError("intentional parity failure")
    if config.behavior == "safe_failure":
        raise UserFacingNodeError("safe parity failure")
    if config.behavior == "block":
        _block_started.setdefault(node_id, asyncio.Event()).set()
        await _block_release.setdefault(node_id, asyncio.Event()).wait()
    await context.progress("finished", current=2, total=2)
    return ParityOutput(text=inputs.text.upper())


PARITY_PLUGIN.register_artifact_type_dependency(TEXT_VALUE)
PARITY_PLUGIN.register_resolver(
    lambda context: TextValueResolver(uow=context.uow)
)
PARITY_PLUGIN.register_writer(
    lambda context: TextValueOutputWriter(uow=context.uow)
)


class _MemoryInvocationCache(InvocationCachePort):
    def __init__(self) -> None:
        self.entries: dict[tuple[UUID, str], InvocationCacheEntry] = {}

    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> InvocationCacheEntry | None:
        return self.entries.get((workspace_id, key_sha256))

    async def put_if_absent(self, entry: InvocationCacheEntry) -> bool:
        key = (entry.workspace_id, entry.key_sha256)
        if key in self.entries:
            return False
        self.entries[key] = entry
        return True

    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        key = (workspace_id, key_sha256)
        entry = self.entries.get(key)
        if entry is None or entry.generation != generation:
            return False
        del self.entries[key]
        return True


@dataclass
class _RecordingProgress(NodeProgressReporter):
    events: list[tuple[str, int | None, int | None]] = field(default_factory=list)

    @override
    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        del context
        self.events.append((message, current, total))


class _InProcessSystemGuestRunner:
    async def run(
        self,
        invocation_root: Path,
        limits: PluginInvocationLimits,
        request: PluginInvocationRequest,
    ) -> None:
        del limits, request
        loader_manifest = PluginGuestLoaderManifest(
            slug=PARITY_PLUGIN.slug,
            loader_target=LOADER_TARGET,
        )
        manifest_path = invocation_root / "plugin-loader.json"
        manifest_path.write_bytes(loader_manifest.canonical_json_bytes())
        await execute_plugin_invocation(
            invocation_root,
            system_loader_manifest_path=manifest_path,
        )


class _ReturningInvoker:
    def __init__(self, output: ArtifactRef) -> None:
        self._output = output
        self.calls = 0

    async def invoke(
        self,
        _request: PluginInvocationRequest,
        /,
    ) -> PluginInvocationResult:
        self.calls += 1
        return PluginInvocationResult(outputs={"text": self._output})


class _FixedInputs:
    def __init__(self, ref: ArtifactRef) -> None:
        self._ref = ref

    async def assemble_inputs(
        self,
        _compiled_node: CompiledNode,
        _incoming_edges: Sequence[object],
        _outputs: Mapping[str, Mapping[str, object]],
        _workflow_run_id: UUID,
        _workspace_id: UUID,
    ) -> dict[str, object]:
        return {"text": self._ref}


class _SecretRevisions:
    def __init__(self) -> None:
        self.revision = "secret-r1"
        self.dependencies: list[Mapping[str, JsonValue]] = []

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        raise AssertionError("Cache parity test must not resolve secret plaintext")

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, graph_id, graph_revision, node_id, name
        self.dependencies.append(dict(dependencies))
        return self.revision


def _release() -> InstalledPluginRelease:
    catalog = PluginCatalogManifest.from_plugin(PARITY_PLUGIN)
    capabilities = PluginCapabilityManifest()
    runtime_artifact = PluginRuntimeArtifact(
        object_key="system/test.parity/runtime/r1.oci.tar",
        archive_digest="1" * 64,
        manifest_digest="2" * 64,
        config_digest="3" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="system/test.parity/r1.tar.gz",
        source_digest="4" * 64,
        lock_digest="5" * 64,
        runtime_profile="python-uv",
        loader_target=LOADER_TARGET,
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor="test:parity",
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
            installed_by_user_id=None,
            installed_by_platform_actor="test:parity",
        ),
    )


def _secret_release() -> InstalledPluginRelease:
    base = _release()
    contract = base.catalog.nodes[0].model_copy(
        update={
            "secret_inputs": (
                PluginSecretInputContract(
                    name="api_key",
                    title="API key",
                    config_dependencies=("secret_name",),
                ),
            ),
            "required_capabilities": (
                PluginRuntimeCapability.NODE_SECRETS,
            ),
        }
    )
    catalog = base.catalog.model_copy(update={"nodes": (contract,)})
    capabilities = PluginCapabilityManifest(
        capabilities=(PluginRuntimeCapability.NODE_SECRETS,)
    )
    release = PluginRelease(
        slug=base.slug,
        revision=base.revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=base.protocol_digest,
        profile_digest=base.profile_digest,
        source_object_key=base.release.source_object_key,
        source_digest=base.source_digest,
        lock_digest=base.lock_digest,
        runtime_profile=base.runtime_profile,
        loader_target=base.loader_target,
        runtime_image_digest=base.runtime_image_digest,
        runtime_artifact=base.runtime_artifact,
        published_by_platform_actor=base.published_by_platform_actor,
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=base.namespace,
            execution_policy=base.execution_policy,
            installed_by_user_id=None,
            installed_by_platform_actor=base.published_by_platform_actor,
        ),
    )


async def _seed_input(unit_of_work: InMemoryUnitOfWork) -> ArtifactRef:
    content = b'{"value":"parity"}'
    artifact = ArtifactObject(
        id=INPUT_ID,
        workspace_id=WORKSPACE_ID,
        artifact_type=TEXT_VALUE.key.id,
        schema_version=TEXT_VALUE.key.schema_version,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": "parity"},
        byte_size=len(content),
        sha256=sha256(content).hexdigest(),
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


def _runtime(
    unit_of_work: InMemoryUnitOfWork,
    cache: _MemoryInvocationCache,
) -> NodeRuntime:
    return NodeRuntime(
        materializer=InputMaterializer(
            ResolverRegistry([TextValueResolver(uow=unit_of_work)])
        ),
        persister=OutputPersister(
            ArtifactWriterRegistry([TextValueOutputWriter(uow=unit_of_work)])
        ),
        invocation_cache=cache,
    )


async def _artifact_for(
    unit_of_work: InMemoryUnitOfWork,
    output: PersistedNodeOutput,
) -> ArtifactObject:
    ref = output.values["text"]
    assert isinstance(ref, ArtifactRef)
    async with unit_of_work as entered:
        artifact = await entered.artifacts.get(WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    return artifact


@pytest.mark.asyncio
async def test_same_exact_system_release_has_output_progress_cache_and_provenance_parity(
    tmp_path: Path,
) -> None:
    _calls.clear()
    release = _release()
    identity = PluginReleaseIdentity.from_release(release)
    contract = release.catalog.nodes[0]

    host_uow = InMemoryUnitOfWork()
    host_input = await _seed_input(host_uow)
    registry = PluginRegistry()
    registry.install(PARITY_PLUGIN)
    host_context = PluginRuntimeContext(
        workspace=tmp_path / "host",
        uploads_dir=tmp_path / "host" / "uploads",
        storage=LocalFileObjectStore(tmp_path / "host" / "objects"),
        uow=host_uow,
        bucket="artifacts",
    )
    host_node = registry.build_node(
        contract.operator_id,
        contract.operator_version,
        host_context,
    )
    host_registration = registry.node_registration(
        contract.operator_id,
        contract.operator_version,
    )
    host_reporter = _RecordingProgress()
    host_runtime = _runtime(host_uow, _MemoryInvocationCache())

    oci_uow = InMemoryUnitOfWork()
    oci_input = await _seed_input(oci_uow)
    oci_reporter = _RecordingProgress()
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=oci_uow,
        runner=_InProcessSystemGuestRunner(),
        scratch_root=tmp_path / "oci",
    )
    oci_node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, contract, invoker)
    oci_runtime = _runtime(oci_uow, _MemoryInvocationCache())

    host_results: list[PersistedNodeOutput] = []
    oci_results: list[PersistedNodeOutput] = []
    for _ in range(2):
        host_result = await host_runtime.run_node(
            host_node,
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="success",
                progress_reporter=host_reporter,
            ),
            {"text": host_input},
            config={"behavior": "success"},
            cache_policy=host_registration.cache_policy,
            plugin_release=identity,
        )
        oci_result = await oci_runtime.run_node(
            oci_node,
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="success",
                progress_reporter=oci_reporter,
            ),
            {"text": oci_input},
            config={"behavior": "success"},
            cache_policy=oci_node.cache_policy,
            plugin_release=identity,
        )
        assert isinstance(host_result, PersistedNodeOutput)
        assert isinstance(oci_result, PersistedNodeOutput)
        host_results.append(host_result)
        oci_results.append(oci_result)

    host_artifact = await _artifact_for(host_uow, host_results[0])
    oci_artifact = await _artifact_for(oci_uow, oci_results[0])
    assert host_artifact.inline_payload == oci_artifact.inline_payload == {
        "value": "PARITY"
    }
    assert host_artifact.metadata["provenance"] == oci_artifact.metadata["provenance"]
    assert oci_artifact.metadata["plugin_release"] == identity.provenance_document()
    assert "plugin_release" not in host_artifact.metadata
    assert host_artifact.metadata["provenance"] == {
        "text": [
            {
                "artifact_id": str(INPUT_ID),
                "artifact_type": TEXT_VALUE.key.id,
                "schema_version": TEXT_VALUE.key.schema_version,
            }
        ]
    }
    assert host_reporter.events == oci_reporter.events == [
        ("started", 1, 2),
        ("finished", 2, 2),
    ]
    assert host_results[0].cache_misses == oci_results[0].cache_misses == 1
    assert host_results[1].cache_hits == oci_results[1].cache_hits == 1
    assert host_results[0].values == host_results[1].values
    assert oci_results[0].values == oci_results[1].values
    assert _calls == {"success": 2}


@pytest.mark.asyncio
async def test_same_exact_system_release_has_failure_and_cancellation_parity(
    tmp_path: Path,
) -> None:
    _calls.clear()
    _block_started.clear()
    _block_release.clear()
    release = _release()
    identity = PluginReleaseIdentity.from_release(release)
    contract = release.catalog.nodes[0]

    host_uow = InMemoryUnitOfWork()
    host_input = await _seed_input(host_uow)
    registry = PluginRegistry()
    registry.install(PARITY_PLUGIN)
    host_node = registry.build_node(
        contract.operator_id,
        contract.operator_version,
        PluginRuntimeContext(
            workspace=tmp_path / "host",
            uploads_dir=tmp_path / "host" / "uploads",
            storage=LocalFileObjectStore(tmp_path / "host" / "objects"),
            uow=host_uow,
            bucket="artifacts",
        ),
    )
    host_runtime = _runtime(host_uow, _MemoryInvocationCache())

    oci_uow = InMemoryUnitOfWork()
    oci_input = await _seed_input(oci_uow)
    oci_node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(
        release,
        contract,
        ArtifactBundlePluginInvoker(
            unit_of_work=oci_uow,
            runner=_InProcessSystemGuestRunner(),
            scratch_root=tmp_path / "oci",
        ),
    )
    oci_runtime = _runtime(oci_uow, _MemoryInvocationCache())

    host_failure_progress = _RecordingProgress()
    oci_failure_progress = _RecordingProgress()
    with pytest.raises(NodeRunError) as host_failure:
        await host_runtime.run_node(
            host_node,
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="host-failure",
                progress_reporter=host_failure_progress,
            ),
            {"text": host_input},
            config={"behavior": "failure"},
            plugin_release=identity,
        )
    assert host_failure.value.failure_code is PluginFailureCode.OPERATOR_FAILURE
    assert "intentional parity failure" not in str(host_failure.value)
    host_cause = host_failure.value.__cause__
    assert isinstance(host_cause, RuntimeError)
    assert "intentional parity failure" in str(host_cause)
    with pytest.raises(NodeRunError) as oci_failure:
        await oci_runtime.run_node(
            oci_node,
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="oci-failure",
                progress_reporter=oci_failure_progress,
            ),
            {"text": oci_input},
            config={"behavior": "failure"},
            plugin_release=identity,
        )
    assert oci_failure.value.failure_code is PluginFailureCode.OPERATOR_FAILURE
    oci_invocation_error = oci_failure.value.__cause__
    assert isinstance(oci_invocation_error, PluginInvocationError)
    assert (
        oci_invocation_error.failure_code is PluginFailureCode.OPERATOR_FAILURE
    )
    assert "intentional parity failure" not in str(oci_failure.value)
    assert host_failure_progress.events == oci_failure_progress.events == [
        ("started", 1, 2)
    ]

    host_cancel = asyncio.create_task(
        host_runtime.run_node(
            host_node,
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="host-cancel",
            ),
            {"text": host_input},
            config={"behavior": "block"},
            plugin_release=identity,
        )
    )
    oci_cancel = asyncio.create_task(
        oci_runtime.run_node(
            oci_node,
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="oci-cancel",
            ),
            {"text": oci_input},
            config={"behavior": "block"},
            plugin_release=identity,
        )
    )
    while "host-cancel" not in _block_started or "oci-cancel" not in _block_started:
        await asyncio.sleep(0)
    await _block_started["host-cancel"].wait()
    await _block_started["oci-cancel"].wait()
    host_cancel.cancel()
    oci_cancel.cancel()
    with pytest.raises(asyncio.CancelledError):
        await host_cancel
    with pytest.raises(asyncio.CancelledError):
        await oci_cancel

    async with host_uow as entered:
        host_artifacts = await entered.artifacts.list_by_type(
            WORKSPACE_ID,
            TEXT_VALUE.key,
        )
    async with oci_uow as entered:
        oci_artifacts = await entered.artifacts.list_by_type(
            WORKSPACE_ID,
            TEXT_VALUE.key,
        )
    assert [artifact.id for artifact in host_artifacts] == [INPUT_ID]
    assert [artifact.id for artifact in oci_artifacts] == [INPUT_ID]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("behavior", "safe_message"),
    [
        ("failure", None),
        ("safe_failure", "safe parity failure"),
    ],
)
async def test_same_exact_system_release_has_graph_result_failure_code_parity(
    tmp_path: Path,
    behavior: Literal["failure", "safe_failure"],
    safe_message: str | None,
) -> None:
    _calls.clear()
    release = _release()
    identity = PluginReleaseIdentity.from_release(release)
    contract = release.catalog.nodes[0]

    host_uow = InMemoryUnitOfWork()
    host_input = await _seed_input(host_uow)
    registry = PluginRegistry()
    registry.install(PARITY_PLUGIN)
    host_node = registry.build_node(
        contract.operator_id,
        contract.operator_version,
        PluginRuntimeContext(
            workspace=tmp_path / "host",
            uploads_dir=tmp_path / "host" / "uploads",
            storage=LocalFileObjectStore(tmp_path / "host" / "objects"),
            uow=host_uow,
            bucket="artifacts",
        ),
    )
    oci_uow = InMemoryUnitOfWork()
    oci_input = await _seed_input(oci_uow)
    oci_node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(
        release,
        contract,
        ArtifactBundlePluginInvoker(
            unit_of_work=oci_uow,
            runner=_InProcessSystemGuestRunner(),
            scratch_root=tmp_path / "oci",
        ),
    )

    results: list[GraphExecutionResult] = []
    for label, unit_of_work, node, input_ref in (
        ("host", host_uow, host_node, host_input),
        ("oci", oci_uow, oci_node, oci_input),
    ):
        request = RunNodeRequest(
            kind="builtin",
            id=f"{label}-failure",
            operator_id=contract.operator_id,
            operator_version=contract.operator_version,
            config={"behavior": behavior},
        )
        compiled_node = CompiledNode(
            request=request,
            node=node,
            registration=None,
            resolved_contracts=resolve_node_contracts(node, {}),
            invocation=NodeInvocation(),
            artifact_type_bindings={},
            plugin_release=identity,
        )
        execution = PreparedGraphExecution(
            plan=CompiledGraph(nodes=(compiled_node,), edges=(), pinned_outputs={}),
            initial_outputs={},
            workspace_id=WORKSPACE_ID,
            graph_id=None,
            graph_revision=None,
            secret_graph_id=None,
            secret_graph_revision=None,
            secret_node_ids=frozenset(),
            module_path=(),
            raise_node_errors=False,
        )
        coordinator = GraphExecutionCoordinator(
            node_execution=NodeExecutionService(
                runtime=_runtime(unit_of_work, _MemoryInvocationCache()),
                edge_values=cast(EdgeValueResolver, _FixedInputs(input_ref)),
                node_secrets=UnavailableNodeSecretResolver(),
            )
        )
        results.append(await coordinator.execute(execution))

    host_result, oci_result = results
    assert host_result.status == "failed"
    assert oci_result.status == "failed"
    host_node_result = host_result.node_results[0]
    oci_node_result = oci_result.node_results[0]
    assert host_node_result.status == "failed"
    assert oci_node_result.status == "failed"
    assert host_node_result.failure_code is PluginFailureCode.OPERATOR_FAILURE
    assert (
        host_node_result.failure_code == oci_node_result.failure_code
    )
    assert host_node_result.plugin_release is not None
    assert host_node_result.plugin_release is oci_node_result.plugin_release
    assert host_node_result.plugin_release == identity
    host_error = host_node_result.error
    oci_error = oci_node_result.error
    assert host_error is not None
    assert oci_error is not None
    if safe_message is None:
        assert "intentional parity failure" not in host_error
        assert "intentional parity failure" not in oci_error
    else:
        assert host_error.count(safe_message) == 1
        assert oci_error.count(safe_message) == 1
    assert "operator_failure" in host_error
    assert "operator_failure" in oci_error


class _FailingInvoker:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def invoke(
        self,
        _request: PluginInvocationRequest,
        /,
    ) -> PluginInvocationResult:
        raise self._error


@pytest.mark.asyncio
async def test_oci_invoker_failures_preserve_explicit_codes_and_default_to_internal(
    tmp_path: Path,
) -> None:
    release = _release()
    contract = release.catalog.nodes[0]
    identity = PluginReleaseIdentity.from_release(release)

    cases = [
        (
            PluginInvocationError(
                "guest output rejected",
                failure_code=PluginFailureCode.OUTPUT_VALIDATION,
            ),
            PluginFailureCode.OUTPUT_VALIDATION,
        ),
        (
            PluginInvocationError("guest adapter exploded"),
            PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
        ),
        (
            RuntimeError("raw adapter crash"),
            PluginFailureCode.INTERNAL_ADAPTER_FAILURE,
        ),
    ]
    for index, (invoker_error, expected_code) in enumerate(cases):
        unit_of_work = InMemoryUnitOfWork()
        input_ref = await _seed_input(unit_of_work)
        node: PluginReleaseNode[
            PluginReleaseNodeConfig,
            NodeInput,
            NodeOutput,
        ] = PluginReleaseNode(
            release,
            contract,
            _FailingInvoker(invoker_error),
        )
        runtime = _runtime(unit_of_work, _MemoryInvocationCache())

        with pytest.raises(NodeRunError) as raised:
            await runtime.run_node(
                node,
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id=f"code-case-{index}",
                ),
                {"text": input_ref},
                plugin_release=identity,
            )

        assert raised.value.failure_code is expected_code
        cause = raised.value.__cause__
        assert isinstance(cause, PluginInvocationError)
        assert str(invoker_error) not in str(raised.value)
        if isinstance(invoker_error, PluginInvocationError):
            assert cause is invoker_error
        else:
            assert cause.__cause__ is invoker_error


@pytest.mark.asyncio
async def test_isolated_exact_cache_keys_include_opaque_secret_revision(
    tmp_path: Path,
) -> None:
    release = _secret_release()
    contract = release.catalog.nodes[0]
    unit_of_work = InMemoryUnitOfWork()
    input_ref = await _seed_input(unit_of_work)
    invoker = _ReturningInvoker(input_ref)
    node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, contract, invoker)
    request = RunNodeRequest(
        kind="builtin",
        id="secret-node",
        operator_id=contract.operator_id,
        operator_version=contract.operator_version,
        config={"behavior": "success", "secret_name": "primary"},
    )
    compiled_node = CompiledNode(
        request=request,
        node=node,
        registration=None,
        resolved_contracts=resolve_node_contracts(node, {}),
        invocation=NodeInvocation(),
        artifact_type_bindings={},
        plugin_release=PluginReleaseIdentity.from_release(release),
    )
    plan = CompiledGraph(nodes=(compiled_node,), edges=(), pinned_outputs={})
    execution = PreparedGraphExecution(
        plan=plan,
        initial_outputs={},
        workspace_id=WORKSPACE_ID,
        graph_id=None,
        graph_revision=None,
        secret_graph_id=None,
        secret_graph_revision=None,
        secret_node_ids=frozenset({request.id}),
        module_path=(),
        raise_node_errors=True,
    )
    secrets = _SecretRevisions()
    service = NodeExecutionService(
        runtime=_runtime(unit_of_work, _MemoryInvocationCache()),
        edge_values=cast(EdgeValueResolver, _FixedInputs(input_ref)),
        node_secrets=secrets,
    )

    for _ in range(2):
        outputs = await service.execute(
            execution=execution,
            compiled_node=compiled_node,
            incoming_edges=(),
            outputs={},
            workflow_run_id=uuid4(),
            node_run_id=uuid4(),
        )
        assert outputs == {"text": input_ref}
    assert invoker.calls == 1
    assert secrets.dependencies == [
        {"secret_name": "primary"},
        {"secret_name": "primary"},
    ]

    secrets.revision = "secret-r2"
    await service.execute(
        execution=execution,
        compiled_node=compiled_node,
        incoming_edges=(),
        outputs={},
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
    )
    assert invoker.calls == 2
