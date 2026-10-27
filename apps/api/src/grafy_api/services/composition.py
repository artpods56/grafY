"""Composition root for workbench-facing application components."""

import logging
from dataclasses import dataclass
from pathlib import Path

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.canonical_conversions import (
    CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
    CanonicalArtifactConversionMap,
)
from grafy_core.egress import EgressPolicy, default_egress_policy
from grafy_core.file_contracts import BUILTIN_FILE_FORMATS, build_extension_table
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.materialized_outputs import WorkbenchUnitOfWorkPort
from grafy_core.ports.node_secrets import (
    NodeSecretResolverPort,
    UnavailableNodeSecretResolver,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    ArtifactOutputWriter,
    OutputPersister,
)
from grafy_core.runtime.persistent_invocation_cache import PersistentInvocationCache
from grafy_core.runtime.resolvers import Resolver, ResolverRegistry
from grafy_shared.config import ExecutionConfig
from grafy_storage import LocalFileObjectStore

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.execution.admission import ExecutionAdmissionLimiter
from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.manager import RunExecutionManager
from grafy_api.execution.materializations import MaterializationService
from grafy_api.execution.node_execution import NodeExecutionService
from grafy_api.execution.preflight import GraphRunPreflight
from grafy_api.execution.run_graph import RunGraph
from grafy_api.realtime.hub import GraphRoomHub
from grafy_api.uploads import UploadService, UploadServiceConfig
from grafy_core.ports.storage import PresigningStorage
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.executions.services import RunResultPresenter
from grafy_api.v1.routes.library.folders import LibraryFoldersService
from grafy_api.v1.routes.library.services import LibraryService

logger = logging.getLogger(__name__)

_WORKBENCH_BUCKET = "workbench-artifacts"


@dataclass(frozen=True, slots=True)
class WorkbenchComponents:
    plugin_registry: PluginRegistry
    upload_config: UploadServiceConfig
    uploads: UploadService
    module_library: ModuleLibraryService | None
    plugin_releases: PluginReleaseService | None
    run_graph: RunGraph
    execution_admission: ExecutionAdmissionLimiter
    execution_manager: RunExecutionManager
    execution_history: ExecutionHistoryService
    materializations: MaterializationService
    presenter: RunResultPresenter
    artifacts: ArtifactService
    library: LibraryService
    library_folders: LibraryFoldersService
    plugin_invoker: None
    plugin_runtime: None
    release_admission: None
    python_apply: None = None


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    """How much concurrent work one workbench instance is allowed to admit.

    The deployment supplies this from ExecutionConfig; the
    literal defaults keep a standalone composition independent of the operator
    environment instead of silently reading GRAFY_* variables.
    """

    map_max_concurrency: int = 4
    max_active_executions: int = 2
    max_pending_graphs: int = 20

    @classmethod
    def from_config(cls, execution: ExecutionConfig) -> "ExecutionLimits":
        return cls(
            map_max_concurrency=execution.map_max_concurrency,
            max_active_executions=execution.max_active_executions,
            max_pending_graphs=execution.max_pending_graphs,
        )


def build_workbench_components(
    *,
    plugin_registry: PluginRegistry | None = None,
    workspace: Path,
    dedupe_artifact_handlers: bool = True,
    limits: ExecutionLimits | None = None,
    unit_of_work: WorkbenchUnitOfWorkPort | None = None,
    storage: FileStoragePort | None = None,
    storage_backend: str = "local",
    bucket: str = _WORKBENCH_BUCKET,
    upload_config: UploadServiceConfig | None = None,
    saved_graphs: SavedGraphService | None = None,
    module_library: ModuleLibraryService | None = None,
    plugin_releases: PluginReleaseService | None = None,
    node_secrets: NodeSecretResolverPort | None = None,
    graph_room_hub: GraphRoomHub | None = None,
    egress_policy: EgressPolicy | None = None,
    canonical_artifact_conversions: CanonicalArtifactConversionMap = (
        CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
    ),
    build_digest: str = "a" * 64,
) -> WorkbenchComponents:
    if plugin_registry is None:
        from grafy_api.services.families import build_application_registry

        plugin_registry = build_application_registry()
    resolved_limits = limits or ExecutionLimits()
    resolved_workspace = workspace.expanduser().resolve()
    resolved_unit_of_work = unit_of_work or InMemoryUnitOfWork()
    resolved_storage = storage or LocalFileObjectStore(resolved_workspace / "objects")
    # A workbench dials what node configuration names, so the deployment policy
    # is composed here rather than read where the request is made. `None` takes
    # the policy named by `GRAFY_EGRESS_TRUSTED_DESTINATIONS`.
    resolved_egress_policy = (
        default_egress_policy() if egress_policy is None else egress_policy
    )
    artifact_types = {
        (spec.key.id, spec.key.schema_version): spec
        for spec in (*BUILTIN_FILE_FORMATS, *plugin_registry.artifact_types)
    }
    extension_claims = build_extension_table(
        (spec.key, spec.extensions) for spec in artifact_types.values()
    )
    # The static registry owns every extension, independent of release tables.
    resolved_upload_config = upload_config or UploadServiceConfig()
    uploads = UploadService.from_config(
        resolved_upload_config,
        storage=resolved_storage,
        unit_of_work_factory=lambda: resolved_unit_of_work,
        presigning=(
            resolved_storage
            if isinstance(resolved_storage, PresigningStorage)
            else None
        ),
        artifact_types=artifact_types,
        extension_claims=extension_claims,
        bucket=bucket,
        storage_backend=storage_backend,
    )
    resolved_node_secrets = node_secrets or UnavailableNodeSecretResolver()
    plugin_context = PluginRuntimeContext(
        workspace=resolved_workspace,
        storage=resolved_storage,
        uow=resolved_unit_of_work,
        bucket=bucket,
        storage_backend=storage_backend,
        artifact_types=tuple(artifact_types.values()),
        node_secrets=resolved_node_secrets,
    )

    resolvers = list(plugin_registry.build_resolvers(plugin_context))
    writers = list(plugin_registry.build_writers(plugin_context))
    if dedupe_artifact_handlers:
        resolver_keys: set[tuple[ArtifactTypeKey, type[object]]] = set()
        unique_resolvers: list[Resolver[object]] = []
        for resolver in resolvers:
            key = (resolver.source, resolver.target)
            if key in resolver_keys:
                logger.info(
                    "shared_artifact_resolver_deduplicated source=%s@%s target=%s",
                    resolver.source.id,
                    resolver.source.schema_version,
                    resolver.target,
                )
                continue
            resolver_keys.add(key)
            unique_resolvers.append(resolver)
        resolvers = unique_resolvers
        writer_keys: set[ArtifactTypeKey] = set()
        unique_writers: list[ArtifactOutputWriter] = []
        for writer in writers:
            if writer.artifact_type in writer_keys:
                logger.info(
                    "shared_artifact_writer_deduplicated artifact_type=%s@%s",
                    writer.artifact_type.id,
                    writer.artifact_type.schema_version,
                )
                continue
            writer_keys.add(writer.artifact_type)
            unique_writers.append(writer)
        writers = unique_writers
    resolver_registry = ResolverRegistry(resolvers)
    writer_registry = ArtifactWriterRegistry(writers)

    availability = ArtifactAvailability(resolved_unit_of_work, resolved_storage)
    artifacts = ArtifactService(
        resolved_unit_of_work,
        resolved_storage,
        availability=availability,
        artifact_types=artifact_types,
        egress_policy=resolved_egress_policy,
    )
    materializations = MaterializationService(
        resolved_unit_of_work,
        availability,
        saved_graphs,
        build_digest=build_digest,
    )
    presenter = RunResultPresenter(artifacts, availability)
    library = LibraryService(
        resolved_unit_of_work,
        artifacts,
        artifact_types=artifact_types,
        saved_graphs=saved_graphs,
        storage=resolved_storage,
    )
    library_folders = LibraryFoldersService(resolved_unit_of_work)
    compiler = GraphCompiler(
        plugin_registry=plugin_registry,
        plugin_context=plugin_context,
        module_library=module_library,
        canonical_artifact_conversions=canonical_artifact_conversions,
        build_digest=build_digest,
    )
    edge_values = EdgeValueResolver(
        resolvers=resolver_registry,
        writers=writer_registry,
        unit_of_work=resolved_unit_of_work,
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
        max_map_concurrency=resolved_limits.map_max_concurrency,
    )
    coordinator = GraphExecutionCoordinator(node_execution=node_execution)
    preflight = GraphRunPreflight(
        plugin_registry=plugin_registry,
        saved_graphs=saved_graphs,
    )
    run_graph = RunGraph(
        preflight=preflight,
        compiler=compiler,
        coordinator=coordinator,
        materializations=materializations,
    )
    execution_history = ExecutionHistoryService(resolved_unit_of_work, saved_graphs)
    execution_admission = ExecutionAdmissionLimiter(
        resolved_limits.max_active_executions
    )
    execution_manager = RunExecutionManager(
        run_graph,
        execution_history=execution_history,
        admission_limiter=execution_admission,
        max_pending_graphs=resolved_limits.max_pending_graphs,
        graph_room_hub=graph_room_hub,
    )
    return WorkbenchComponents(
        plugin_registry=plugin_registry,
        upload_config=resolved_upload_config,
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
        library=library,
        library_folders=library_folders,
        plugin_invoker=None,
        plugin_runtime=None,
        release_admission=None,
        python_apply=None,
    )


__all__ = [
    "ExecutionLimits",
    "WorkbenchComponents",
    "build_workbench_components",
]
