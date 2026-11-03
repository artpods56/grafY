import asyncio
from collections.abc import Coroutine
from contextvars import ContextVar
from dataclasses import dataclass
import logging
from types import TracebackType
from typing import Self, override

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from grafy_core.domain.errors import ConcurrentWriteError
from grafy_core.ports.agent_conversations import (
    AgentConversationRepositoryPort,
    AgentConversationUnitOfWorkPort,
)
from grafy_core.ports.agent_keys import (
    AgentKeyRepositoryPort,
    AgentKeyUnitOfWorkPort,
)
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
    SqlAgentConversationRepository,
    SqlAgentKeyRepository,
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
    agent_keys: AgentKeyRepositoryPort
    agent_conversations: AgentConversationRepositoryPort
    identity: IdentityRepositoryPort
    security_audit: SecurityAuditRepositoryPort
    uploads: UploadRepositoryPort
    library_folders: LibraryFolderRepositoryPort
    collaboration: CollaborationRepositoryPort


logger = logging.getLogger(__name__)

CANCEL_GRACE_SECONDS = 1.0
"""How long an interrupted close is given after it has been told to stop."""

SETTLE_TIMEOUT_SECONDS = 5.0
"""How long a database will wait for an interrupted session close before it gives up.

Reaching the deadline means the driver itself is wedged, which is worth a log line: the
connection is gone either way, and the alternative is a shutdown that never returns.
"""


class PendingSessionCleanups:
    """The sessions an interrupted unit of work still owes the pool.

    A cancellation that reaches a unit of work on its way out must not have to wait for the
    driver — that is a request that cannot die — and it must not drop the close either. An
    async SQLAlchemy session closes on its driver thread, so a dropped close leaves the
    connection checked out for the life of the pool, the aiosqlite worker parked at `tx.get()`,
    and the next checkout from that pool waiting on a request that never returns.

    So the cleanup runs on a task of its own and this is who holds it. Shielding a cleanup and
    then forgetting it is the same leak with better manners: whoever disposes the engine settles
    what is here first, and says so when something refuses to land.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def pending(self) -> int:
        """What still owes the pool something.

        A finished task is dropped by its done-callback, which runs on the next turn of the loop,
        so the set can briefly hold one that has already landed. That is not debt.
        """

        return sum(1 for task in self._tasks if not task.done())

    def spawn(
        self, coroutine: Coroutine[None, None, None], *, name: str
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._observed)
        return task

    def _observed(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            logger.warning("unit_of_work_cleanup_cancelled name=%s", task.get_name())
            return
        failure = task.exception()
        if failure is not None:
            logger.warning(
                "unit_of_work_cleanup_failed name=%s error_type=%s",
                task.get_name(),
                type(failure).__name__,
            )

    async def settle(self, *, timeout: float = SETTLE_TIMEOUT_SECONDS) -> None:
        """Wait for what is still closing, then report whatever would not come back."""

        self._tasks = {task for task in self._tasks if not task.done()}
        live = list(self._tasks)
        if not live:
            return
        try:
            _, pending = await asyncio.wait(live, timeout=timeout)
        except ValueError:
            # Tasks belonging to a loop that has since closed: they are nobody's to await now.
            logger.warning("unit_of_work_cleanup_settle_skipped tasks=%s", len(live))
            return
        for task in pending:
            task.cancel()
        # Awaiting the cancellation is the point, not the courtesy. Whoever closes this loop
        # afterwards cancels whatever is left and waits for it without a deadline of its own, so
        # a close still running at that moment is a teardown that never returns: CI reached
        # exactly that, a test that had already passed, its portal thread parked in
        # `Runner.close` -> `_cancel_all_tasks` -> `gather`, for two minutes and then forever.
        if not pending:
            return
        _, still = await asyncio.wait(pending, timeout=CANCEL_GRACE_SECONDS)
        if still:
            logger.error(
                "unit_of_work_cleanups_abandoned tasks=%s deadline_seconds=%s names=%s",
                len(still),
                timeout,
                sorted(task.get_name() for task in still),
            )


async def _close_session(session: AsyncSession, *, rollback: bool) -> None:
    try:
        if rollback:
            await session.rollback()
    finally:
        await session.close()


class SqlAlchemyUnitOfWork(
    LibraryUnitOfWorkPort,
    WorkbenchUnitOfWorkPort,
    ProjectUnitOfWorkPort,
    RunUnitOfWorkPort,
    NodeSecretUnitOfWorkPort,
    AgentKeyUnitOfWorkPort,
    AgentConversationUnitOfWorkPort,
    IdentityUnitOfWorkPort,
    UploadUnitOfWorkPort,
    CollaborationUnitOfWorkPort,
):
    """Task-local transactions for Projects, Runs, results, and Workspace-owned data."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cleanups: PendingSessionCleanups | None = None,
    ) -> None:
        self._session_factory = session_factory
        # Whoever holds a close this unit of work could not finish. A database passes its own so
        # that an interrupted close is settled before the engine is disposed; on its own a unit
        # of work keeps them here, which is still an owner that outlives the request.
        self._cleanups = cleanups if cleanups is not None else PendingSessionCleanups()
        self._state: ContextVar[_SqlAlchemyUnitOfWorkState | None] = ContextVar(
            "grafy_sqlalchemy_unit_of_work_state", default=None
        )

    @property
    def session_cleanups(self) -> PendingSessionCleanups:
        """Whoever holds a close this unit of work could not finish."""

        return self._cleanups

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
    def agent_keys(self) -> AgentKeyRepositoryPort:
        return self._entered_state().agent_keys

    @property
    @override
    def agent_conversations(self) -> AgentConversationRepositoryPort:
        return self._entered_state().agent_conversations

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
                agent_keys=SqlAgentKeyRepository(session),
                agent_conversations=SqlAgentConversationRepository(session),
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
        self._state.set(None)
        cleanup = self._cleanups.spawn(
            _close_session(state.session, rollback=exc_type is not None),
            name="unit-of-work-cleanup",
        )
        # The close runs on a task either way, and this awaits it while it is allowed to. When the
        # cancellation arrives the request lets go at once — holding a dying request to the driver
        # is how one room's teardown stalled a whole suite — and the close stays with the owner of
        # this database instead of being lost with the task that was cancelled.
        await asyncio.shield(cleanup)

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
