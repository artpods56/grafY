import asyncio
import contextlib
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from types import TracebackType
from typing import Self, override

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from grafy_core.domain.errors import ConcurrentWriteError
from grafy_core.ports.artifacts import ArtifactRepositoryPort
from grafy_core.ports.collaboration import (
    CollaborationRepositoryPort,
    CollaborationUnitOfWorkPort,
)
from grafy_core.ports.identity import (
    IdentityRepositoryPort,
    IdentityUnitOfWorkPort,
    SecurityAuditRepositoryPort,
)
from grafy_core.ports.library_folders import LibraryFolderRepositoryPort
from grafy_core.ports.node_secrets import (
    NodeSecretRepositoryPort,
    NodeSecretUnitOfWorkPort,
)
from grafy_core.ports.projects import ProjectRepositoryPort, ProjectUnitOfWorkPort
from grafy_core.ports.library import LibraryUnitOfWorkPort
from grafy_core.ports.runs import (
    ResultStoreRepositoryPort,
    RunRepositoryPort,
    RunUnitOfWorkPort,
)
from grafy_core.ports.uploads import UploadRepositoryPort, UploadUnitOfWorkPort
from grafy_core.ports.workbench import WorkbenchUnitOfWorkPort

from grafy_persistence.adapters.repositories import (
    SqlProjectRepository,
    SqlArtifactRepository,
    SqlNodeSecretRepository,
    SqlResultStoreRepository,
    SqlRunRepository,
    SqlIdentityRepository,
    SqlSecurityAuditRepository,
    SqlUploadRepository,
    SqlLibraryFolderRepository,
    SqlCollaborationRepository,
)


@dataclass(frozen=True, slots=True)
class _SqlAlchemyUnitOfWorkState:
    session: AsyncSession
    projects: ProjectRepositoryPort
    runs: RunRepositoryPort
    results: ResultStoreRepositoryPort
    artifacts: ArtifactRepositoryPort
    node_secrets: NodeSecretRepositoryPort
    identity: IdentityRepositoryPort
    security_audit: SecurityAuditRepositoryPort
    uploads: UploadRepositoryPort
    library_folders: LibraryFolderRepositoryPort
    collaboration: CollaborationRepositoryPort


logger = logging.getLogger(__name__)

CLEANUP_TIMEOUT_SECONDS = 5.0
"""How long a unit of work keeps trying to hand its connection back.

The attempts are shielded because the cancellation that ends a request does not stop owing
its database anything; the bound is there so a session wedged inside the driver is reported
in this process instead of becoming a task that never finishes.
"""


async def _retire_session(session: AsyncSession, *, rollback: bool) -> None:
    """Roll back and close a session in a way a cancellation cannot interrupt.

    An async SQLAlchemy session is closed by work that runs on the driver's own thread, and
    a task cancelled partway through it neither returns the connection nor releases that
    thread: the pool's terminate fails with the same `CancelledError`, the worker sits at
    `tx.get()` for the rest of the process, and the next checkout from that pool is a request
    that never comes back. Any task-group cancellation reaches a `finally` at every await, so
    the only safe shape is to run the cleanup on a task of its own and keep waiting for it
    through each cancellation aimed at this one.
    """

    async def cleanup() -> None:
        if rollback:
            await session.rollback()
        await session.close()

    task = asyncio.create_task(cleanup(), name="unit-of-work-cleanup")
    cancelled_here = False
    deadline = asyncio.get_running_loop().time() + CLEANUP_TIMEOUT_SECONDS
    while not task.done():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
        except asyncio.TimeoutError:
            break
        except asyncio.CancelledError:
            cancelled_here = True
    if task.done():
        failure = None if task.cancelled() else task.exception()
        if failure is not None:
            logger.warning(
                "unit_of_work_cleanup_failed error_type=%s", type(failure).__name__
            )
    else:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        logger.error(
            "unit_of_work_cleanup_incomplete deadline_seconds=%s",
            CLEANUP_TIMEOUT_SECONDS,
        )
    if cancelled_here:
        raise asyncio.CancelledError


class SqlAlchemyUnitOfWork(
    LibraryUnitOfWorkPort,
    WorkbenchUnitOfWorkPort,
    ProjectUnitOfWorkPort,
    RunUnitOfWorkPort,
    NodeSecretUnitOfWorkPort,
    IdentityUnitOfWorkPort,
    UploadUnitOfWorkPort,
    CollaborationUnitOfWorkPort,
):
    """Task-local transactions for Projects, Runs, results, and Workspace-owned data."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._state: ContextVar[_SqlAlchemyUnitOfWorkState | None] = ContextVar(
            "grafy_sqlalchemy_unit_of_work_state", default=None
        )

    @property
    @override
    def projects(self) -> ProjectRepositoryPort:
        return self._entered_state().projects

    @property
    @override
    def runs(self) -> RunRepositoryPort:
        return self._entered_state().runs

    @property
    @override
    def results(self) -> ResultStoreRepositoryPort:
        return self._entered_state().results

    @property
    @override
    def artifacts(self) -> ArtifactRepositoryPort:
        return self._entered_state().artifacts

    @property
    @override
    def node_secrets(self) -> NodeSecretRepositoryPort:
        return self._entered_state().node_secrets

    @property
    @override
    def identity(self) -> IdentityRepositoryPort:
        return self._entered_state().identity

    @property
    @override
    def security_audit(self) -> SecurityAuditRepositoryPort:
        return self._entered_state().security_audit

    @property
    @override
    def uploads(self) -> UploadRepositoryPort:
        return self._entered_state().uploads

    @property
    @override
    def library_folders(self) -> LibraryFolderRepositoryPort:
        return self._entered_state().library_folders

    @property
    @override
    def collaboration(self) -> CollaborationRepositoryPort:
        return self._entered_state().collaboration

    @override
    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        if self._state.get() is not None:
            raise RuntimeError("Unit of work is already entered in this task")
        session = self._session_factory()
        self._state.set(
            _SqlAlchemyUnitOfWorkState(
                session=session,
                projects=SqlProjectRepository(session),
                runs=SqlRunRepository(session),
                results=SqlResultStoreRepository(session),
                artifacts=SqlArtifactRepository(session),
                node_secrets=SqlNodeSecretRepository(session),
                identity=SqlIdentityRepository(session),
                security_audit=SqlSecurityAuditRepository(session),
                uploads=SqlUploadRepository(session),
                library_folders=SqlLibraryFolderRepository(session),
                collaboration=SqlCollaborationRepository(session),
            )
        )
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        state = self._state.get()
        if state is None:
            return
        try:
            await _retire_session(state.session, rollback=exc_type is not None)
        finally:
            self._state.set(None)

    @override
    async def commit(self) -> None:
        state = self._entered_state()
        try:
            await state.session.commit()
        except StaleDataError as exc:
            await state.session.rollback()
            raise ConcurrentWriteError(
                "The Project changed in another transaction"
            ) from exc

    @override
    async def rollback(self) -> None:
        await self._entered_state().session.rollback()

    def _entered_state(self) -> _SqlAlchemyUnitOfWorkState:
        state = self._state.get()
        if state is None:
            raise RuntimeError("Unit of work is not entered")
        return state

    @classmethod
    def from_factory(cls, session_factory: async_sessionmaker[AsyncSession]) -> Self:
        return cls(session_factory)
