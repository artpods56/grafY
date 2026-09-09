"""Diagnostic for the known transient revocation gap; uses a disposable database.

Run from the repository root:
    PYTHONPATH=. .venv/bin/python docs/plans/backend-cleanup/reproduce-transient-revocation.py

Successful reproduction exits zero. Once the fence is implemented, replace this
with a regression asserting revocation is rejected while the run is active.
"""

import asyncio
import tempfile
from pathlib import Path
from sqlalchemy import update
from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.manager import RunExecutionManager
from grafy_api.execution.requests import RunRequest
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.plugin_releases import PlatformPluginActor
from grafy_core.domain.plugin_revocations import PluginReleaseRevocationReason
from grafy_persistence import schema
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from tests.unit.api.runtime.test_execution_manager import ControlledRunGraph
from tests.unit.persistence.test_system_cutover import (
    cutover_database,
    WORKSPACE_ID,
    NOW,
)


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fixture = cutover_database.__wrapped__(root)
        database, release = await anext(fixture)
        runner = ControlledRunGraph()
        manager = RunExecutionManager(
            runner,
            execution_history=ExecutionHistoryService(
                SqlAlchemyUnitOfWork(database.sessions), None
            ),
        )
        try:
            async with database.engine.begin() as connection:
                await connection.execute(
                    update(schema.graph_executions).values(
                        status="succeeded", finished_at=NOW
                    )
                )
            snapshot = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
            await asyncio.wait_for(runner.started.wait(), timeout=5)
            async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
                active = await transaction.plugin_releases.lock_system_revocation()
            assert active == (), active
            releases = PluginReleaseService(
                lambda: SqlAlchemyUnitOfWork(database.sessions),
                LocalFileObjectStore(root / "objects"),
                bucket="plugins",
            )
            revoked = await releases.revoke_system(
                slug=release.release.slug,
                revision=release.release.revision,
                reason=PluginReleaseRevocationReason.SECURITY,
                platform_actor=PlatformPluginActor("cli:reproduction"),
            )
            assert not runner.release.is_set()
            assert revoked is not None
            print(
                f"REPRODUCED: transient execution {snapshot.execution_id} is paused inside run(), SQL drain returned no active executions, and System revocation committed."
            )
        finally:
            runner.release.set()
            await manager.shutdown()
            await fixture.aclose()


asyncio.run(main())
