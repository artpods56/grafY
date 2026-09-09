"""Composition root for workbench-facing application components."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.canonical_conversions import (
    CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
    CanonicalArtifactConversionMap,
)
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.materialized_outputs import WorkbenchUnitOfWorkPort
from grafy_core.ports.node_secrets import (
    NodeSecretResolverPort,
    UnavailableNodeSecretResolver,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    OutputPersister,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_storage import LocalFileObjectStore

from grafy_api.plugins.runtime.admission import (
    HOST_BASE_CAPABILITIES,
    ReleaseExecutionAdmission,
)
from grafy_api.plugins.runtime.network_policy import NetworkPolicy
from grafy_api.plugins.compatibility.bindings import (
    validate_system_host_bindings,
)
from grafy_core.domain.plugin_host_bindings import (
    LoadedSystemPlugin,
    SystemHostPluginBinding,
)
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.realtime.hub import GraphRoomHub
from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_core.runtime.persistent_invocation_cache import PersistentInvocationCache
from grafy_api.execution.manager import RunExecutionManager
from grafy_api.execution.node_execution import NodeExecutionService
from grafy_api.plugins.runtime.artifacts import ArtifactBundlePluginInvoker
from grafy_api.plugins.runtime.docker import DockerPluginRuntime
from grafy_api.execution.admission import ExecutionAdmissionLimiter
from grafy_api.execution.preflight import GraphRunPreflight
from grafy_api.execution.run_graph import RunGraph
from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.materializations import MaterializationService
from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.v1.routes.executions.services import RunResultPresenter
from grafy_api.settings import STAGED_UPLOAD_HARD_MAX_BYTES
from grafy_api.staged_uploads import StagedUploadService


_WORKBENCH_BUCKET = "workbench-artifacts"


@dataclass(frozen=True, slots=True)
class WorkbenchComponents:
    plugin_registry: PluginRegistry
    uploads: StagedUploadService
    module_library: ModuleLibraryService | None
    plugin_releases: PluginReleaseService | None
    run_graph: RunGraph
    execution_admission: ExecutionAdmissionLimiter
    execution_manager: RunExecutionManager
    execution_history: ExecutionHistoryService
    materializations: MaterializationService
    presenter: RunResultPresenter
    artifacts: ArtifactService
    plugin_invoker: ArtifactBundlePluginInvoker | None
    plugin_runtime: DockerPluginRuntime | None
    release_admission: ReleaseExecutionAdmission | None


def build_workbench_components(
    *,
    plugin_registry: PluginRegistry,
    map_max_concurrency: int = 4,
    max_active_executions: int = 2,
    max_pending_graphs: int = 20,
    max_active_plugin_invocations: int = 4,
    plugin_invocation_wall_time_seconds_by_slug: Mapping[str, int] | None = None,
    workspace: Path | None = None,
    unit_of_work: WorkbenchUnitOfWorkPort | None = None,
    storage: FileStoragePort | None = None,
    storage_backend: str = "local",
    bucket: str = _WORKBENCH_BUCKET,
    staged_upload_max_bytes: int = STAGED_UPLOAD_HARD_MAX_BYTES,
    saved_graphs: SavedGraphService | None = None,
    module_library: ModuleLibraryService | None = None,
    plugin_releases: PluginReleaseService | None = None,
    plugin_runtime: DockerPluginRuntime | None = None,
    system_host_bindings: tuple[SystemHostPluginBinding, ...] = (),
    loaded_system_plugins: tuple[LoadedSystemPlugin, ...] = (),
    node_secrets: NodeSecretResolverPort | None = None,
    graph_room_hub: GraphRoomHub | None = None,
    network_policy: NetworkPolicy | None = None,
    canonical_artifact_conversions: CanonicalArtifactConversionMap = (
        CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
    ),
    build_digest: str = "a" * 64,
) -> WorkbenchComponents:
    validate_system_host_bindings(
        system_host_bindings,
        loaded_system_plugins,
        plugin_registry,
    )
    if system_host_bindings and plugin_releases is None:
        raise RuntimeError("System host bindings require Plugin release persistence")
    resolved_workspace = (
        (
            workspace
            or Path(
                os.getenv(
                    "GRAFY_WORKSPACE",
                    ".grafy-artifacts/workbench",
                )
            )
        )
        .expanduser()
        .resolve()
    )
    uploads_dir = resolved_workspace / "uploads"
    resolved_unit_of_work = unit_of_work or InMemoryUnitOfWork()
    uploads = StagedUploadService(
        uploads_dir,
        unit_of_work_factory=lambda: resolved_unit_of_work,
        max_upload_bytes=staged_upload_max_bytes,
    )
    resolved_storage = storage or LocalFileObjectStore(resolved_workspace / "objects")
    resolved_node_secrets = node_secrets or UnavailableNodeSecretResolver()
    plugin_context = PluginRuntimeContext(
        workspace=resolved_workspace,
        uploads_dir=uploads_dir,
        storage=resolved_storage,
        uow=resolved_unit_of_work,
        bucket=bucket,
        storage_backend=storage_backend,
        node_secrets=resolved_node_secrets,
    )

    resolver_registry = ResolverRegistry(
        list(plugin_registry.build_resolvers(plugin_context))
    )
    writer_registry = ArtifactWriterRegistry(
        list(plugin_registry.build_writers(plugin_context))
    )

    availability = ArtifactAvailability(resolved_unit_of_work, resolved_storage)
    artifacts = ArtifactService(
        resolved_unit_of_work,
        resolved_storage,
        availability=availability,
        artifact_types={
            (spec.key.id, spec.key.schema_version): spec
            for spec in plugin_registry.artifact_types
        },
    )
    materializations = MaterializationService(
        resolved_unit_of_work,
        availability,
        saved_graphs,
    )
    presenter = RunResultPresenter(artifacts, availability)
    plugin_invoker = None
    artifact_plugin_invoker = None
    release_admission: ReleaseExecutionAdmission | None = None
    if plugin_releases is not None:
        if plugin_runtime is None:
            release_admission = ReleaseExecutionAdmission(
                isolated_adapter_available=False,
                runtime_profile=None,
                system_host_bindings=system_host_bindings,
                host_supported_capabilities=HOST_BASE_CAPABILITIES,
            )
        else:
            artifact_plugin_invoker = ArtifactBundlePluginInvoker(
                unit_of_work=resolved_unit_of_work,
                runner=plugin_runtime,
                scratch=plugin_runtime,
                storage=resolved_storage,
                bucket=bucket,
                storage_backend=storage_backend,
                max_concurrent_invocations=max_active_plugin_invocations,
                wall_time_seconds_by_plugin_slug=(
                    plugin_invocation_wall_time_seconds_by_slug
                ),
                node_secrets=resolved_node_secrets,
                uploads_dir=uploads_dir,
            )
            plugin_invoker = artifact_plugin_invoker
            runtime_admission = plugin_runtime.release_admission
            release_admission = ReleaseExecutionAdmission(
                isolated_adapter_available=(
                    runtime_admission.isolated_adapter_available
                ),
                runtime_profile=runtime_admission.runtime_profile,
                supported_capabilities=runtime_admission.supported_capabilities,
                network_egress=runtime_admission.network_egress,
                postgresql_egress=runtime_admission.postgresql_egress,
                network_policy=runtime_admission.network_policy,
                supported_bundle_adapters=(runtime_admission.supported_bundle_adapters),
                platform_artifact_contracts=(
                    runtime_admission.platform_artifact_contracts
                ),
                system_host_bindings=system_host_bindings,
                host_supported_capabilities=HOST_BASE_CAPABILITIES,
            )
    compiler = GraphCompiler(
        plugin_registry=plugin_registry,
        plugin_context=plugin_context,
        module_library=module_library,
        canonical_artifact_conversions=canonical_artifact_conversions,
        plugin_release_lookup=plugin_releases,
        plugin_invoker=plugin_invoker,
        release_admission=release_admission,
        build_digest=build_digest,
    )
    edge_values = EdgeValueResolver(
        resolvers=resolver_registry,
        writers=writer_registry,
        artifacts=artifacts,
    )
    runtime = NodeRuntime(
        materializer=InputMaterializer(resolver_registry),
        persister=OutputPersister(writer_registry),
        invocation_cache=PersistentInvocationCache(
            unit_of_work=resolved_unit_of_work,
            storage=resolved_storage,
        ),
    )
    node_execution = NodeExecutionService(
        runtime=runtime,
        edge_values=edge_values,
        node_secrets=resolved_node_secrets,
        max_map_concurrency=map_max_concurrency,
    )
    coordinator = GraphExecutionCoordinator(node_execution=node_execution)
    if network_policy is not None:
        resolved_network_policy = network_policy
    elif plugin_runtime is not None:
        resolved_network_policy = plugin_runtime.network_policy
    else:
        resolved_network_policy = NetworkPolicy()
    preflight = GraphRunPreflight(
        plugin_registry=plugin_registry,
        saved_graphs=saved_graphs,
        plugin_release_lookup=plugin_releases,
        network_policy=resolved_network_policy,
    )
    run_graph = RunGraph(
        preflight=preflight,
        compiler=compiler,
        coordinator=coordinator,
        materializations=materializations,
        plugin_sandboxes=plugin_runtime,
    )
    execution_history = ExecutionHistoryService(resolved_unit_of_work, saved_graphs)
    execution_admission = ExecutionAdmissionLimiter(max_active_executions)
    execution_manager = RunExecutionManager(
        run_graph,
        execution_history=execution_history,
        admission_limiter=execution_admission,
        max_pending_graphs=max_pending_graphs,
        graph_room_hub=graph_room_hub,
    )
    return WorkbenchComponents(
        plugin_registry=plugin_registry,
        uploads=uploads,
        module_library=module_library,
        plugin_releases=plugin_releases,
        run_graph=run_graph,
        execution_admission=execution_admission,
        execution_manager=execution_manager,
        execution_history=execution_history,
        materializations=materializations,
        presenter=presenter,
        artifacts=artifacts,
        plugin_invoker=artifact_plugin_invoker,
        plugin_runtime=plugin_runtime,
        release_admission=release_admission,
    )


__all__ = ["WorkbenchComponents", "build_workbench_components"]
