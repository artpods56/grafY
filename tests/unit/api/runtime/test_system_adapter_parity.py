from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Annotated, cast
from uuid import UUID, uuid4

import pytest
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.models import (
    CompiledGraph,
    CompiledNode,
    PreparedGraphExecution,
)
from grafy_api.execution.node_execution import NodeExecutionService
from grafy_api.execution.requests import RunNodeRequest
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
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
from grafy_core.nodes import (
    InPort,
    NodeExecutionContext,
    OutPort,
    resolve_node_contracts,
)
from grafy_core.plugins import NodeCachePolicy, Plugin
from grafy_core.runtime.execution import NodeRunError, NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.invocation import NodeInvocation
from grafy_core.runtime.invocation_cache import InvocationCachePort
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    OutputPersister,
)
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginInvocationRequest,
    PluginInvocationResult,
    PluginReleaseNode,
    PluginReleaseNodeConfig,
)
from grafy_core.runtime.plugin_protocol import PluginFailureCode
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_workbench.text.nodes import TextValueOutputWriter, TextValueResolver
from pydantic import SecretStr

WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000972")
INPUT_ID = UUID("00000000-0000-4000-8000-000000000973")
LOADER_TARGET = "tests.unit.api.runtime.test_system_adapter_parity:PARITY_PLUGIN"


class ParityConfig(NodeConfig):
    secret_name: str | None = None


class ParityInput(NodeInput):
    text: Annotated[str, InPort(TEXT_VALUE)]


class ParityOutput(NodeOutput):
    text: Annotated[str, OutPort(TEXT_VALUE)]


PARITY_PLUGIN = Plugin(slug="test.parity", title="Adapter parity")


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
    del context, config
    return ParityOutput(text=inputs.text.upper())


PARITY_PLUGIN.register_artifact_type_dependency(TEXT_VALUE)
PARITY_PLUGIN.register_resolver(lambda context: TextValueResolver(uow=context.uow))
PARITY_PLUGIN.register_writer(lambda context: TextValueOutputWriter(uow=context.uow))


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
    contract = base.release.catalog.nodes[0].model_copy(
        update={
            "secret_inputs": (
                PluginSecretInputContract(
                    name="api_key",
                    title="API key",
                    config_dependencies=("secret_name",),
                ),
            ),
            "required_capabilities": (PluginRuntimeCapability.NODE_SECRETS,),
        }
    )
    catalog = base.release.catalog.model_copy(update={"nodes": (contract,)})
    capabilities = PluginCapabilityManifest(
        capabilities=(PluginRuntimeCapability.NODE_SECRETS,)
    )
    release = PluginRelease(
        slug=base.release.slug,
        revision=base.release.revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=base.release.protocol_digest,
        profile_digest=base.release.profile_digest,
        source_object_key=base.release.source_object_key,
        source_digest=base.release.source_digest,
        lock_digest=base.release.lock_digest,
        runtime_profile=base.release.runtime_profile,
        loader_target=base.release.loader_target,
        runtime_image_digest=base.release.runtime_image_digest,
        runtime_artifact=base.release.runtime_artifact,
        published_by_platform_actor=base.release.published_by_platform_actor,
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=base.installation.namespace,
            execution_policy=base.installation.execution_policy,
            installed_by_user_id=None,
            installed_by_platform_actor=base.release.published_by_platform_actor,
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
    contract = release.release.catalog.nodes[0]
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
    contract = release.release.catalog.nodes[0]
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
        config={"secret_name": "primary"},
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
