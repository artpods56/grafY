"""Build the API application's identity services and lifespan resources.

The composition root is the only reader of the composed :class:`Settings` object.
Everything below takes one configuration section and hands the resulting value to the
collaborator that owns it, so a service can never reach a knob it does not declare.

Construction order here is the dependency order. In particular ``project_room_hub`` is
built before the workbench components that receive it; it used to be built after
``FastAPI(...)`` and only worked because the lifespan runs after ``create_app`` returns.
"""

import asyncio
import logging
from pathlib import Path

from grafy_core.application.identity import IdentityService
from grafy_core.domain.identity import parse_oidc_domain_workspace_grants
from grafy_core.egress import TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE, EgressPolicy
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import EgressConfig

from grafy_api.app_state import AppIdentity, AppResources
from grafy_api.agents.conversations import AgentConversationService
from grafy_api.agents.keys import AgentKeyService
from grafy_api.agents.models import AgentModelResolver
from grafy_api.agents.publishing import NullAgentTurnPublisher
from grafy_api.agents.turns import AgentService
from grafy_api.services.families import build_application_registry
from grafy_api.node_secrets import NodeSecretService
from grafy_api.realtime.hub import ProjectRoomHub
from grafy_api.realtime.run_events import ProjectRunEvents
from grafy_api.runs.service import RunService
from grafy_api.runs.facts import ApplicationFactsFactory
from grafy_api.runs.persistence import PersistentResultStore, RepositoryProjectDocuments
from grafy_core.kernel.implementation_identity import RegistryImplementationDigests
from grafy_api.services.composition import ComputationLimits, build_workbench_components
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
        return SqlAlchemyUnitOfWork(database.sessions, cleanups=database.cleanups)

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
        return SqlAlchemyUnitOfWork(database.sessions, cleanups=database.cleanups)

    from grafy_core.application.projects import ProjectService
    from grafy_core.application.collaboration import CollaborationService

    projects = ProjectService(new_unit_of_work)
    project_room_hub = ProjectRoomHub.from_settings(settings.realtime)
    collaboration = CollaborationService(
        new_unit_of_work,
        command_hmac_key=settings.keys.resolved_command_hmac_key(),
        command_hmac_key_version=settings.keys.command_hmac_key_version,
    )
    node_secrets = NodeSecretService(
        unit_of_work_factory=new_unit_of_work,
        plugin_registry=registry,
        encryption_key=settings.keys.credential_encryption_key,
    )
    # An Agent's own key is sealed with the same deployment key as a node secret, and
    # its endpoint is dialed against the same egress grants the workbench was built with.
    agent_keys = AgentKeyService(
        unit_of_work_factory=new_unit_of_work,
        encryption_key=settings.keys.credential_encryption_key,
    )
    agent_conversations = AgentConversationService(unit_of_work_factory=new_unit_of_work)
    agent_models = AgentModelResolver(
        settings=settings.agents,
        keys=agent_keys,
        egress_policy=workbench_egress_policy(settings.egress),
    )
    # The turn runtime gets a publisher that counts what it discards. The Project room's
    # `agent.*` frames are the next unit of issue #202, and until they exist a streamed
    # partial has nowhere to go — which is a dropped notification, never a lost turn: the
    # durable message a turn writes is what the reader will be shown either way.
    agent_turns = AgentService(
        unit_of_work_factory=new_unit_of_work,
        models=agent_models,
        publisher=NullAgentTurnPublisher(),
    )
    workbench = build_workbench_components(
        plugin_registry=registry,
        workspace=app.workspace,
        limits=ComputationLimits.from_config(settings.execution),
        unit_of_work=SqlAlchemyUnitOfWork(
            database.sessions, cleanups=database.cleanups
        ),
        storage=storage,
        storage_backend=settings.storage.storage_backend,
        bucket=settings.storage.storage_bucket,
        upload_config=UploadServiceConfig.from_settings(settings.uploads),
        node_secrets=node_secrets,
        egress_policy=workbench_egress_policy(settings.egress),
    )
    digests = RegistryImplementationDigests.from_registry(
        registry, uv_lock=Path(__file__).resolve().parents[5] / "uv.lock"
    )
    runs = RunService(
        documents=RepositoryProjectDocuments(uow_factory=new_unit_of_work),
        uow_factory=new_unit_of_work,
        result_store_factory=lambda workspace_id: PersistentResultStore(
            workspace_id=workspace_id, uow_factory=new_unit_of_work
        ),
        facts=ApplicationFactsFactory(
            registry=registry, digests=digests, secrets=node_secrets
        ),
        runners=workbench.runner_factory,
        events=ProjectRunEvents(hub=project_room_hub, uow_factory=new_unit_of_work),
        concurrency=settings.execution.project_computation_concurrency,
    )
    resources = AppResources(
        database=database,
        workbench=workbench,
        projects=projects,
        runs=runs,
        collaboration=collaboration,
        node_secrets=node_secrets,
        agent_keys=agent_keys,
        agent_conversations=agent_conversations,
        agent_models=agent_models,
        agent_turns=agent_turns,
        project_room_hub=project_room_hub,
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
    del orphan_cleanup_confirmed
    if owner_lease is None:
        # Another process may still own those Runs; only the exclusive owner can
        # tell an orphan from a live computation.
        logger.warning("unfinished_runs_not_interrupted reason=no_exclusive_owner")
        return
    interrupted = await resources.runs.recover_after_restart()
    logger.info("unfinished_runs_interrupted count=%s", len(interrupted))
    # A turn's task died with the process that ran it, so its receipt is what says it was
    # running. Marking it interrupted is what releases the conversation for a new send;
    # leaving it running would hold the thread busy with nothing left to stop.
    interrupted_turns = await resources.agent_turns.recover_after_restart()
    logger.info("unfinished_agent_turns_interrupted count=%s", len(interrupted_turns))


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
