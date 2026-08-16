from contextvars import ContextVar
from dataclasses import dataclass
from types import TracebackType
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from grafy_core.artifacts import ArtifactRepositoryPort
from grafy_core.ports.agent_authoring import (
    AgentAuthoringRepositoryPort,
    AgentAuthoringUnitOfWorkPort,
)
from grafy_core.domain.errors import ConcurrentWriteError
from grafy_core.ports.collaboration import (
    CollaborationRepositoryPort,
    CollaborationUnitOfWorkPort,
)
from grafy_core.ports.execution_history import (
    ExecutionHistoryUnitOfWorkPort,
    GraphExecutionHistoryRepositoryPort,
)
from grafy_core.ports.invocation_cache import InvocationCacheRepositoryPort
from grafy_core.ports.identity import (
    IdentityRepositoryPort,
    IdentityUnitOfWorkPort,
    SecurityAuditRepositoryPort,
)
from grafy_core.ports.materialized_outputs import (
    MaterializedNodeOutputsRepositoryPort,
    WorkbenchUnitOfWorkPort,
)
from grafy_core.ports.node_secrets import (
    NodeSecretRepositoryPort,
    NodeSecretUnitOfWorkPort,
)
from grafy_core.ports.module_library import (
    ModuleLibraryRepositoryPort,
    ModuleLibraryUnitOfWorkPort,
)
from grafy_core.ports.saved_graphs import (
    SavedGraphRepositoryPort,
    SavedGraphUnitOfWorkPort,
)
from grafy_core.ports.staged_uploads import (
    StagedUploadRepositoryPort,
    StagedUploadUnitOfWorkPort,
)
from grafy_core.ports.templates import TemplateRepositoryPort, TemplateUnitOfWorkPort

from grafy_persistence.adapters.repositories import (
    SqlArtifactRepository,
    SqlAgentAuthoringRepository,
    SqlCollaborationRepository,
    SqlGraphExecutionHistoryRepository,
    SqlIdentityRepository,
    SqlInvocationCacheRepository,
    SqlMaterializedNodeOutputsRepository,
    SqlModuleLibraryRepository,
    SqlNodeSecretRepository,
    SqlSavedGraphRepository,
    SqlSecurityAuditRepository,
    SqlStagedUploadRepository,
    SqlTemplateRepository,
)


@dataclass(frozen=True, slots=True)
class _SqlAlchemyUnitOfWorkState:
    session: AsyncSession
    graphs: SavedGraphRepositoryPort
    artifacts: ArtifactRepositoryPort
    invocation_cache: InvocationCacheRepositoryPort
    materialized_outputs: MaterializedNodeOutputsRepositoryPort
    node_secrets: NodeSecretRepositoryPort
    execution_history: GraphExecutionHistoryRepositoryPort
    identity: IdentityRepositoryPort
    security_audit: SecurityAuditRepositoryPort
    staged_uploads: StagedUploadRepositoryPort
    collaboration: CollaborationRepositoryPort
    modules: ModuleLibraryRepositoryPort
    templates: TemplateRepositoryPort
    agent_authoring: AgentAuthoringRepositoryPort


class SqlAlchemyUnitOfWork(
    WorkbenchUnitOfWorkPort,
    SavedGraphUnitOfWorkPort,
    NodeSecretUnitOfWorkPort,
    ExecutionHistoryUnitOfWorkPort,
    IdentityUnitOfWorkPort,
    StagedUploadUnitOfWorkPort,
    CollaborationUnitOfWorkPort,
    ModuleLibraryUnitOfWorkPort,
    TemplateUnitOfWorkPort,
    AgentAuthoringUnitOfWorkPort,
):
    """Reusable task-local SQLAlchemy transaction boundary.

    The API keeps one unit-of-work object in long-lived writers and resolvers.
    Context-local state gives each concurrent async task its own session while
    preserving the existing ``async with uow`` port.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._state: ContextVar[_SqlAlchemyUnitOfWorkState | None] = ContextVar(
            "grafy_sqlalchemy_unit_of_work_state",
            default=None,
        )

    @property
    @override
    def graphs(self) -> SavedGraphRepositoryPort:
        return self._entered_state().graphs

    @property
    @override
    def artifacts(self) -> ArtifactRepositoryPort:
        return self._entered_state().artifacts

    @property
    @override
    def invocation_cache(self) -> InvocationCacheRepositoryPort:
        return self._entered_state().invocation_cache

    @property
    @override
    def materialized_outputs(self) -> MaterializedNodeOutputsRepositoryPort:
        return self._entered_state().materialized_outputs

    @property
    @override
    def node_secrets(self) -> NodeSecretRepositoryPort:
        return self._entered_state().node_secrets

    @property
    @override
    def execution_history(self) -> GraphExecutionHistoryRepositoryPort:
        return self._entered_state().execution_history

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
    def staged_uploads(self) -> StagedUploadRepositoryPort:
        return self._entered_state().staged_uploads

    @property
    @override
    def collaboration(self) -> CollaborationRepositoryPort:
        return self._entered_state().collaboration

    @property
    @override
    def modules(self) -> ModuleLibraryRepositoryPort:
        return self._entered_state().modules

    @property
    @override
    def templates(self) -> TemplateRepositoryPort:
        return self._entered_state().templates

    @property
    @override
    def agent_authoring(self) -> AgentAuthoringRepositoryPort:
        return self._entered_state().agent_authoring

    @override
    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        if self._state.get() is not None:
            raise RuntimeError("Unit of work is already entered in this task")
        session = self._session_factory()
        self._state.set(
            _SqlAlchemyUnitOfWorkState(
                session=session,
                graphs=SqlSavedGraphRepository(session),
                artifacts=SqlArtifactRepository(session),
                invocation_cache=SqlInvocationCacheRepository(session),
                materialized_outputs=SqlMaterializedNodeOutputsRepository(session),
                node_secrets=SqlNodeSecretRepository(session),
                execution_history=SqlGraphExecutionHistoryRepository(session),
                identity=SqlIdentityRepository(session),
                security_audit=SqlSecurityAuditRepository(session),
                staged_uploads=SqlStagedUploadRepository(session),
                collaboration=SqlCollaborationRepository(session),
                modules=SqlModuleLibraryRepository(session),
                templates=SqlTemplateRepository(session),
                agent_authoring=SqlAgentAuthoringRepository(session),
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
            if exc_type is not None:
                await state.session.rollback()
        finally:
            try:
                await state.session.close()
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
                "The saved graph changed in another transaction"
            ) from exc

    @override
    async def rollback(self) -> None:
        await self._entered_state().session.rollback()

    def _entered_state(self) -> _SqlAlchemyUnitOfWorkState:
        state = self._state.get()
        if state is None:
            raise RuntimeError("Unit of work is not entered")
        return state


# Existing callers use the narrower historical name for saved-graph operations.
SqlAlchemySavedGraphUnitOfWork = SqlAlchemyUnitOfWork
