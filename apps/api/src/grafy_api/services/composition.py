"""Composition root for workbench-facing application components."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from grafy_core.artifacts import InMemoryUnitOfWork
from grafy_core.application.agent_authoring import AgentAuthoringService
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.operators.arithmetic import (
    IntegerValueOutputWriter,
    IntegerValueResolver,
)
from grafy_core.operators.text import TextValueOutputWriter, TextValueResolver
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
    ArtifactOutputWriter,
    ArtifactWriterRegistry,
    OutputPersister,
)
from grafy_core.runtime.resolvers import Resolver, ResolverRegistry
from grafy_storage import LocalFileObjectStore

from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.v1.routes.catalog.services import GraphModuleCatalog
from grafy_api.v1.routes.executions.runtime.compiler import GraphCompiler
from grafy_api.v1.routes.executions.runtime.generated_executor import (
    GeneratedNodeExecutorClient,
    UnavailableGeneratedReleaseExecutor,
)
from grafy_api.v1.routes.executions.runtime.coordinator import (
    GraphExecutionCoordinator,
)
from grafy_api.v1.routes.executions.runtime.edge_values import EdgeValueResolver
from grafy_api.v1.routes.executions.runtime.inline import InlineExecutionEngine
from grafy_api.v1.routes.executions.runtime.invocation_cache import (
    PersistentInvocationCache,
)
from grafy_api.v1.routes.executions.runtime.manager import RunExecutionManager
from grafy_api.v1.routes.executions.runtime.node_execution import (
    NodeExecutionService,
)
from grafy_api.v1.routes.executions.runtime.admission import (
    ExecutionAdmissionLimiter,
)
from grafy_api.v1.routes.executions.runtime.prefect import PrefectExecutionEngine
from grafy_api.v1.routes.executions.runtime.preflight import GraphRunPreflight
from grafy_api.v1.routes.executions.runtime.run_graph import RunGraph
from grafy_api.v1.routes.executions.services import (
    ExecutionHistoryService,
    MaterializationService,
    RunResultPresenter,
)
from grafy_api.settings import STAGED_UPLOAD_HARD_MAX_BYTES
from grafy_api.v1.routes.uploads.services import ImageUploadService


_WORKBENCH_BUCKET = "workbench-artifacts"


@dataclass(frozen=True, slots=True)
class WorkbenchComponents:
    plugin_registry: PluginRegistry
    uploads: ImageUploadService
    modules: GraphModuleCatalog
    run_graph: RunGraph
    execution_admission: ExecutionAdmissionLimiter
    execution_manager: RunExecutionManager
    execution_history: ExecutionHistoryService
    materializations: MaterializationService
    presenter: RunResultPresenter
    artifacts: ArtifactService
    generated_executor: GeneratedNodeExecutorClient | None


def build_workbench_components(
    *,
    plugin_registry: PluginRegistry,
    execution_backend: Literal["prefect", "inline"],
    map_max_concurrency: int = 4,
    max_active_executions: int = 2,
    prefect_task_retries: int = 0,
    prefect_task_retry_delay_seconds: float = 0,
    workspace: Path | None = None,
    unit_of_work: WorkbenchUnitOfWorkPort | None = None,
    storage: FileStoragePort | None = None,
    storage_backend: str = "local",
    bucket: str = _WORKBENCH_BUCKET,
    staged_upload_max_bytes: int = STAGED_UPLOAD_HARD_MAX_BYTES,
    saved_graphs: SavedGraphService | None = None,
    module_library: ModuleLibraryService | None = None,
    node_secrets: NodeSecretResolverPort | None = None,
    agent_authoring: AgentAuthoringService | None = None,
    generated_executor_url: str | None = None,
    generated_executor_hmac_key: bytes | None = None,
    generated_executor_timeout_seconds: float = 120.0,
) -> WorkbenchComponents:
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
    uploads = ImageUploadService(
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

    resolvers = [
        cast(Resolver[object], IntegerValueResolver(uow=resolved_unit_of_work)),
        cast(Resolver[object], TextValueResolver(uow=resolved_unit_of_work)),
    ]
    resolvers.extend(plugin_registry.build_resolvers(plugin_context))
    resolver_registry = ResolverRegistry(resolvers)

    writers: list[ArtifactOutputWriter] = [
        IntegerValueOutputWriter(uow=resolved_unit_of_work),
        TextValueOutputWriter(uow=resolved_unit_of_work),
    ]
    writers.extend(plugin_registry.build_writers(plugin_context))
    writer_registry = ArtifactWriterRegistry(writers)

    artifacts = ArtifactService(
        resolved_unit_of_work,
        resolved_storage,
        artifact_types={
            (spec.key.id, spec.key.schema_version): spec
            for spec in plugin_registry.artifact_types
        },
    )
    modules = GraphModuleCatalog(
        saved_graphs,
        plugin_registry,
        module_library=module_library,
    )
    materializations = MaterializationService(
        resolved_unit_of_work,
        artifacts,
        saved_graphs,
    )
    presenter = RunResultPresenter(artifacts)
    generated_executor_client: GeneratedNodeExecutorClient | None = None
    generated_executor = UnavailableGeneratedReleaseExecutor()
    if generated_executor_url is not None and generated_executor_hmac_key is not None:
        generated_executor_client = GeneratedNodeExecutorClient(
            base_url=generated_executor_url,
            hmac_key=generated_executor_hmac_key,
            timeout_seconds=generated_executor_timeout_seconds,
        )
        generated_executor = generated_executor_client
    compiler = GraphCompiler(
        plugin_registry=plugin_registry,
        plugin_context=plugin_context,
        module_catalog=modules,
        generated_releases=agent_authoring,
        generated_executor=generated_executor,
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
    effective_map_max_concurrency = 1
    if execution_backend == "prefect":
        effective_map_max_concurrency = map_max_concurrency
    node_execution = NodeExecutionService(
        runtime=runtime,
        edge_values=edge_values,
        node_secrets=resolved_node_secrets,
        max_map_concurrency=effective_map_max_concurrency,
    )
    coordinator = GraphExecutionCoordinator(node_execution=node_execution)
    if execution_backend == "prefect":
        engine = PrefectExecutionEngine(
            coordinator=coordinator,
            task_retries=prefect_task_retries,
            task_retry_delay_seconds=prefect_task_retry_delay_seconds,
        )
    else:
        engine = InlineExecutionEngine(coordinator=coordinator)
    preflight = GraphRunPreflight(
        plugin_registry=plugin_registry,
        saved_graphs=saved_graphs,
    )
    run_graph = RunGraph(
        preflight=preflight,
        compiler=compiler,
        engine=engine,
        materializations=materializations,
    )
    execution_history = ExecutionHistoryService(resolved_unit_of_work, saved_graphs)
    execution_admission = ExecutionAdmissionLimiter(max_active_executions)
    execution_manager = RunExecutionManager(
        run_graph,
        execution_history=execution_history,
        admission_limiter=execution_admission,
    )
    return WorkbenchComponents(
        plugin_registry=plugin_registry,
        uploads=uploads,
        modules=modules,
        run_graph=run_graph,
        execution_admission=execution_admission,
        execution_manager=execution_manager,
        execution_history=execution_history,
        materializations=materializations,
        presenter=presenter,
        artifacts=artifacts,
        generated_executor=generated_executor_client,
    )


__all__ = ["WorkbenchComponents", "build_workbench_components"]
