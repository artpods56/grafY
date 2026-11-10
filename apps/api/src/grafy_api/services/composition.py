"""Composition root for workbench-facing application components."""

import logging
from dataclasses import dataclass
from pathlib import Path

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.egress import EgressPolicy, default_egress_policy
from grafy_core.file_contracts import BUILTIN_FILE_FORMATS, build_extension_table
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.library import LibraryUnitOfWorkPort
from grafy_core.ports.node_secrets import (
    NodeSecretResolverPort,
    UnavailableNodeSecretResolver,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    ArtifactOutputWriter,
    OutputPersister,
)
from grafy_core.runtime.resolvers import Resolver, ResolverRegistry
from grafy_shared.config import ExecutionConfig
from grafy_storage import LocalFileObjectStore

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.runs.node_runner import NodeComputationRunnerFactory
from grafy_api.uploads import UploadService, UploadServiceConfig
from grafy_core.ports.storage import PresigningStorage
from grafy_api.artifacts.service import ArtifactService
from grafy_api.library.folders import LibraryFoldersService
from grafy_api.library.service import LibraryService

logger = logging.getLogger(__name__)

_WORKBENCH_BUCKET = "workbench-artifacts"


@dataclass(frozen=True, slots=True)
class WorkbenchComponents:
    plugin_registry: PluginRegistry
    upload_config: UploadServiceConfig
    uploads: UploadService
    runner_factory: NodeComputationRunnerFactory
    artifacts: ArtifactService
    library: LibraryService
    library_folders: LibraryFoldersService


@dataclass(frozen=True, slots=True)
class ComputationLimits:
    """How much concurrent work one workbench instance is allowed to admit.

    The deployment supplies this from ExecutionConfig; the
    literal defaults keep a standalone composition independent of the operator
    environment instead of silently reading GRAFY_* variables.
    """

    map_max_concurrency: int = 4

    @classmethod
    def from_config(cls, execution: ExecutionConfig) -> "ComputationLimits":
        return cls(
            map_max_concurrency=execution.map_max_concurrency,
        )


def build_workbench_components(
    *,
    plugin_registry: PluginRegistry | None = None,
    workspace: Path,
    limits: ComputationLimits | None = None,
    unit_of_work: LibraryUnitOfWorkPort,
    storage: FileStoragePort | None = None,
    storage_backend: str = "local",
    bucket: str = _WORKBENCH_BUCKET,
    upload_config: UploadServiceConfig | None = None,
    node_secrets: NodeSecretResolverPort | None = None,
    egress_policy: EgressPolicy | None = None,
) -> WorkbenchComponents:
    if plugin_registry is None:
        from grafy_api.services.families import build_application_registry

        plugin_registry = build_application_registry()
    resolved_limits = limits or ComputationLimits()
    resolved_workspace = workspace.expanduser().resolve()
    resolved_unit_of_work = unit_of_work
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
    # Several first-party plugins declare a handler for the same built-in artifact type,
    # and both registries refuse a duplicate registration outright. The first handler for
    # an artifact type serves it and the rest are logged, so a shared format does not
    # make startup fail on the second plugin that can also handle it.
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

    availability = ArtifactAvailability(resolved_unit_of_work)
    artifacts = ArtifactService(
        resolved_unit_of_work,
        resolved_storage,
        availability=availability,
        artifact_types=artifact_types,
        egress_policy=resolved_egress_policy,
    )
    library = LibraryService(
        resolved_unit_of_work,
        artifacts,
        artifact_types=artifact_types,
        storage=resolved_storage,
    )
    library_folders = LibraryFoldersService(resolved_unit_of_work)
    runtime = NodeRuntime(
        materializer=InputMaterializer(resolver_registry),
        persister=OutputPersister(writer_registry),
    )
    runners = NodeComputationRunnerFactory(
        registry=plugin_registry,
        runtime=runtime,
        resolvers=resolver_registry,
        writers=writer_registry,
        unit_of_work=resolved_unit_of_work,
        node_secrets=resolved_node_secrets,
        plugin_context=plugin_context,
        max_map_concurrency=resolved_limits.map_max_concurrency,
    )
    return WorkbenchComponents(
        plugin_registry=plugin_registry,
        upload_config=resolved_upload_config,
        uploads=uploads,
        runner_factory=runners,
        artifacts=artifacts,
        library=library,
        library_folders=library_folders,
    )


__all__ = [
    "ComputationLimits",
    "WorkbenchComponents",
    "build_workbench_components",
]
