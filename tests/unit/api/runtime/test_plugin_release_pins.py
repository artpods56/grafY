"""Compiler contracts for exact Workspace Plugin release pins."""

from collections.abc import Mapping
from pathlib import Path
from typing import Never, cast
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.artifacts import ArtifactFieldProjection, ArtifactRef, ArtifactTypeKey
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
from grafy_core.domain.modules import (
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
    GraphModuleDefinition,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginFieldProjection,
    PluginNodeContract,
    PluginPortContract,
    PluginPortDirection,
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
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_selection import (
    PluginFamilyLifecycle,
    PluginReleaseSelection,
)
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationReason,
)
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_workbench.text import TEXT as TEXT_PLUGIN
from grafy_workbench.text.nodes import TextValueOutputWriter, TextValueResolver
from grafy_core.plugins import PluginRuntimeContext
from grafy_core.ports.node_secrets import UnavailableNodeSecretResolver
from grafy_core.ports.modules import GraphModuleExecutionResult
from grafy_core.runtime.invocation import InvocationMode
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import ArtifactWriterRegistry, OutputPersister
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationRequest,
    PluginInvocationResult,
    PluginReleaseNode,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_storage import LocalFileObjectStore

from grafy_api.plugins.runtime.admission import (
    PluginNonRunnableReason,
    ReleaseExecutionAdmission,
    ReleaseExecutionRejection,
    ReleaseExecutionRoute,
)
from grafy_api.system_host_bindings import (
    SystemHostBindingError,
    validate_system_host_bindings,
)
from grafy_core.domain.plugin_host_bindings import (
    LoadedSystemPlugin,
    SystemHostPluginBinding,
)
from tests.support.system_plugins import build_explicit_plugin_registry
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.execution.requests import (
    FieldProjectionRequest,
    RunEdgeRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_core.application.modules import ModuleLibraryService
from grafy_api.v1.models import PluginReleasePinModel
from grafy_api.execution.preflight import GraphRunPreflight
from grafy_api.execution.run_graph import RunGraph
from grafy_api.execution.materializations import MaterializationService
from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.models import PreparedGraphExecution
from grafy_api.execution.node_execution import NodeExecutionService


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000871")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000872")
TEXT = PluginArtifactTypeKey(id="scalar.text", schema_version=1)
HOST_LOADER_TARGET = "grafy_workbench.text.plugin:TEXT"
HOST_BUILD_DIGEST = "f" * 64
_RELEASE_ADMISSION = ReleaseExecutionAdmission(
    isolated_adapter_available=True,
    runtime_profile="python-uv",
)


def _text_port(
    name: str,
    direction: PluginPortDirection,
) -> PluginPortContract:
    return PluginPortContract(
        name=name,
        title=name.title(),
        direction=direction,
        artifact_type=TEXT,
        shape=PortShape.ONE,
        accepted_shapes=(PortShape.ONE,),
    )


def _echo_contract(operator_version: int = 1) -> PluginNodeContract:
    return PluginNodeContract(
        operator_id="notes.echo",
        operator_version=operator_version,
        title="Echo",
        description="Echoes one text reference.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(_text_port("text", "input"),),
        outputs=(_text_port("text", "output"),),
    )


def _release(
    revision: int,
    nodes: tuple[PluginNodeContract, ...] = (_echo_contract(),),
    *,
    workspace_id: UUID = WORKSPACE_ID,
    scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    executable: bool = True,
    declared_capabilities: tuple[PluginRuntimeCapability, ...] = (),
    execution_policy: PluginExecutionPolicy = PluginExecutionPolicy.ISOLATED_ONLY,
    artifact_types: tuple[PluginArtifactTypeContract, ...] = (),
    artifact_type_dependencies: tuple[PluginArtifactTypeContract, ...] | None = None,
) -> InstalledPluginRelease:
    dependencies = artifact_type_dependencies
    if dependencies is None:
        dependencies = tuple(
            PluginArtifactTypeContract.from_spec(spec)
            for spec in TEXT_PLUGIN.artifact_types
        )
    catalog = PluginCatalogManifest(
        slug="notes",
        title="Notes",
        artifact_types=artifact_types,
        artifact_type_dependencies=dependencies,
        nodes=nodes,
    )
    capabilities = PluginCapabilityManifest(capabilities=declared_capabilities)
    runtime_artifact = (
        PluginRuntimeArtifact(
            object_key=f"plugin-releases/notes/runtime/r{revision}.oci.tar",
            archive_digest="a" * 64,
            manifest_digest="b" * 64,
            config_digest="c" * 64,
        )
        if executable
        else None
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/notes/r{revision}.tar.gz",
        source_digest=f"{revision}" * 64,
        lock_digest="9" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=(
            runtime_artifact.manifest_digest if runtime_artifact is not None else None
        ),
        runtime_artifact=runtime_artifact,
        published_by_user_id=(
            workspace_id if scope is PluginReleaseScope.WORKSPACE else None
        ),
        published_by_platform_actor=(
            "test:system" if scope is PluginReleaseScope.SYSTEM else None
        ),
    )
    installation = PluginInstallation.from_release(
        release,
        namespace=PluginReleaseNamespace(
            scope=scope,
            workspace_id=(
                workspace_id if scope is PluginReleaseScope.WORKSPACE else None
            ),
        ),
        execution_policy=execution_policy,
        installed_by_user_id=(
            workspace_id if scope is PluginReleaseScope.WORKSPACE else None
        ),
        installed_by_platform_actor=(
            "test:system" if scope is PluginReleaseScope.SYSTEM else None
        ),
    )
    return InstalledPluginRelease(release=release, installation=installation)


def _host_text_release(revision: int) -> InstalledPluginRelease:
    catalog = PluginCatalogManifest.from_plugin(TEXT_PLUGIN)
    capabilities = PluginCapabilityManifest()
    runtime_artifact = PluginRuntimeArtifact(
        object_key=f"plugin-releases/system/builtin.text/runtime/r{revision}.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/system/builtin.text/r{revision}.tar.gz",
        source_digest=f"{revision}" * 64,
        lock_digest="9" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_workbench.text.plugin:TEXT",
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor="test:system",
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
            installed_by_platform_actor="test:system",
        ),
    )


class RecordingReleaseLookup:
    def __init__(
        self,
        *releases: InstalledPluginRelease,
        selection: PluginReleaseSelection | None = None,
        revocation: PluginReleaseRevocation | None = None,
    ) -> None:
        self._releases = releases
        self._selection = selection
        self._revocation = revocation
        self.release_reads = 0
        self.selection_reads = 0
        self.revocation_reads = 0

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None:
        self.release_reads += 1
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
    ) -> PluginReleaseSelection | None:
        self.selection_reads += 1
        del workspace_id
        selection = self._selection
        if selection is None:
            return None
        if selection.scope is scope and selection.slug == slug:
            return selection
        return None

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        self.revocation_reads += 1
        revocation = self._revocation
        if revocation is None:
            return None
        if (
            revocation.scope is PluginReleaseScope.WORKSPACE
            and revocation.workspace_id == workspace_id
            and revocation.slug == slug
            and revocation.revision == revision
        ):
            return revocation
        return None

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        self.revocation_reads += 1
        revocation = self._revocation
        if revocation is None:
            return None
        if (
            revocation.scope is PluginReleaseScope.SYSTEM
            and revocation.slug == slug
            and revocation.revision == revision
        ):
            return revocation
        return None


class NoopInvoker:
    def __init__(self) -> None:
        self.requests: list[PluginInvocationRequest] = []

    async def invoke(
        self,
        request: PluginInvocationRequest,
        /,
    ) -> PluginInvocationResult:
        self.requests.append(request)
        return PluginInvocationResult(outputs={})


class _UnusedModuleExecutor:
    async def execute_module(
        self,
        _definition: GraphModuleDefinition,
        _context: NodeExecutionContext,
        _inputs: Mapping[str, object],
        /,
    ) -> GraphModuleExecutionResult:
        raise AssertionError("Compiler test unexpectedly executed a graph module")


def _unused_saved_graph_uow() -> Never:
    raise AssertionError("Compiler test unexpectedly queried saved graphs")


def _compiler(
    lookup: RecordingReleaseLookup | None = None,
    invoker: NoopInvoker | None = None,
    admission: ReleaseExecutionAdmission = _RELEASE_ADMISSION,
) -> GraphCompiler:
    registry = build_explicit_plugin_registry()
    unit_of_work = InMemoryUnitOfWork()
    workbench = Path("/tmp/grafy-plugin-pin-tests")
    uploads_dir = workbench / "uploads"
    plugin_context = PluginRuntimeContext(
        workspace=workbench,
        uploads_dir=uploads_dir,
        storage=LocalFileObjectStore(workbench / "objects"),
        uow=unit_of_work,
        bucket="test-artifacts",
    )
    return GraphCompiler(
        plugin_registry=registry,
        plugin_context=plugin_context,
        module_library=ModuleLibraryService(_unused_saved_graph_uow, registry),
        canonical_artifact_conversions=CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
        plugin_release_lookup=lookup or RecordingReleaseLookup(),
        plugin_invoker=invoker or NoopInvoker(),
        release_admission=admission,
        build_digest="a" * 64,
    )


def _pinned_node(
    node_id: str,
    pin: PluginReleasePinModel | None,
    *,
    operator_id: str = "notes.echo",
) -> RunNodeRequest:
    return RunNodeRequest(
        kind="plugin" if pin is not None else "builtin",
        id=node_id,
        operator_id=operator_id,
        operator_version=1,
        config={"scale": 2},
        plugin_release=pin,
    )


def _echo_run_request(
    pin_revision: int,
) -> RunRequest:
    """One pinned echo node fed by a pinned upstream output edge."""
    from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
    from grafy_api.execution.requests import (
        PinnedOutputRequest,
        RunEdgeRequest,
    )

    return RunRequest(
        nodes=[
            _pinned_node(
                "echo",
                PluginReleasePinModel(
                    scope=PluginReleaseScope.WORKSPACE,
                    slug="notes",
                    revision=pin_revision,
                ),
            )
        ],
        edges=[
            RunEdgeRequest(
                from_node="upstream",
                from_port="text",
                to_node="echo",
                to_port="text",
            )
        ],
        pinned_outputs=[
            PinnedOutputRequest(
                from_node="upstream",
                from_port="text",
                value=ArtifactRef.from_key(
                    artifact_id=uuid4(),
                    key=ArtifactTypeKey(TEXT.id, TEXT.schema_version),
                ),
            )
        ],
    )


def _system_text_run_request(_revision: int = 1) -> RunRequest:
    return RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="input",
                operator_id="text.input",
                operator_version=1,
                config={"text": "bound host implementation"},
            )
        ]
    )


@pytest.mark.asyncio
async def test_compile_imports_no_plugin_source_modules() -> None:
    """Compilation resolves persisted contracts only; Plugin Python never loads."""
    import sys

    modules_before = frozenset(sys.modules)

    compiled = await _compiler(
        RecordingReleaseLookup(_release(1)),
        NoopInvoker(),
    ).compile(
        _echo_run_request(pin_revision=1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert isinstance(compiled.nodes[0].node, PluginReleaseNode)
    new_module_names = [name for name in sys.modules if name not in modules_before]
    assert [name for name in new_module_names if name.startswith("grafy_plugin")] == []


@pytest.mark.asyncio
async def test_graph_pinned_to_revision_one_stays_on_it_after_two_is_published() -> (
    None
):
    lookup = RecordingReleaseLookup(_release(1), _release(2))

    compiled = await _compiler(lookup).compile(
        _echo_run_request(pin_revision=1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    pinned = compiled.nodes[0]
    assert isinstance(pinned.node, PluginReleaseNode)
    assert pinned.node is not None
    assert pinned.node.release.release.revision == 1
    assert pinned.registration is None
    assert pinned.plugin_release is not None
    assert pinned.plugin_release.slug == "notes"
    assert pinned.plugin_release.revision == 1
    assert pinned.plugin_release.source_digest == "1" * 64


@pytest.mark.asyncio
async def test_same_operator_in_two_releases_compiles_to_distinct_identities() -> None:
    first = _release(1)
    second = _release(2)

    compiled_first = await _compiler(RecordingReleaseLookup(first, second)).compile(
        _echo_run_request(pin_revision=1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )
    compiled_second = await _compiler(RecordingReleaseLookup(first, second)).compile(
        _echo_run_request(pin_revision=2),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    identity_first = compiled_first.nodes[0].plugin_release
    identity_second = compiled_second.nodes[0].plugin_release
    assert identity_first is not None and identity_second is not None
    assert identity_first != identity_second
    assert identity_first.revision == 1
    assert identity_second.revision == 2
    assert (
        identity_first.fingerprint_document() != identity_second.fingerprint_document()
    )


@pytest.mark.asyncio
async def test_same_slug_and_revision_resolve_independently_by_release_scope() -> None:
    workspace_release = _release(1)
    system_release = _release(1, scope=PluginReleaseScope.SYSTEM)
    compiler = _compiler(
        RecordingReleaseLookup(workspace_release, system_release),
        NoopInvoker(),
    )

    workspace_graph = await compiler.compile(
        _echo_run_request(pin_revision=1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )
    system_request = _echo_run_request(pin_revision=1)
    system_graph = await compiler.compile(
        system_request.model_copy(
            update={
                "nodes": [
                    system_request.nodes[0].model_copy(
                        update={
                            "plugin_release": PluginReleasePinModel(
                                scope=PluginReleaseScope.SYSTEM,
                                slug="notes",
                                revision=1,
                            )
                        }
                    )
                ]
            }
        ),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    workspace_identity = workspace_graph.nodes[0].plugin_release
    system_identity = system_graph.nodes[0].plugin_release
    assert workspace_identity is not None
    assert workspace_identity.scope is PluginReleaseScope.WORKSPACE
    assert system_identity is not None
    assert system_identity.scope is PluginReleaseScope.SYSTEM
    assert system_identity.workspace_id is None


@pytest.mark.asyncio
async def test_exact_selected_system_release_runs_through_bound_host() -> None:
    release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(release)
    binding = SystemHostPluginBinding.from_release(
        release,
        selection_generation=selection.generation,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )
    compiled = await _compiler(
        RecordingReleaseLookup(release, selection=selection),
        admission=ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
            system_host_bindings=(binding,),
        ),
    ).compile(
        _system_text_run_request(1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    node = compiled.nodes[0]
    assert not isinstance(node.node, PluginReleaseNode)
    assert node.registration is not None
    assert node.registration.plugin_slug == "text"
    assert node.plugin_release is None


@pytest.mark.asyncio
async def test_revoked_selected_system_release_cannot_use_bound_host() -> None:
    release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(release)
    revocation = PluginReleaseRevocation.from_release(
        release,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_platform_actor="test:system",
    )
    binding = SystemHostPluginBinding.from_release(
        release,
        selection_generation=selection.generation,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )

    compiled = await _compiler(
        RecordingReleaseLookup(
            release,
            selection=selection,
            revocation=revocation,
        ),
        admission=ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
            system_host_bindings=(binding,),
        ),
    ).compile(
        _system_text_run_request(1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    node = compiled.nodes[0]
    assert not isinstance(node.node, PluginReleaseNode)
    assert node.plugin_release is None


@pytest.mark.asyncio
async def test_historical_system_release_overlapping_host_runs_isolated() -> None:
    historical = _host_text_release(1)
    selected = _host_text_release(2)
    selection = PluginReleaseSelection.from_release(selected)
    binding = SystemHostPluginBinding.from_release(
        selected,
        selection_generation=selection.generation,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )
    compiled = await _compiler(
        RecordingReleaseLookup(historical, selected, selection=selection),
        admission=ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
            system_host_bindings=(binding,),
        ),
    ).compile(
        _system_text_run_request(1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    node = compiled.nodes[0]
    assert not isinstance(node.node, PluginReleaseNode)
    assert node.registration is not None
    assert node.plugin_release is None


@pytest.mark.asyncio
async def test_exact_release_contract_comparison_uses_declared_artifact_contracts() -> (
    None
):
    release = _release(
        1,
        artifact_type_dependencies=tuple(
            PluginArtifactTypeContract.from_spec(spec)
            for spec in TEXT_PLUGIN.artifact_types
        ),
    )

    compiled = await _compiler(RecordingReleaseLookup(release)).compile(
        _echo_run_request(pin_revision=1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert compiled.nodes[0].plugin_release == PluginReleaseIdentity.from_release(
        release
    )


@pytest.mark.asyncio
async def test_isolated_exact_release_supplies_its_own_projectable_artifact_contract() -> (
    None
):
    unique_key = PluginArtifactTypeKey(id="historical.document", schema_version=1)
    unique_artifact = PluginArtifactTypeContract(
        key=unique_key,
        title="Historical document",
        payload_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        field_projections=(
            PluginFieldProjection(path=("text",), target=TEXT, title="Text"),
        ),
    )
    producer = PluginNodeContract(
        operator_id="notes.historical_document",
        operator_version=1,
        title="Historical document",
        description="Produces an artifact declared only by this release.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(),
        outputs=(
            PluginPortContract(
                name="document",
                title="Document",
                direction="output",
                artifact_type=unique_key,
                shape=PortShape.ONE,
                accepted_shapes=(PortShape.ONE,),
            ),
        ),
    )
    release = _release(
        1,
        nodes=(producer, _echo_contract()),
        scope=PluginReleaseScope.SYSTEM,
        artifact_types=(unique_artifact,),
        artifact_type_dependencies=(
            PluginArtifactTypeContract.from_spec(
                next(
                    spec
                    for spec in TEXT_PLUGIN.artifact_types
                    if spec.key.id == TEXT.id
                )
            ),
        ),
    )
    pin = PluginReleasePinModel(
        scope=PluginReleaseScope.SYSTEM,
        slug=release.release.slug,
        revision=release.release.revision,
    )

    compiled = await _compiler(RecordingReleaseLookup(release)).compile(
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="plugin",
                    id="producer",
                    operator_id=producer.operator_id,
                    operator_version=producer.operator_version,
                    plugin_release=pin,
                ),
                _pinned_node("consumer", pin),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="producer",
                    from_port="document",
                    to_node="consumer",
                    to_port="text",
                    projection=FieldProjectionRequest(path=["text"]),
                )
            ],
        ),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert all(node.registration is None for node in compiled.nodes)
    assert compiled.edges[0].projection == ArtifactFieldProjection(
        path=("text",),
        target=ArtifactTypeKey("scalar.text", 1),
        title="Text",
    )


@pytest.mark.asyncio
async def test_selected_host_binding_digest_mismatch_fails_closed() -> None:
    release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(release)
    binding = SystemHostPluginBinding.from_release(
        release,
        selection_generation=selection.generation,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    ).model_copy(update={"runtime_archive_digest": "d" * 64})

    compiled = await _compiler(
        RecordingReleaseLookup(release, selection=selection),
        admission=ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
            system_host_bindings=(binding,),
        ),
    ).compile(
        _system_text_run_request(1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert compiled.nodes[0].plugin_release is None


@pytest.mark.asyncio
async def test_selected_host_binding_generation_mismatch_fails_closed() -> None:
    release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(release)
    binding = SystemHostPluginBinding.from_release(
        release,
        selection_generation=selection.generation + 1,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )

    compiled = await _compiler(
        RecordingReleaseLookup(release, selection=selection),
        admission=ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
            system_host_bindings=(binding,),
        ),
    ).compile(
        _system_text_run_request(1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert compiled.nodes[0].plugin_release is None


def test_isolated_only_and_workspace_releases_never_select_host_route() -> None:
    host_release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(host_release)
    binding = SystemHostPluginBinding.from_release(
        host_release,
        selection_generation=selection.generation,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )
    admission = ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile="python-uv",
        system_host_bindings=(binding,),
    )
    isolated_system = _release(1, scope=PluginReleaseScope.SYSTEM)
    isolated_selection = PluginReleaseSelection.from_release(isolated_system)
    workspace = _release(1)

    assert (
        admission.decide(isolated_system, selection=isolated_selection)
        is ReleaseExecutionRoute.ISOLATED
    )
    assert admission.decide(workspace) is ReleaseExecutionRoute.ISOLATED


def test_non_published_system_selection_never_selects_host_route() -> None:
    release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(release)
    selection.lifecycle = PluginFamilyLifecycle.DEPRECATED
    binding = SystemHostPluginBinding.from_release(
        release,
        selection_generation=selection.generation,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )

    assert (
        ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
            system_host_bindings=(binding,),
        ).decide(release, selection=selection)
        is ReleaseExecutionRoute.ISOLATED
    )


def test_admission_requires_an_exact_artifact_bundle_adapter() -> None:
    decision = ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile="python-uv",
        supported_bundle_adapters=frozenset({("table-bundle", 1)}),
    ).decide(_release(1))

    assert isinstance(decision, ReleaseExecutionRejection)
    assert decision.reason == "unsupported_artifact_type"
    assert "inline-json@1" in decision.detail


def test_admission_enables_only_wired_bundle_adapters_by_default() -> None:
    assert _RELEASE_ADMISSION.supported_bundle_adapters == frozenset(
        {
            ("binary-file", 1),
            ("inline-json", 1),
            ("object-set", 1),
            ("table-bundle", 1),
        }
    )


def test_admission_uses_the_selected_node_capability_profile() -> None:
    artifact_query = _echo_contract().model_copy(
        update={
            "operator_id": "sql.artifacts.query",
            "required_capabilities": (PluginRuntimeCapability.UNTRUSTED_SQL,),
        }
    )
    postgresql = _echo_contract().model_copy(
        update={
            "operator_id": "sql.postgresql.execute",
            "secret_inputs": (
                PluginSecretInputContract(
                    name="database_url",
                    title="Database URL",
                    config_dependencies=("secret_name",),
                ),
            ),
            "required_capabilities": (
                PluginRuntimeCapability.NODE_SECRETS,
                PluginRuntimeCapability.POSTGRESQL_EGRESS,
                PluginRuntimeCapability.UNTRUSTED_SQL,
            ),
        }
    )
    release = _release(
        1,
        nodes=(artifact_query, postgresql),
        declared_capabilities=(
            PluginRuntimeCapability.NODE_SECRETS,
            PluginRuntimeCapability.POSTGRESQL_EGRESS,
            PluginRuntimeCapability.UNTRUSTED_SQL,
        ),
    )
    admission = ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile="python-uv",
        supported_capabilities=frozenset({PluginRuntimeCapability.UNTRUSTED_SQL}),
    )

    assert (
        admission.decide(release, node_contract=artifact_query)
        is ReleaseExecutionRoute.ISOLATED
    )
    postgresql_decision = admission.decide(
        release,
        node_contract=postgresql,
    )
    assert isinstance(postgresql_decision, ReleaseExecutionRejection)
    assert postgresql_decision.reason == "unsupported_capabilities"
    assert "postgresql.egress" in postgresql_decision.detail


def test_admission_rejects_an_exact_revocation_with_the_stable_reason() -> None:
    release = _release(1)
    revocation = PluginReleaseRevocation.from_release(
        release,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_user_id=uuid4(),
    )

    decision = _RELEASE_ADMISSION.decide(release, revocation=revocation)

    assert isinstance(decision, ReleaseExecutionRejection)
    assert decision.reason == "revoked"
    assert "security" in decision.detail


def test_host_binding_registry_contract_mismatch_fails_composition_check() -> None:
    release = _host_text_release(1)
    binding = SystemHostPluginBinding.from_release(
        release,
        selection_generation=1,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )
    mismatched_catalog = binding.catalog.model_copy(
        update={"nodes": binding.catalog.nodes[:-1]}
    )
    mismatched = binding.model_copy(update={"catalog": mismatched_catalog})
    registry = build_explicit_plugin_registry()
    loaded = LoadedSystemPlugin(
        slug=release.release.slug,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )

    with pytest.raises(SystemHostBindingError, match="operators do not match"):
        validate_system_host_bindings((mismatched,), (loaded,), registry)


def test_host_binding_build_mismatch_fails_composition_check() -> None:
    release = _host_text_release(1)
    binding = SystemHostPluginBinding.from_release(
        release,
        selection_generation=1,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )
    loaded = LoadedSystemPlugin(
        slug=release.release.slug,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest="e" * 64,
    )
    registry = build_explicit_plugin_registry()

    with pytest.raises(SystemHostBindingError, match="build digest"):
        validate_system_host_bindings((binding,), (loaded,), registry)


@pytest.mark.asyncio
async def test_pin_to_another_workspace_fails_without_disclosing_the_release() -> None:
    foreign = _release(4, workspace_id=OTHER_WORKSPACE_ID)
    request = RunRequest(
        nodes=[
            _pinned_node(
                "echo",
                PluginReleasePinModel(
                    scope=PluginReleaseScope.WORKSPACE,
                    slug="notes",
                    revision=4,
                ),
            )
        ]
    )

    with pytest.raises(GraphExecutionError, match="does not exist in this workspace"):
        await _compiler(RecordingReleaseLookup(foreign)).compile(
            request,
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )


def test_builtin_node_cannot_carry_a_plugin_release_pin() -> None:
    with pytest.raises(ValidationError, match="cannot carry a Plugin release pin"):
        RunNodeRequest(
            kind="builtin",
            id="input",
            operator_id="text.input",
            operator_version=1,
            plugin_release=PluginReleasePinModel(
                scope=PluginReleaseScope.WORKSPACE,
                slug="notes",
                revision=1,
            ),
        )


def test_graph_module_cannot_carry_a_plugin_release_pin() -> None:
    with pytest.raises(ValidationError, match="cannot carry a Plugin release pin"):
        RunNodeRequest(
            kind="module",
            id="module",
            operator_id=f"graph.module.{uuid4()}",
            operator_version=1,
            plugin_release=PluginReleasePinModel(
                scope=PluginReleaseScope.WORKSPACE,
                slug="notes",
                revision=1,
            ),
        )


@pytest.mark.parametrize(
    "operator_id",
    [MODULE_INPUT_OPERATOR_ID, MODULE_OUTPUT_OPERATOR_ID],
)
def test_module_boundary_cannot_carry_a_plugin_release_pin(
    operator_id: str,
) -> None:
    with pytest.raises(ValidationError, match="cannot carry a Plugin release pin"):
        RunNodeRequest(
            kind="module",
            id="boundary",
            operator_id=operator_id,
            operator_version=1,
            plugin_release=PluginReleasePinModel(
                scope=PluginReleaseScope.SYSTEM,
                slug="notes",
                revision=1,
            ),
        )


def test_workspace_plugin_node_without_a_pin_fails_closed() -> None:
    with pytest.raises(ValidationError, match="must pin an exact Plugin release"):
        RunNodeRequest(
            kind="plugin",
            id="echo",
            operator_id="notes.echo",
            operator_version=1,
            config={"scale": 2},
        )


@pytest.mark.asyncio
async def test_missing_pinned_release_blocks_compilation_with_a_clear_error() -> None:
    published = _release(1)
    request = RunRequest(
        nodes=[
            _pinned_node(
                "echo",
                PluginReleasePinModel(
                    scope=PluginReleaseScope.WORKSPACE,
                    slug="notes",
                    revision=7,
                ),
            )
        ]
    )

    with pytest.raises(GraphExecutionError, match="revision 7, which does not exist"):
        await _compiler(RecordingReleaseLookup(published)).compile(
            request,
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.parametrize(
    ("release", "reason"),
    [
        (_release(1, executable=False), "missing_runtime_artifact"),
        (
            _release(
                1,
                nodes=(
                    _echo_contract().model_copy(
                        update={
                            "required_capabilities": (
                                PluginRuntimeCapability.NETWORK_EGRESS,
                            )
                        }
                    ),
                ),
                declared_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
            ),
            "unsupported_capabilities",
        ),
    ],
)
@pytest.mark.asyncio
async def test_exact_release_pin_cannot_bypass_execution_admission(
    release: InstalledPluginRelease,
    reason: PluginNonRunnableReason,
) -> None:
    with pytest.raises(GraphExecutionError, match=reason):
        await _compiler(RecordingReleaseLookup(release)).compile(
            _echo_run_request(pin_revision=1),
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_revoked_exact_release_pin_is_not_runnable() -> None:
    release = _release(1)
    revocation = PluginReleaseRevocation.from_release(
        release,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_user_id=uuid4(),
    )

    with pytest.raises(GraphExecutionError, match=r"not runnable \(revoked\)"):
        await _compiler(RecordingReleaseLookup(release, revocation=revocation)).compile(
            _echo_run_request(pin_revision=1),
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_compile_snapshots_exact_release_admission_facts_once() -> None:
    release = _release(1)
    lookup = RecordingReleaseLookup(release)
    request = _echo_run_request(pin_revision=1)
    request.nodes.append(
        _pinned_node(
            "echo-again",
            PluginReleasePinModel(
                scope=PluginReleaseScope.WORKSPACE,
                slug="notes",
                revision=1,
            ),
        )
    )
    request.edges.append(
        RunEdgeRequest(
            from_node="upstream",
            from_port="text",
            to_node="echo-again",
            to_port="text",
        )
    )

    compiled = await _compiler(lookup).compile(
        request,
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    assert len(compiled.nodes) == 2
    assert lookup.release_reads == 1
    assert lookup.selection_reads == 1
    assert lookup.revocation_reads == 1


@pytest.mark.asyncio
async def test_exact_release_pin_requires_the_isolated_adapter() -> None:
    release = _release(1)
    unavailable = ReleaseExecutionAdmission(
        isolated_adapter_available=False,
        runtime_profile="python-uv",
    )

    with pytest.raises(GraphExecutionError, match="plugin_runtime_unavailable"):
        await _compiler(
            RecordingReleaseLookup(release),
            admission=unavailable,
        ).compile(
            _echo_run_request(pin_revision=1),
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_release_that_does_not_declare_the_operator_is_rejected() -> None:
    published = _release(3, nodes=(_echo_contract(),))
    request = RunRequest(
        nodes=[
            _pinned_node(
                "echo",
                PluginReleasePinModel(
                    scope=PluginReleaseScope.WORKSPACE,
                    slug="notes",
                    revision=3,
                ),
                operator_id="notes.other",
            )
        ]
    )

    with pytest.raises(GraphExecutionError, match="does not declare operator"):
        await _compiler(RecordingReleaseLookup(published)).compile(
            request,
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_pinned_plugin_participates_in_ordinary_map_semantics() -> None:
    """Projections, cardinality, and MAP derivation stay on the shared path."""

    system_release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(system_release)
    binding = SystemHostPluginBinding.from_release(
        system_release,
        selection_generation=selection.generation,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )
    lookup = RecordingReleaseLookup(
        _release(1),
        _release(2),
        system_release,
        selection=selection,
    )
    from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
    from grafy_api.execution.requests import (
        PinnedOutputRequest,
        RunEdgeRequest,
    )

    source = RunNodeRequest(
        kind="builtin",
        id="source",
        operator_id="text.split",
        operator_version=1,
        config={"separator": "|"},
    )
    echo = _pinned_node(
        "echo",
        PluginReleasePinModel(
            scope=PluginReleaseScope.WORKSPACE,
            slug="notes",
            revision=1,
        ),
    )
    request = RunRequest(
        nodes=[source, echo],
        edges=[
            RunEdgeRequest(
                from_node="upstream",
                from_port="text",
                to_node="source",
                to_port="text",
            ),
            RunEdgeRequest(
                from_node="source",
                from_port="parts",
                to_node="echo",
                to_port="text",
                collection_mode="map",
            ),
        ],
        pinned_outputs=[
            PinnedOutputRequest(
                from_node="upstream",
                from_port="text",
                value=ArtifactRef.from_key(
                    artifact_id=uuid4(),
                    key=ArtifactTypeKey(TEXT.id, TEXT.schema_version),
                ),
            )
        ],
    )

    compiled = await _compiler(
        lookup,
        admission=ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
            system_host_bindings=(binding,),
        ),
    ).compile(
        request,
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    echo_compiled = next(node for node in compiled.nodes if node.request.id == "echo")
    assert echo_compiled.invocation.mode is InvocationMode.MAP
    assert echo_compiled.invocation.map_input == "text"
    assert echo_compiled.resolved_contracts.input_contract.ports["text"].accepts == (  # noqa: E501
        ArtifactTypeKey(TEXT.id, TEXT.schema_version)
    )


class OutputInvoker:
    """Invoker stub that returns one fixed host-minted output ref."""

    def __init__(self, output: ArtifactRef) -> None:
        self._output = output
        self.requests: list[PluginInvocationRequest] = []

    async def invoke(
        self,
        request: PluginInvocationRequest,
        /,
    ) -> PluginInvocationResult:
        self.requests.append(request)
        return PluginInvocationResult(outputs={"text": self._output})


class _CountingWriter:
    artifact_type = ArtifactTypeKey("test.release_pin.value", 1)

    def __init__(self) -> None:
        self.calls = 0

    async def write(self, value: object, context: object) -> ArtifactRef:
        self.calls += 1
        raise AssertionError("Plugin-owned values must not reach a host writer")


class _MemoryInvocationCache:
    def __init__(self) -> None:
        self.puts = 0

    async def get(self, workspace_id: UUID, key_sha256: str) -> object:
        return None

    async def put_if_absent(self, entry: object) -> bool:
        self.puts += 1
        return True

    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        return False


class _FixedEdgeValues:
    def __init__(self, inputs: Mapping[str, object]) -> None:
        self._inputs = inputs

    async def assemble_inputs(
        self,
        compiled_node: object,
        incoming_edges: object,
        outputs: object,
        workflow_run_id: UUID,
        workspace_id: UUID,
    ) -> dict[str, object]:
        del compiled_node, incoming_edges, outputs, workflow_run_id, workspace_id
        return dict(self._inputs)


@pytest.mark.asyncio
async def test_release_node_executes_with_caching_disabled_and_refs_untouched() -> None:
    """An EXACT-style release path still runs fail-closed without invocation
    caching, and host-minted output refs pass through the persister."""

    from grafy_core.artifacts import ArtifactTypeSpec
    from grafy_core.plugins import NodeCachePolicy, NodeRegistration
    from grafy_core.runtime.invocation_cache import InvocationCachePort
    from grafy_api.execution.models import (
        CompiledGraph,
        CompiledNode,
    )

    value_key = ArtifactTypeKey(TEXT.id, TEXT.schema_version)
    outgoing = ArtifactRef.from_key(artifact_id=uuid4(), key=value_key)
    invoker = OutputInvoker(outgoing)
    lookup = RecordingReleaseLookup(_release(1), _release(2))

    compiled = await _compiler(lookup, cast(NoopInvoker | None, invoker)).compile(
        _echo_run_request(pin_revision=1),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )
    pinned = compiled.nodes[0]
    assert isinstance(pinned.node, PluginReleaseNode)

    # Even a registration that would normally earn caching stays fail-closed.
    forced_registration = NodeRegistration(
        node_class=type(pinned.node),
        factory=None,
        cache_policy=NodeCachePolicy.EXACT,
    )
    recompiled = CompiledNode(
        request=pinned.request,
        node=pinned.node,
        registration=forced_registration,
        resolved_contracts=pinned.resolved_contracts,
        invocation=pinned.invocation,
        artifact_type_bindings=pinned.artifact_type_bindings,
        plugin_release=pinned.plugin_release,
    )
    plan = CompiledGraph(nodes=(recompiled,), edges=(), pinned_outputs={})

    incoming_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=value_key)
    writer = _CountingWriter()
    cache = _MemoryInvocationCache()
    runtime = NodeRuntime(
        materializer=InputMaterializer(ResolverRegistry()),
        persister=OutputPersister(ArtifactWriterRegistry([writer])),
        invocation_cache=cast(InvocationCachePort, cache),
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=runtime,
            edge_values=cast(
                EdgeValueResolver, _FixedEdgeValues({"text": incoming_ref})
            ),
            node_secrets=UnavailableNodeSecretResolver(),
        )
    )

    def _execution() -> PreparedGraphExecution:
        return PreparedGraphExecution(
            workspace_id=WORKSPACE_ID,
            plan=plan,
            initial_outputs={},
            graph_id=None,
            graph_revision=None,
            secret_graph_id=None,
            secret_graph_revision=None,
            secret_node_ids=frozenset(),
            module_path=(),
            raise_node_errors=False,
        )

    first = await coordinator.execute(_execution())
    second = await coordinator.execute(_execution())

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    # The invoker ran for both executions; no cache entry was consulted or set.
    assert len(invoker.requests) == 2
    assert cache.puts == 0
    for request_record in invoker.requests:
        assert request_record.inputs["text"] is incoming_ref
    # Host-minted output refs pass through untouched; the writer never ran.
    first_output = first.node_results[0].outputs["text"]
    second_output = second.node_results[0].outputs["text"]
    assert isinstance(first_output, ArtifactRef)
    assert first_output == outgoing
    assert second_output == outgoing
    assert writer.calls == 0
    del value_key, ArtifactTypeSpec


@pytest.mark.asyncio
async def test_host_node_output_feeds_pinned_workspace_plugin_in_same_graph(
    tmp_path: Path,
) -> None:
    """Host and release nodes share the ordinary artifact-ref graph boundary."""

    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    registry = build_explicit_plugin_registry()
    plugin_context = PluginRuntimeContext(
        workspace=tmp_path,
        uploads_dir=tmp_path / "uploads",
        storage=storage,
        uow=unit_of_work,
        bucket="test-artifacts",
    )
    outgoing = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=ArtifactTypeKey(TEXT.id, TEXT.schema_version),
    )
    invoker = OutputInvoker(outgoing)
    saved_graphs = SavedGraphService(_unused_saved_graph_uow, registry)
    system_release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(system_release)
    binding = SystemHostPluginBinding.from_release(
        system_release,
        selection_generation=selection.generation,
        loader_target=HOST_LOADER_TARGET,
        host_build_digest=HOST_BUILD_DIGEST,
    )
    lookup = RecordingReleaseLookup(
        _release(1),
        _release(2),
        system_release,
        selection=selection,
    )
    compiler = GraphCompiler(
        plugin_registry=registry,
        plugin_context=plugin_context,
        module_library=ModuleLibraryService(_unused_saved_graph_uow, registry),
        canonical_artifact_conversions=CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
        plugin_release_lookup=lookup,
        plugin_invoker=invoker,
        release_admission=ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
            system_host_bindings=(binding,),
        ),
        build_digest="a" * 64,
    )
    request = RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="host-input",
                operator_id="text.input",
                operator_version=1,
                config={"text": "from host"},
            ),
            _pinned_node(
                "plugin-echo",
                PluginReleasePinModel(
                    scope=PluginReleaseScope.WORKSPACE,
                    slug="notes",
                    revision=1,
                ),
            ),
        ],
        edges=[
            RunEdgeRequest(
                from_node="host-input",
                from_port="text",
                to_node="plugin-echo",
                to_port="text",
            )
        ],
    )
    writer_registry = ArtifactWriterRegistry([TextValueOutputWriter(uow=unit_of_work)])
    resolver_registry = ResolverRegistry([TextValueResolver(uow=unit_of_work)])
    artifacts = ArtifactService(
        unit_of_work,
        storage,
        artifact_types={
            (spec.key.id, spec.key.schema_version): spec
            for spec in registry.artifact_types
        },
        availability=ArtifactAvailability(unit_of_work, storage),
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=NodeRuntime(
                materializer=InputMaterializer(resolver_registry),
                persister=OutputPersister(writer_registry),
            ),
            edge_values=EdgeValueResolver(
                resolvers=resolver_registry,
                writers=writer_registry,
                artifacts=artifacts,
            ),
            node_secrets=UnavailableNodeSecretResolver(),
        )
    )
    run_graph = RunGraph(
        preflight=GraphRunPreflight(
            plugin_registry=registry,
            saved_graphs=saved_graphs,
            plugin_release_lookup=lookup,
        ),
        compiler=compiler,
        coordinator=coordinator,
        materializations=MaterializationService(
            unit_of_work, ArtifactAvailability(unit_of_work, storage), saved_graphs
        ),
    )
    result = await run_graph.run(WORKSPACE_ID, request)
    assert lookup.release_reads == 1
    assert lookup.selection_reads == 1
    assert lookup.revocation_reads == 1

    assert result.status == "succeeded"
    assert [node.status for node in result.node_results] == [
        "succeeded",
        "succeeded",
    ]
    assert result.node_results[0].plugin_release is None
    assert result.node_results[1].plugin_release is not None
    assert result.node_results[1].plugin_release.revision == 1
    assert len(invoker.requests) == 1
    host_ref = invoker.requests[0].inputs["text"]
    assert isinstance(host_ref, ArtifactRef)
    assert await TextValueResolver(uow=unit_of_work).resolve(
        host_ref, WORKSPACE_ID
    ) == ("from host")
    assert result.outputs["plugin-echo"]["text"] == outgoing


@pytest.mark.asyncio
async def test_release_revoked_after_preflight_is_rejected_by_compilation() -> None:
    release = _release(1)
    lookup = RecordingReleaseLookup(release)
    preflight = GraphRunPreflight(
        plugin_registry=build_explicit_plugin_registry(),
        saved_graphs=None,
        plugin_release_lookup=lookup,
    )
    request = _echo_run_request(pin_revision=1)
    context = await preflight.validate(WORKSPACE_ID, request)
    assert lookup.revocation_reads == 0
    lookup._revocation = PluginReleaseRevocation.from_release(
        release,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_user_id=uuid4(),
    )

    with pytest.raises(GraphExecutionError, match=r"not runnable \(revoked\)"):
        await _compiler(lookup).compile(
            request,
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
            resolved_releases=context.resolved_releases,
        )

    assert lookup.release_reads == 1
    assert lookup.revocation_reads == 1
    assert lookup.selection_reads == 1


@pytest.mark.asyncio
async def test_prepared_release_cannot_cross_workspace_boundary() -> None:
    lookup = RecordingReleaseLookup(_release(1))
    preflight = GraphRunPreflight(
        plugin_registry=build_explicit_plugin_registry(),
        saved_graphs=None,
        plugin_release_lookup=lookup,
    )
    request = _echo_run_request(pin_revision=1)
    context = await preflight.validate(WORKSPACE_ID, request)

    with pytest.raises(GraphExecutionError, match="does not exist in this workspace"):
        await _compiler(lookup).compile(
            request,
            _UnusedModuleExecutor(),
            workspace_id=uuid4(),
            resolved_releases=context.resolved_releases,
        )

    assert lookup.release_reads == 2
    assert lookup.revocation_reads == 0


@pytest.mark.asyncio
async def test_release_preparation_is_scoped_to_each_run() -> None:
    lookup = RecordingReleaseLookup(_release(1))
    preflight = GraphRunPreflight(
        plugin_registry=build_explicit_plugin_registry(),
        saved_graphs=None,
        plugin_release_lookup=lookup,
    )
    compiler = _compiler(lookup)
    request = _echo_run_request(pin_revision=1)
    for _ in range(2):
        context = await preflight.validate(WORKSPACE_ID, request)
        plan = await compiler.compile(
            request,
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
            resolved_releases=context.resolved_releases,
        )
        assert len(plan.nodes) == 1

    assert lookup.release_reads == 2
    assert lookup.revocation_reads == 2
    assert lookup.selection_reads == 2
