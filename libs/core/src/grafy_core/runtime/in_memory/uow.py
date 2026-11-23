from asyncio import Lock
from contextvars import ContextVar
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Self, override

if TYPE_CHECKING:
    from grafy_core.ports.uploads import UploadRepositoryPort

from grafy_core.ports.agent_conversations import AgentConversationRepositoryPort
from grafy_core.ports.agent_turns import AgentTurnRepositoryPort
from grafy_core.ports.artifacts import ArtifactRepositoryPort, UnitOfWorkPort
from grafy_core.ports.collaboration import CollaborationRepositoryPort
from grafy_core.ports.library_folders import LibraryFolderRepositoryPort
from grafy_core.ports.projects import ProjectRepositoryPort
from grafy_core.ports.runs import ResultStoreRepositoryPort, RunRepositoryPort
from grafy_core.ports.workspace_packs import WorkspacePackRepositoryPort

from grafy_core.runtime.in_memory.agents import (
    InMemoryAgentConversationRepository,
    InMemoryAgentTurnRepository,
)
from grafy_core.runtime.in_memory.artifacts import (
    InMemoryArtifactRepository,
    InMemoryLibraryFolderRepository,
)
from grafy_core.runtime.in_memory.collaboration import InMemoryCollaborationRepository
from grafy_core.runtime.in_memory.projects import InMemoryProjectRepository
from grafy_core.runtime.in_memory.runs import (
    InMemoryRunRepository,
    InMemoryResultStoreRepository,
)
from grafy_core.runtime.in_memory.store import InMemoryDataStore
from grafy_core.runtime.in_memory.uploads import InMemoryUploadRepository
from grafy_core.runtime.in_memory.workspace_packs import InMemoryWorkspacePackRepository


@dataclass(frozen=True, slots=True)
class _InMemoryUnitOfWorkState:
    working_store: InMemoryDataStore
    artifacts: ArtifactRepositoryPort
    uploads: "UploadRepositoryPort"
    library_folders: "LibraryFolderRepositoryPort"
    projects: ProjectRepositoryPort
    collaboration: CollaborationRepositoryPort
    runs: RunRepositoryPort
    results: ResultStoreRepositoryPort
    agent_conversations: AgentConversationRepositoryPort
    agent_turns: AgentTurnRepositoryPort
    workspace_packs: WorkspacePackRepositoryPort


class InMemoryUnitOfWork(UnitOfWorkPort):
    def __init__(self, store: InMemoryDataStore | None = None) -> None:
        self._store = store or InMemoryDataStore()
        self._transaction_lock = Lock()
        self._state: ContextVar[_InMemoryUnitOfWorkState | None] = ContextVar(
            "grafy_in_memory_unit_of_work_state",
            default=None,
        )
        self.commit_count = 0
        self.rollback_count = 0

    @property
    @override
    def artifacts(self) -> ArtifactRepositoryPort:
        return self._entered_state().artifacts

    @property
    def uploads(self) -> "UploadRepositoryPort":
        return self._entered_state().uploads

    @property
    def library_folders(self) -> "LibraryFolderRepositoryPort":
        return self._entered_state().library_folders

    @property
    @override
    def projects(self) -> ProjectRepositoryPort:
        return self._entered_state().projects

    @property
    @override
    def collaboration(self) -> CollaborationRepositoryPort:
        return self._entered_state().collaboration

    @property
    @override
    def runs(self) -> RunRepositoryPort:
        return self._entered_state().runs

    @property
    @override
    def results(self) -> ResultStoreRepositoryPort:
        return self._entered_state().results

    @property
    def agent_conversations(self) -> AgentConversationRepositoryPort:
        return self._entered_state().agent_conversations

    @property
    def agent_turns(self) -> AgentTurnRepositoryPort:
        return self._entered_state().agent_turns

    @property
    def workspace_packs(self) -> WorkspacePackRepositoryPort:
        return self._entered_state().workspace_packs

    @override
    async def __aenter__(self) -> Self:
        if self._state.get() is not None:
            raise RuntimeError("Unit of work is already entered in this task")

        await self._transaction_lock.acquire()
        try:
            working_store = self._store.clone()
            self._state.set(
                _InMemoryUnitOfWorkState(
                    working_store=working_store,
                    workspace_packs=InMemoryWorkspacePackRepository(working_store),
                    artifacts=InMemoryArtifactRepository(working_store),
                    uploads=InMemoryUploadRepository(working_store),
                    library_folders=InMemoryLibraryFolderRepository(working_store),
                    projects=InMemoryProjectRepository(working_store),
                    collaboration=InMemoryCollaborationRepository(working_store),
                    runs=InMemoryRunRepository(working_store),
                    results=InMemoryResultStoreRepository(working_store),
                    agent_conversations=InMemoryAgentConversationRepository(
                        working_store
                    ),
                    agent_turns=InMemoryAgentTurnRepository(working_store),
                )
            )
        except BaseException:
            self._transaction_lock.release()
            raise
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
                await self.rollback()
        finally:
            self._state.set(None)
            self._transaction_lock.release()

    @override
    async def commit(self) -> None:
        state = self._entered_state()
        self._store.replace_with(state.working_store)
        self.commit_count += 1

    @override
    async def rollback(self) -> None:
        state = self._entered_state()
        state.working_store.replace_with(self._store)
        self.rollback_count += 1

    def _entered_state(self) -> _InMemoryUnitOfWorkState:
        state = self._state.get()
        if state is None:
            raise RuntimeError("Unit of work is not entered")
        return state
