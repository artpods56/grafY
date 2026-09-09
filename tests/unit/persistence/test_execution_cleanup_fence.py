import asyncio
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy import select, update

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.manager import RunExecutionManager
from grafy_api.execution.materializations import MaterializationService
from grafy_api.execution.node_execution import NodeExecutionService
from grafy_api.execution.preflight import GraphRunPreflight
from grafy_api.execution.requests import RunRequest
from grafy_api.execution.run_graph import RunGraph
from grafy_api.plugins.runtime.sandbox import (
    PluginSandboxScopeId,
    PluginSandboxCleanupError,
)
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import PlatformPluginActor
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocationReason,
    SystemPluginRevocationDrainError,
)
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.node_secrets import UnavailableNodeSecretResolver
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import ArtifactWriterRegistry, OutputPersister
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_persistence import schema
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_persistence.system_cutover import (
    SystemBaselineCutoverService,
    SystemCutoverCommand,
    SystemCutoverBlockedError,
)
from tests.unit.persistence.test_transient_execution_revocation import (
    execution_database as _execution_database_fixture,
    fence_database as _fence_database_fixture,
)
from grafy_storage import LocalFileObjectStore
from tests.unit.persistence.test_system_cutover import (
    cutover_database as _cutover_database_fixture,
    GRAPH_ID,
    WORKSPACE_ID,
    NOW,
    system_cutover_baseline,
    cutover_rollback_unit,
)

cutover_database = _cutover_database_fixture
execution_database = _execution_database_fixture
fence_database = _fence_database_fixture


class ControlledSandboxCleanup:
    def __init__(self, cancelled: bool) -> None:
        self.error: BaseException | None = (
            asyncio.CancelledError("container removal interrupted")
            if cancelled
            else RuntimeError("container removal failed")
        )
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.attempted = False
        self.scope: PluginSandboxScopeId | None = None

    async def close_scope(self, scope_id: PluginSandboxScopeId, /) -> None:
        self.attempted = True
        self.scope = scope_id
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "cleanup_kind"),
    [
        (mode, kind)
        for mode in ("inline", "transient", "saved")
        for kind in ("error", "cancelled", "success")
    ]
    + [("inline", "caller_cancel"), ("inline", "interrupted")],
)
async def test_cleanup_confirmation_controls_execution_maintenance_fence(
    execution_database: tuple[Database, InstalledPluginRelease],
    tmp_path: Path,
    mode: Literal["inline", "transient", "saved"],
    cleanup_kind: Literal[
        "error", "cancelled", "success", "caller_cancel", "interrupted"
    ],
) -> None:
    database, release = execution_database
    async with database.engine.begin() as connection:
        await connection.execute(
            update(schema.graph_executions).values(status="succeeded", finished_at=NOW)
        )
        empty = SavedGraphDocument(nodes=(), edges=())
        for table in (schema.saved_graphs, schema.saved_graph_revisions):
            await connection.execute(update(table).values(document=empty))
    uow = SqlAlchemyUnitOfWork(database.sessions)
    registry = PluginRegistry()
    storage = LocalFileObjectStore(tmp_path / "objects")
    graphs = SavedGraphService(
        lambda: SqlAlchemyUnitOfWork(database.sessions), registry
    )
    history = ExecutionHistoryService(uow, graphs)
    resolvers = ResolverRegistry([])
    writers = ArtifactWriterRegistry([])
    cleanup = ControlledSandboxCleanup(cleanup_kind == "cancelled")
    if cleanup_kind in {"success", "caller_cancel", "interrupted"}:
        cleanup.error = None
    if cleanup_kind in {"caller_cancel", "interrupted"}:
        cleanup.release.clear()
    runner = RunGraph(
        plugin_sandboxes=cleanup,
        preflight=GraphRunPreflight(plugin_registry=registry, saved_graphs=graphs),
        compiler=GraphCompiler(
            plugin_registry=registry,
            plugin_context=PluginRuntimeContext(
                workspace=tmp_path,
                uploads_dir=tmp_path / "uploads",
                storage=storage,
                uow=uow,
                bucket="plugins",
            ),
            module_library=None,
            canonical_artifact_conversions={},
            build_digest="a" * 64,
        ),
        coordinator=GraphExecutionCoordinator(
            node_execution=NodeExecutionService(
                runtime=NodeRuntime(
                    materializer=InputMaterializer(resolvers),
                    persister=OutputPersister(writers),
                ),
                edge_values=EdgeValueResolver(
                    resolvers=resolvers, writers=writers, unit_of_work=uow
                ),
                node_secrets=UnavailableNodeSecretResolver(),
            )
        ),
        materializations=MaterializationService(
            uow, ArtifactAvailability(uow, storage), graphs
        ),
    )
    manager = RunExecutionManager(runner, execution_history=history)
    request = RunRequest(
        nodes=[],
        graph_id=GRAPH_ID if mode == "saved" else None,
        graph_revision=7 if mode == "saved" else None,
    )
    execution_id = None
    inline_task = None
    try:
        async with asyncio.timeout(5):
            if mode == "inline":
                if cleanup_kind in {"caller_cancel", "interrupted"}:
                    inline_task = asyncio.create_task(
                        manager.run_inline(WORKSPACE_ID, request)
                    )
                    await cleanup.started.wait()
                    inline_task.cancel()
                    # Let the caller enter RunGraph's shielded-cleanup cancellation handler.
                    await asyncio.sleep(0)
                    if cleanup_kind == "caller_cancel":
                        cleanup.release.set()
                        with pytest.raises(asyncio.CancelledError):
                            await inline_task
                    else:
                        inline_task.cancel()
                        with pytest.raises(PluginSandboxCleanupError) as interrupted:
                            await inline_task
                        assert interrupted.value.scope_id == cleanup.scope
                        assert isinstance(
                            interrupted.value.__cause__, asyncio.CancelledError
                        )
                elif cleanup_kind == "success":
                    inline_result = await manager.run_inline(WORKSPACE_ID, request)
                    assert inline_result.status == "succeeded"
                else:
                    with pytest.raises(PluginSandboxCleanupError) as failure:
                        await manager.run_inline(WORKSPACE_ID, request)
                    assert failure.value.scope_id == cleanup.scope
                    assert failure.value.__cause__ is cleanup.error
            else:
                snapshot = await manager.start(WORKSPACE_ID, request)
                execution_id = snapshot.execution_id
                subscription = await manager.subscribe_events(
                    WORKSPACE_ID, snapshot.execution_id
                )
                sequence = 0
                while True:
                    batch = await subscription.wait(after_sequence=sequence)
                    if batch.terminal:
                        break
                    if batch.events:
                        sequence = batch.events[-1].sequence
                result = await manager.get(WORKSPACE_ID, execution_id)
                assert result.status == (
                    "succeeded" if cleanup_kind == "success" else "failed"
                )
                if cleanup_kind != "success":
                    assert (
                        result.error is not None
                        and "remains active for maintenance" in result.error
                    )
            assert cleanup.attempted
            assert cleanup.scope is not None
            releases = PluginReleaseService(
                lambda: SqlAlchemyUnitOfWork(database.sessions),
                storage,
                bucket="plugins",
            )
            if cleanup_kind in {"success", "caller_cancel"}:
                async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
                    assert await transaction.execution_history.list_transient() == ()
                await releases.revoke_system(
                    slug=release.release.slug,
                    revision=release.release.revision,
                    reason=PluginReleaseRevocationReason.SECURITY,
                    platform_actor=PlatformPluginActor("cli:cleanup-fence"),
                )
                if mode == "saved":
                    assert execution_id is not None
                    saved = await history.get_for_graph(
                        WORKSPACE_ID, GRAPH_ID, execution_id
                    )
                    assert saved is not None and saved.execution.status == "succeeded"
                return
            with pytest.raises(SystemPluginRevocationDrainError) as blocked:
                await releases.revoke_system(
                    slug=release.release.slug,
                    revision=release.release.revision,
                    reason=PluginReleaseRevocationReason.SECURITY,
                    platform_actor=PlatformPluginActor("cli:cleanup-fence"),
                )
            assert (
                await releases.get_system_revocation(
                    slug=release.release.slug, revision=release.release.revision
                )
                is None
            )
            async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
                activity = await transaction.execution_history.list_transient()
            assert len(activity) == 1
            assert activity[0].workspace_id == WORKSPACE_ID
            assert [item.execution_id for item in blocked.value.active_executions] == [
                activity[0].execution_id
            ]
            with pytest.raises(SystemCutoverBlockedError) as cutover:
                await SystemBaselineCutoverService(database.sessions).execute(
                    SystemCutoverCommand(
                        mode="dry-run",
                        baseline=system_cutover_baseline(release),
                        rollback_unit=cutover_rollback_unit(),
                    )
                )
            assert str(cutover.value).count(str(activity[0].execution_id)) == 1
            with pytest.raises(RuntimeError, match="requires exclusive API ownership"):
                await history.recover_transient(
                    exclusive_owner=False, orphan_cleanup_confirmed=False
                )
            if mode == "saved":
                assert execution_id is not None
                async with database.engine.connect() as connection:
                    active = (
                        await connection.execute(
                            select(schema.graph_executions.c.status).where(
                                schema.graph_executions.c.execution_id == execution_id
                            )
                        )
                    ).scalar_one()
                assert active in {"running", "cancelling"}
            # Terminalizing saved history cannot bypass the surviving activity marker.
            await history.interrupt_started()
            with pytest.raises(SystemPluginRevocationDrainError):
                await releases.revoke_system(
                    slug=release.release.slug,
                    revision=release.release.revision,
                    reason=PluginReleaseRevocationReason.SECURITY,
                    platform_actor=PlatformPluginActor("cli:cleanup-fence"),
                )
            cleanup.error = None
            cleanup.release.set()
            await cleanup.close_scope(cleanup.scope)
            assert (
                await history.recover_transient(
                    exclusive_owner=True, orphan_cleanup_confirmed=True
                )
                == 1
            )
            await releases.revoke_system(
                slug=release.release.slug,
                revision=release.release.revision,
                reason=PluginReleaseRevocationReason.SECURITY,
                platform_actor=PlatformPluginActor("cli:cleanup-fence"),
            )
    finally:
        cleanup.release.set()
        if inline_task is not None and not inline_task.done():
            inline_task.cancel()
            await asyncio.gather(inline_task, return_exceptions=True)
        await manager.shutdown()
