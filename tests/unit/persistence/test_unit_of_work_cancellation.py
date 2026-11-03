"""A unit of work that is cancelled still owes its connection back.

Closing an async SQLAlchemy session is work on the driver's own thread. A cancellation that
arrives partway through it returns neither the connection nor the thread, and an
exception-handler-shaped `finally` is no defence under a task group: anyio re-delivers the
cancellation at every await the cleanup performs. This suite is the boundary where that is
either true or not true.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import anyio
from sqlalchemy import text

from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork


def test_a_unit_of_work_cancelled_by_its_task_group_returns_its_connection(
    tmp_path: Path,
) -> None:
    """The cancellation is the mechanism; nothing here is timed.

    The body parks on an event that nobody sets, so the only way it ends is the scope being
    cancelled, and the task group waits for the worker before the pool is read. A connection
    still checked out at that point was abandoned, not lent.
    """

    database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'uow.db'}")
    pool = database.engine.pool
    in_the_transaction = asyncio.Event()
    never_released = asyncio.Event()

    async def main() -> None:
        scopes: list[anyio.CancelScope] = []

        async def worker() -> None:
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
                async with unit_of_work:
                    state = unit_of_work._entered_state()  # noqa: SLF001
                    await state.session.execute(text("select 1"))
                    in_the_transaction.set()
                    await never_released.wait()

        try:
            async with anyio.create_task_group() as group:
                group.start_soon(worker)
                await in_the_transaction.wait()
                scopes[0].cancel()

            assert pool.checkedout() == 0, pool.status()
        finally:
            await database.engine.dispose()

    anyio.run(main)
