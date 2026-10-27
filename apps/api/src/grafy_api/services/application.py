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
from pathlib import Path

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.identity import IdentityService
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.identity import parse_oidc_domain_workspace_grants
from grafy_core.egress import TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE, EgressPolicy
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import EgressConfig

from grafy_api.app_state import AppIdentity, AppResources
from grafy_api.services.families import build_application_registry
from grafy_api.node_secrets import NodeSecretService
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


def workbench_egress_policy(egress: EgressConfig) -> EgressPolicy:
    """The grants the workbench dials node-named destinations against.

    Built while the app starts, so a destination the egress authority cannot read
    fails the deployment here and names the variable the operator set, instead of
    failing the first node that names the destination.
    """

    try:
        return EgressPolicy.from_destinations(egress.egress_trusted_destinations)
    except ValueError as exc:
        raise ValueError(
            f"{TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE} is not usable: {exc}"
        ) from exc


async def build_app_resources(
    *,
    settings: Settings,
    database: Database,
    owner_lease: ApiOwnerLease | None,
) -> AppResources:
    """Construct every lifespan resource and recover its execution state.

    On any recovery failure the partially built resources are torn down before the
    error propagates, so a refused startup leaves no active execution or room.
    """

    app = settings.app
    registry = build_application_registry()
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
        encryption_key=settings.keys.credential_encryption_key,
    )
    resources = AppResources(
        database=database,
        workbench=build_workbench_components(
            plugin_registry=registry,
            workspace=app.workspace,
            limits=ExecutionLimits.from_config(settings.execution),
            unit_of_work=SqlAlchemyUnitOfWork(database.sessions),
            storage=storage,
            storage_backend=settings.storage.storage_backend,
            bucket=settings.storage.storage_bucket,
            upload_config=UploadServiceConfig.from_settings(settings.uploads),
            saved_graphs=saved_graphs,
            module_library=module_library,
            plugin_releases=plugin_releases,
            node_secrets=node_secrets,
            graph_room_hub=graph_room_hub,
            egress_policy=workbench_egress_policy(settings.egress),
            build_digest=app.resolved_build_digest,
        ),
        saved_graphs=saved_graphs,
        collaboration=collaboration,
        node_secrets=node_secrets,
        graph_room_hub=graph_room_hub,
    )
    try:
        await _recover(
            resources,
            owner_lease=owner_lease,
            orphan_cleanup_confirmed=True,
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
