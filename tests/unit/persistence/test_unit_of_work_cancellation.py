"""A unit of work that is cancelled still owes its connection back.

Closing an async SQLAlchemy session is work on the driver's own thread. A cancellation that
arrives partway through it returns neither the connection nor the thread, and an
exception-handler-shaped `finally` is no defence under a task group: anyio re-delivers the
cancellation at every await the cleanup performs. A CI job ended that way — `Exception
terminating connection` in one test's log section, and its test thread parked in
`Future.result()` on the next request that needed a connection from that pool.

These tests are the boundary where that is either true or not true. Nothing in them is timed:
the body parks on an event nobody sets, so only the cancellation ends it, and the task group
joins its worker before the pool is read.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import anyio
import pytest
from sqlalchemy import text

from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork


@pytest.mark.parametrize("owner", ["database", "unit_of_work"])
def test_a_unit_of_work_cancelled_by_its_task_group_returns_its_connection(
    tmp_path: Path, owner: str
) -> None:
    """The close survives, whoever holds it.

    `database` is how the application is wired: an interrupted close belongs to the database and
    is settled before its engine is disposed. `unit_of_work` is one built on its own, which must
    not be any worse off for having no database to lean on.
    """

    database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'uow.db'}")
    pool = database.engine.pool
    held_cleanups = database.cleanups if owner == "database" else None
    in_the_transaction = asyncio.Event()
    never_released = asyncio.Event()

    async def main() -> None:
        scopes: list[anyio.CancelScope] = []
        unit_of_work = SqlAlchemyUnitOfWork(database.sessions, cleanups=held_cleanups)
        owed = held_cleanups or unit_of_work.session_cleanups

        async def worker() -> None:
            with anyio.CancelScope() as scope:
                scopes.append(scope)
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

            # Reached only after the worker is gone: the request was cancelled and returned, so a
            # close still owed here is one that was handed over rather than one still in hand.
            await owed.settle()
            assert pool.checkedout() == 0, pool.status()
        finally:
            await database.dispose()

    anyio.run(main)


def test_a_finished_unit_of_work_leaves_nothing_to_settle(tmp_path: Path) -> None:
    """The ordinary way out is still ordinary.

    Handing every close to a task of its own would make the common path asynchronous behind
    everyone's back. An uncancelled unit of work returns its connection itself and leaves its
    owner with nothing to settle.
    """

    database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'plain.db'}")
    pool = database.engine.pool
    cleanups = database.cleanups

    async def main() -> None:
        unit_of_work = SqlAlchemyUnitOfWork(database.sessions, cleanups=cleanups)
        async with unit_of_work:
            state = unit_of_work._entered_state()  # noqa: SLF001
            assert (await state.session.execute(text("select 1"))).scalar() == 1
        assert pool.checkedout() == 0, pool.status()
        assert cleanups.pending == 0
        await database.dispose()

    anyio.run(main)
