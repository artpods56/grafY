"""Build the API application's identity services and lifespan resources.

The composition root is the only reader of the composed :class:`Settings` object.
Everything below takes one configuration section and hands the resulting value to the
collaborator that owns it, so a service can never reach a knob it does not declare.

Construction order here is the dependency order. In particular ``graph_room_hub`` is
built before the workbench components that receive it; it used to be built after
``FastAPI(...)`` and only worked because the lifespan runs after ``create_app`` returns.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.identity import IdentityService
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.application.templates import TemplateService
from grafy_core.domain.identity import parse_oidc_domain_workspace_grants
from grafy_core.ports.storage import FileStoragePort
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_workbench import BuiltinNodeCatalog
from grafy_workbench.catalog import BUILTIN_FAMILIES

from grafy_api.app_state import AppIdentity, AppResources
from grafy_api.dev_plugins import DevPluginError, load_dev_plugins
from grafy_api.node_secrets import NodeSecretService
from grafy_api.plugins.profiles import runtime_profile
from grafy_api.plugins.runtime.docker import DockerPluginRuntime
from grafy_api.plugins.runtime.egress import PluginEgressBrokerPolicy
from grafy_api.plugins.runtime.network_policy import NetworkPolicy
from grafy_api.realtime.hub import GraphRoomHub
from grafy_api.services.composition import ExecutionLimits, build_workbench_components
from grafy_api.settings import Settings
from grafy_api.single_owner import ApiOwnerLease
from grafy_api.storage import configured_file_storage
from grafy_api.uploads import UploadServiceConfig
from grafy_api.v1.routes.auth.services import AuthService

logger = logging.getLogger(__name__)


def acquire_api_owner_lease(workspace: Path, *, required: bool) -> ApiOwnerLease | None:
    """Take the process-wide owner lock when the deployment demands one owner."""

    if not required:
        return None
    lease = ApiOwnerLease(workspace / ".grafy-api-owner.lock")
    lease.acquire()
    return lease


def build_app_identity(settings: Settings, database: Database) -> AppIdentity:
    """Build the app-lifetime identity and auth services.

    These exist before the lifespan starts because FastAPI wires them as request
    dependencies, and a dependency may run before the first startup event.
    """

    def identity_uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    identity_service = IdentityService(
        identity_uow_factory,
        # grafy-shared is a leaf package, so the raw deployment grants are parsed here
        # rather than inside AuthConfig.
        domain_workspace_grants=parse_oidc_domain_workspace_grants(
            settings.auth.oidc_domain_workspaces
        ),
    )
    auth_service = AuthService(
        auth=settings.auth,
        public_origin=settings.app.public_origin,
        unit_of_work_factory=identity_uow_factory,
        identity_service=identity_service,
    )
    return AppIdentity(
        identity_uow_factory=identity_uow_factory,
        identity_service=identity_service,
        auth_service=auth_service,
        public_origin=settings.app.public_origin,
    )


@dataclass(slots=True)
class _RuntimeStartup:
    plugin_runtime: DockerPluginRuntime | None
    orphan_cleanup_confirmed: bool


async def _build_plugin_runtime(
    *,
    settings: Settings,
    storage: FileStoragePort,
    releases: PluginReleaseService,
    egress_policy: PluginEgressBrokerPolicy,
    network_policy: NetworkPolicy,
    owner_lease: ApiOwnerLease | None,
) -> _RuntimeStartup:
    """Build and ready the host Docker sandbox, or report it is not enabled."""

    plugins = settings.plugins
    if not plugins.plugin_runtime_enabled:
        return _RuntimeStartup(plugin_runtime=None, orphan_cleanup_confirmed=False)

    seccomp_profile = plugins.resolved_seccomp_profile
    if seccomp_profile is not None and not seccomp_profile.is_file():
        raise RuntimeError("Configured Plugin seccomp profile is not a regular file")
    plugin_runtime = DockerPluginRuntime(
        releases=releases,
        storage=storage,
        bucket=settings.storage.storage_bucket,
        profile=runtime_profile(
            plugins.plugin_runtime_profile,
            native_base_image=plugins.plugin_runtime_native_base_image,
            native_base_image_digest=plugins.plugin_runtime_native_base_image_digest,
        ),
        scratch_root=settings.app.workspace / "plugin-runtime" / "scratch",
        docker_binary=plugins.plugin_docker_binary,
        seccomp_profile=seccomp_profile,
        max_live_sandboxes=plugins.max_live_plugin_sandboxes,
        max_distinct_releases_per_scope=(
            plugins.max_distinct_plugin_releases_per_graph
        ),
        max_sandbox_variants_per_scope=(
            plugins.max_plugin_sandbox_variants_per_execution
        ),
        egress_policy=egress_policy,
        network_policy=network_policy,
    )
    await plugin_runtime.check_ready()
    orphan_cleanup_confirmed = False
    if owner_lease is not None:
        await plugin_runtime.recover_orphans()
        orphan_cleanup_confirmed = True
    for profile in network_policy.profiles:
        logger.info(
            "network_profile plane=%s name=%s mode=%s digest=%s",
            profile.plane.value,
            profile.name,
            profile.mode.value,
            profile.policy_digest,
        )
    return _RuntimeStartup(
        plugin_runtime=plugin_runtime,
        orphan_cleanup_confirmed=orphan_cleanup_confirmed,
    )


async def build_app_resources(
    *,
    settings: Settings,
    database: Database,
    egress_policy: PluginEgressBrokerPolicy,
    owner_lease: ApiOwnerLease | None,
) -> AppResources:
    """Construct every lifespan resource and recover its execution state.

    On any recovery failure the partially built resources are torn down before the
    error propagates, so a refused startup leaves no sandbox or room behind.
    """

    app = settings.app
    if app.environment == "production" and settings.plugins.dev_plugins:
        raise DevPluginError(
            "GRAFY_DEV_PLUGINS is development-only and cannot run in production"
        )
    dev_plugins = load_dev_plugins(settings.plugins.dev_plugins)
    registry = BuiltinNodeCatalog.load(
        app.resolved_build_digest, families=(*BUILTIN_FAMILIES, *dev_plugins)
    ).registry
    storage = configured_file_storage(settings.storage, app.workspace)

    def new_unit_of_work() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    saved_graphs = SavedGraphService(new_unit_of_work, registry)
    module_library = ModuleLibraryService(new_unit_of_work, registry)
    plugin_releases = PluginReleaseService(
        new_unit_of_work,
        storage,
        bucket=settings.storage.storage_bucket,
    )
    graph_room_hub = GraphRoomHub.from_settings(settings.realtime)
    network_policy = NetworkPolicy.from_config(settings.egress)
    runtime_startup = await _build_plugin_runtime(
        settings=settings,
        storage=storage,
        releases=plugin_releases,
        egress_policy=egress_policy,
        network_policy=network_policy,
        owner_lease=owner_lease,
    )
    templates = TemplateService(new_unit_of_work)
    collaboration = CollaborationService(
        new_unit_of_work,
        registry,
        command_hmac_key=settings.keys.resolved_command_hmac_key(),
        command_hmac_key_version=settings.keys.command_hmac_key_version,
        saved_graphs=saved_graphs,
    )
    node_secrets = NodeSecretService(
        unit_of_work_factory=new_unit_of_work,
        plugin_registry=registry,
        plugin_release_lookup=plugin_releases,
        encryption_key=settings.keys.credential_encryption_key,
    )
    resources = AppResources(
        database=database,
        workbench=build_workbench_components(
            plugin_registry=registry,
            dev_plugin_slugs=frozenset(plugin.slug for plugin in dev_plugins),
            dedupe_artifact_handlers=bool(dev_plugins),
            workspace=app.workspace,
            limits=ExecutionLimits.from_config(settings.execution, settings.plugins),
            unit_of_work=SqlAlchemyUnitOfWork(database.sessions),
            storage=storage,
            storage_backend=settings.storage.storage_backend,
            bucket=settings.storage.storage_bucket,
            upload_config=UploadServiceConfig.from_settings(settings.uploads),
            saved_graphs=saved_graphs,
            module_library=module_library,
            plugin_releases=plugin_releases,
            plugin_runtime=runtime_startup.plugin_runtime,
            node_secrets=node_secrets,
            graph_room_hub=graph_room_hub,
            network_policy=network_policy,
            build_digest=app.resolved_build_digest,
        ),
        templates=templates,
        saved_graphs=saved_graphs,
        collaboration=collaboration,
        node_secrets=node_secrets,
        graph_room_hub=graph_room_hub,
    )
    try:
        await _recover(
            resources,
            owner_lease=owner_lease,
            orphan_cleanup_confirmed=runtime_startup.orphan_cleanup_confirmed,
        )
    except BaseException:
        await resources.cleanup()
        raise
    return resources


async def _recover(
    resources: AppResources,
    *,
    owner_lease: ApiOwnerLease | None,
    orphan_cleanup_confirmed: bool = False,
) -> None:
    components = resources.workbench
    await components.execution_history.recover_transient(
        exclusive_owner=owner_lease is not None,
        orphan_cleanup_confirmed=orphan_cleanup_confirmed,
    )
    await components.execution_history.interrupt_started()
    await components.execution_manager.recover_queued()
    capacity = await resources.capacity_diagnostics()
    logger.info(
        "capacity_diagnostics active_executions=%s "
        "max_active_executions=%s pending_graphs=%s "
        "max_pending_graphs=%s active_plugin_invocations=%s "
        "max_active_plugin_invocations=%s live_plugin_sandboxes=%s "
        "max_live_plugin_sandboxes=%s",
        capacity.execution_admission.active_executions,
        capacity.execution_admission.max_active_executions,
        capacity.execution_queue.pending_graphs,
        capacity.execution_queue.max_pending_graphs,
        (
            None
            if capacity.plugin_invocations is None
            else capacity.plugin_invocations.active_invocations
        ),
        (
            None
            if capacity.plugin_invocations is None
            else capacity.plugin_invocations.max_active_invocations
        ),
        (
            None
            if capacity.plugin_sandboxes is None
            else capacity.plugin_sandboxes.live_sandboxes
        ),
        (
            None
            if capacity.plugin_sandboxes is None
            else capacity.plugin_sandboxes.max_live_sandboxes
        ),
    )
    # Migration 0009 backfills heads; refuse to serve if any graph still lacks one.
    await resources.collaboration.verify_every_graph_has_head()


async def run_periodic_cleanup(
    *,
    settings: Settings,
    auth_service: AuthService,
    resources: AppResources,
) -> None:
    """One maintenance interval for every periodic sweep."""

    cleanups = (
        ("auth_cleanup_failed", "cleanup_expired", auth_service.cleanup_expired),
        (
            "upload_cleanup_failed",
            "cleanup_abandoned",
            resources.workbench.uploads.cleanup_abandoned,
        ),
    )
    while True:
        await asyncio.sleep(settings.auth.auth_cleanup_interval_seconds)
        for event, operation, cleanup in cleanups:
            try:
                _ = await cleanup()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "%s operation=%s error_class=%s",
                    event,
                    operation,
                    type(error).__name__,
                )


__all__ = [
    "acquire_api_owner_lease",
    "build_app_identity",
    "build_app_resources",
    "run_periodic_cleanup",
]
