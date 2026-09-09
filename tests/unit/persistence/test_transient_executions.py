import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
from typing import override

import pytest
from sqlalchemy import update

from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.manager import RunExecutionManager
from grafy_api.execution.control import RunExecutionControl
from grafy_api.execution.models import GraphExecutionResult
from grafy_api.execution.admission import ExecutionAdmissionLimiter
from grafy_api.execution.requests import RunRequest
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.execution_history import TransientExecution
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import PlatformPluginActor
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocationReason,
    SystemPluginRevocationDrainError,
)
from grafy_persistence import schema
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_persistence.system_cutover import (
    SystemBaselineCutoverService,
    SystemCutoverCommand,
    SystemCutoverBlockedError,
)
from grafy_storage import LocalFileObjectStore
from tests.unit.api.runtime.test_execution_manager import ControlledRunGraph
from tests.unit.persistence.test_system_cutover import (
    cutover_database as _cutover_database_fixture,
    WORKSPACE_ID,
    NOW,
    system_cutover_baseline,
    cutover_rollback_unit,
)


cutover_database = _cutover_database_fixture


class FailingRunGraph(ControlledRunGraph):
    @override
    async def run(
        self,
        workspace_id: UUID,
        request: RunRequest,
        control: RunExecutionControl | None = None,
    ) -> GraphExecutionResult:
        await super().run(workspace_id, request, control)
        raise RuntimeError("deliberate execution failure")


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["success", "failure", "cancel", "shutdown"])
async def test_transient_activity_blocks_maintenance_until_task_finishes(
    cutover_database: tuple[Database, InstalledPluginRelease],
    tmp_path: Path,
    finish: str,
) -> None:
    database, release = cutover_database
    async with database.engine.begin() as connection:
        await connection.execute(
            update(schema.graph_executions).values(status="succeeded", finished_at=NOW)
        )
    history = ExecutionHistoryService(SqlAlchemyUnitOfWork(database.sessions), None)
    runner = FailingRunGraph() if finish == "failure" else ControlledRunGraph()
    manager = RunExecutionManager(runner, execution_history=history)
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    try:
        snapshot = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
        async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
            activity = await transaction.execution_history.list_transient()
        assert [row.execution_id for row in activity] == [snapshot.execution_id]
        if finish != "cancel_before_start":
            await asyncio.wait_for(runner.started.wait(), timeout=5)
        with pytest.raises(SystemPluginRevocationDrainError):
            await releases.revoke_system(
                slug=release.release.slug,
                revision=release.release.revision,
                reason=PluginReleaseRevocationReason.SECURITY,
                platform_actor=PlatformPluginActor("cli:test"),
            )
        assert (
            await releases.get_system_revocation(
                slug=release.release.slug, revision=release.release.revision
            )
            is None
        )
        with pytest.raises(SystemCutoverBlockedError, match="drained execution queue"):
            await SystemBaselineCutoverService(database.sessions).execute(
                SystemCutoverCommand(
                    mode="dry-run",
                    baseline=system_cutover_baseline(release),
                    rollback_unit=cutover_rollback_unit(),
                )
            )
        if finish in {"cancel", "cancel_before_start"}:
            await manager.cancel(WORKSPACE_ID, snapshot.execution_id)
        elif finish in {"success", "failure"}:
            runner.release.set()
            events = await manager.subscribe_events(WORKSPACE_ID, snapshot.execution_id)
            async with asyncio.timeout(5):
                sequence = 0
                while True:
                    batch = await events.wait(after_sequence=sequence)
                    if batch.terminal:
                        break
                    if batch.events:
                        sequence = batch.events[-1].sequence
        await manager.shutdown()
        async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
            assert await transaction.execution_history.list_transient() == ()
        await releases.revoke_system(
            slug=release.release.slug,
            revision=release.release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            platform_actor=PlatformPluginActor("cli:test"),
        )
    finally:
        runner.release.set()
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exclusive", "drained"),
    [(False, False), (False, True), (True, False), (True, True)],
)
async def test_transient_recovery_requires_exclusive_owner_and_drained_guests(
    cutover_database: tuple[Database, InstalledPluginRelease],
    exclusive: bool,
    drained: bool,
) -> None:
    database, _ = cutover_database
    history = ExecutionHistoryService(SqlAlchemyUnitOfWork(database.sessions), None)
    execution_id, owner_id = uuid4(), uuid4()
    await history.register_transient(WORKSPACE_ID, execution_id, owner_id)
    if exclusive and drained:
        assert (
            await history.recover_transient(
                exclusive_owner=exclusive, orphan_cleanup_confirmed=drained
            )
            == 1
        )
    else:
        with pytest.raises(RuntimeError, match=str(execution_id)):
            await history.recover_transient(
                exclusive_owner=exclusive, orphan_cleanup_confirmed=drained
            )
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        rows = await transaction.execution_history.list_transient()
    assert bool(rows) is not (exclusive and drained)


@pytest.mark.asyncio
async def test_transient_activity_is_transactional_and_owner_bound(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, _ = cutover_database
    marker = TransientExecution(
        execution_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        owner_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        await transaction.execution_history.add_transient(marker)
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        assert await transaction.execution_history.list_transient() == ()
        await transaction.execution_history.add_transient(marker)
        await transaction.commit()
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        await transaction.execution_history.remove_transient(
            marker.execution_id, uuid4()
        )
        await transaction.commit()
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        assert await transaction.execution_history.list_transient() == (marker,)
        await transaction.execution_history.remove_transient(
            marker.execution_id, marker.owner_id
        )
        await transaction.commit()
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        assert await transaction.execution_history.list_transient() == ()


@pytest.mark.asyncio
async def test_cancellation_before_first_task_step_clears_transient_activity(
    cutover_database: tuple[Database, InstalledPluginRelease],
) -> None:
    database, _ = cutover_database
    runner = ControlledRunGraph()
    manager = RunExecutionManager(
        runner,
        execution_history=ExecutionHistoryService(
            SqlAlchemyUnitOfWork(database.sessions), None
        ),
    )
    try:
        snapshot = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
        await manager.cancel(WORKSPACE_ID, snapshot.execution_id)
        await manager.shutdown()
        assert not runner.started.is_set()
        async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
            assert await transaction.execution_history.list_transient() == ()
    finally:
        runner.release.set()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_transient_admission_failure_prevents_execution_and_returns_capacity(
    cutover_database: tuple[Database, InstalledPluginRelease],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, _ = cutover_database
    history = ExecutionHistoryService(SqlAlchemyUnitOfWork(database.sessions), None)
    original = ExecutionHistoryService.register_transient

    async def committed_then_failed(
        self: ExecutionHistoryService,
        workspace_id: UUID,
        execution_id: UUID,
        owner_id: UUID,
    ) -> None:
        await original(self, workspace_id, execution_id, owner_id)
        raise RuntimeError("commit acknowledgement lost")

    monkeypatch.setattr(
        ExecutionHistoryService, "register_transient", committed_then_failed
    )
    runner = ControlledRunGraph()
    manager = RunExecutionManager(
        runner,
        execution_history=history,
        admission_limiter=ExecutionAdmissionLimiter(1),
    )
    try:
        with pytest.raises(RuntimeError, match="acknowledgement lost"):
            await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
        assert not runner.started.is_set()
        async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
            assert await transaction.execution_history.list_transient() == ()
        monkeypatch.setattr(ExecutionHistoryService, "register_transient", original)
        await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
        await asyncio.wait_for(runner.started.wait(), 5)
    finally:
        runner.release.set()
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("failures", [1, 2])
async def test_transient_terminal_cleanup_retries_and_retains_marker_on_failure(
    cutover_database: tuple[Database, InstalledPluginRelease],
    monkeypatch: pytest.MonkeyPatch,
    failures: int,
) -> None:
    database, _ = cutover_database
    history = ExecutionHistoryService(SqlAlchemyUnitOfWork(database.sessions), None)
    original = ExecutionHistoryService.release_transient
    attempts = 0

    async def fail_release(
        self: ExecutionHistoryService, execution_id: UUID, owner_id: UUID
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts <= failures:
            raise RuntimeError("activity deletion unavailable")
        await original(self, execution_id, owner_id)

    monkeypatch.setattr(ExecutionHistoryService, "release_transient", fail_release)
    runner = ControlledRunGraph()
    manager = RunExecutionManager(runner, execution_history=history)
    try:
        snapshot = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
        await asyncio.wait_for(runner.started.wait(), 5)
        runner.release.set()
        subscription = await manager.subscribe_events(
            WORKSPACE_ID, snapshot.execution_id
        )
        async with asyncio.timeout(5):
            sequence = 0
            while True:
                batch = await subscription.wait(after_sequence=sequence)
                if batch.terminal:
                    break
                if batch.events:
                    sequence = batch.events[-1].sequence
        assert attempts == 2
        current = await manager.get(WORKSPACE_ID, snapshot.execution_id)
        assert current.status == "succeeded"
        async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
            rows = await transaction.execution_history.list_transient()
        assert bool(rows) is (failures == 2)
        if failures == 2:
            assert (
                current.error is not None
                and str(snapshot.execution_id) in current.error
            )
    finally:
        runner.release.set()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_failed_task_creation_clears_registered_activity(
    cutover_database: tuple[Database, InstalledPluginRelease],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, _ = cutover_database
    runner = ControlledRunGraph()
    manager = RunExecutionManager(
        runner,
        execution_history=ExecutionHistoryService(
            SqlAlchemyUnitOfWork(database.sessions), None
        ),
        admission_limiter=ExecutionAdmissionLimiter(1),
    )

    def refuse_task(self: RunExecutionManager, record: object) -> None:
        raise RuntimeError("task creation unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(RunExecutionManager, "_create_run_task_locked", refuse_task)
            with pytest.raises(RuntimeError, match="task creation unavailable"):
                await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
        assert not runner.started.is_set()
        async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
            assert await transaction.execution_history.list_transient() == ()
        await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
        await asyncio.wait_for(runner.started.wait(), 5)
    finally:
        runner.release.set()
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_inline_registration_failure_never_starts_the_executor(
    cutover_database: tuple[Database, InstalledPluginRelease],
    monkeypatch: pytest.MonkeyPatch,
    committed: bool,
    cancelled: bool,
) -> None:
    database, _ = cutover_database
    original = ExecutionHistoryService.register_transient

    async def fail_registration(
        self: ExecutionHistoryService,
        workspace_id: UUID,
        execution_id: UUID,
        owner_id: UUID,
    ) -> None:
        if committed:
            await original(self, workspace_id, execution_id, owner_id)
        if cancelled:
            raise asyncio.CancelledError()
        raise RuntimeError("registration acknowledgement failed")

    monkeypatch.setattr(
        ExecutionHistoryService, "register_transient", fail_registration
    )
    runner = ControlledRunGraph()
    manager = RunExecutionManager(
        runner,
        execution_history=ExecutionHistoryService(
            SqlAlchemyUnitOfWork(database.sessions), None
        ),
    )
    error_type = asyncio.CancelledError if cancelled else RuntimeError
    with pytest.raises(error_type):
        await manager.run_inline(WORKSPACE_ID, RunRequest(nodes=[]))
    assert not runner.started.is_set()
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        assert await transaction.execution_history.list_transient() == ()
    await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("failures", [1, 2])
@pytest.mark.parametrize("execution_fails", [False, True])
async def test_inline_removal_retries_retains_activity_and_preserves_execution_errors(
    cutover_database: tuple[Database, InstalledPluginRelease],
    monkeypatch: pytest.MonkeyPatch,
    failures: int,
    execution_fails: bool,
) -> None:
    database, _ = cutover_database
    original = ExecutionHistoryService.release_transient
    attempts = 0

    async def fail_removal(
        self: ExecutionHistoryService, execution_id: UUID, owner_id: UUID
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts <= failures:
            raise RuntimeError("transient deletion failed")
        await original(self, execution_id, owner_id)

    monkeypatch.setattr(ExecutionHistoryService, "release_transient", fail_removal)
    runner = FailingRunGraph() if execution_fails else ControlledRunGraph()
    runner.release.set()
    manager = RunExecutionManager(
        runner,
        execution_history=ExecutionHistoryService(
            SqlAlchemyUnitOfWork(database.sessions), None
        ),
    )
    if execution_fails:
        with pytest.raises(RuntimeError, match="deliberate execution failure"):
            await manager.run_inline(WORKSPACE_ID, RunRequest(nodes=[]))
    elif failures == 2:
        with pytest.raises(RuntimeError, match="activity marker retained") as failure:
            await manager.run_inline(WORKSPACE_ID, RunRequest(nodes=[]))
        assert str(failure.value.__cause__) == "transient deletion failed"
    else:
        result = await manager.run_inline(WORKSPACE_ID, RunRequest(nodes=[]))
        assert result.status == "succeeded"
    assert attempts == 2
    async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
        activity = await transaction.execution_history.list_transient()
    assert len(activity) == (1 if failures == 2 else 0)
    if activity:
        assert activity[0].workspace_id == WORKSPACE_ID
    await manager.shutdown()
