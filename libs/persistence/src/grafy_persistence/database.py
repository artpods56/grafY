from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from grafy_persistence.unit_of_work import PendingSessionCleanups


def _configure_sqlite_connection(
    connection: DBAPIConnection,
    connection_record: ConnectionPoolEntry,
) -> None:
    del connection_record
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


@dataclass(frozen=True, slots=True)
class Database:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    cleanups: PendingSessionCleanups = field(default_factory=PendingSessionCleanups)
    """Session closes a cancelled unit of work could not finish.

    Passed to the units of work built over this database so that an interrupted close has an
    owner outliving the request that was cancelled, and is settled here rather than lost.
    """

    async def dispose(self) -> None:
        await self.cleanups.settle()
        await self.engine.dispose()


def prepare_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (
        None,
        "",
        ":memory:",
    ):
        Path(url.database).expanduser().resolve().parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    return database_url


def create_database(database_url: str) -> Database:
    from grafy_persistence.orm import start_mappers

    start_mappers()
    prepared_database_url = prepare_database_url(database_url)
    url = make_url(prepared_database_url)

    engine = create_async_engine(
        prepared_database_url,
        pool_pre_ping=True,
    )
    if url.get_backend_name() == "sqlite":
        event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)

    return Database(
        engine=engine,
        sessions=async_sessionmaker(engine, expire_on_commit=False),
    )
