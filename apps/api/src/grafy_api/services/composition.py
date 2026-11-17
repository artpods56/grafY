"""Composition root for workbench-facing application components."""

from dataclasses import dataclass
from pathlib import Path

from grafy_core.egress import EgressPolicy, default_egress_policy
from grafy_core.documents import FILE_ARTIFACTS
from grafy_core.file_contracts import BUILTIN_FILE_FORMATS, build_extension_table
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.library import LibraryUnitOfWorkPort
from grafy_core.ports.node_secrets import (
    NodeSecretResolverPort,
    UnavailableNodeSecretResolver,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.port_check import check_port_declarations
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import OutputPersister
from grafy_shared.config import ExecutionConfig
from grafy_storage import LocalFileObjectStore

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.runs.node_runner import NodeComputationRunnerFactory
from grafy_api.uploads import UploadService, UploadServiceConfig
from grafy_core.ports.storage import PresigningStorage
from grafy_api.artifacts.content import ArtifactContentService
from grafy_api.artifacts.images import ArtifactImageService
from grafy_api.artifacts.tiler_client import HttpTiler
from grafy_shared.config.tiler import TilerConfig
from grafy_api.artifacts.geo import ArtifactGeoService
from grafy_api.artifacts.geo_tiles import ArtifactGeoTileService
from grafy_api.artifacts.tables import ArtifactTableService
from grafy_api.artifacts.wms import WmsTileClient
from grafy_api.library.folders import LibraryFoldersService
from grafy_api.library.service import LibraryService

_WORKBENCH_BUCKET = "workbench-artifacts"


@dataclass(frozen=True, slots=True)
class WorkbenchComponents:
    plugin_registry: PluginRegistry
    upload_config: UploadServiceConfig
    uploads: UploadService
    runner_factory: NodeComputationRunnerFactory
    artifact_content: ArtifactContentService
    artifact_images: ArtifactImageService
    artifact_tables: ArtifactTableService
    artifact_geo: ArtifactGeoService
    artifact_geo_tiles: ArtifactGeoTileService
    wms: WmsTileClient
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
    tiler_config: TilerConfig | None = None,
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
    uow = unit_of_work
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
        unit_of_work_factory=lambda: uow,
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
    values = ArtifactValues(
        (*FILE_ARTIFACTS, *plugin_registry.artifacts),
        uow=uow,
        storage=resolved_storage,
        bucket=bucket,
        storage_backend=storage_backend,
    )
    check_port_declarations(plugin_registry.nodes, values)
    plugin_context = PluginRuntimeContext(
        workspace=resolved_workspace,
        storage=resolved_storage,
        uow=uow,
        bucket=bucket,
        storage_backend=storage_backend,
        artifact_types=tuple(artifact_types.values()),
        node_secrets=resolved_node_secrets,
        values=values,
    )

    availability = ArtifactAvailability(uow)
    wms = WmsTileClient(egress_policy=resolved_egress_policy)
    artifact_content = ArtifactContentService(
        uow,
        resolved_storage,
        artifact_types=artifact_types,
    )
    artifact_tables = ArtifactTableService(uow, resolved_storage)
    artifact_geo = ArtifactGeoService(
        uow,
        resolved_storage,
        availability=availability,
    )
    artifact_geo_tiles = ArtifactGeoTileService(
        uow,
        resolved_storage,
        availability=availability,
        wms=wms,
    )
    library = LibraryService(
        uow,
        artifact_content,
        artifact_types=artifact_types,
        storage=resolved_storage,
    )
    library_folders = LibraryFoldersService(uow)
    runtime = NodeRuntime(
        materializer=InputMaterializer(values),
        persister=OutputPersister(values),
    )
    runners = NodeComputationRunnerFactory(
        registry=plugin_registry,
        runtime=runtime,
        node_secrets=resolved_node_secrets,
        plugin_context=plugin_context,
        values=values,
        max_map_concurrency=resolved_limits.map_max_concurrency,
    )
    resolved_tiler_config = (
        tiler_config if tiler_config is not None else TilerConfig.model_construct()
    )
    return WorkbenchComponents(
        plugin_registry=plugin_registry,
        upload_config=resolved_upload_config,
        uploads=uploads,
        runner_factory=runners,
        artifact_content=artifact_content,
        artifact_images=ArtifactImageService(
            uow, resolved_tiler_config, HttpTiler(resolved_tiler_config)
        ),
        artifact_tables=artifact_tables,
        artifact_geo=artifact_geo,
        artifact_geo_tiles=artifact_geo_tiles,
        wms=wms,
        library=library,
        library_folders=library_folders,
    )


__all__ = [
    "ComputationLimits",
    "WorkbenchComponents",
    "build_workbench_components",
]
