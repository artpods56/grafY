from asyncio import Lock
from collections.abc import Collection
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Self,
    final,
    override,
)
from uuid import UUID

if TYPE_CHECKING:
    from grafy_core.domain.invocation_cache import InvocationCacheEntry
    from grafy_core.domain.execution_history import (
        GraphExecution,
        GraphExecutionCursor,
        GraphExecutionDetail,
        GraphExecutionNodeResult,
        GraphExecutionPage,
        GraphExecutionStatus,
    )
    from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
    from grafy_core.domain.staged_uploads import StagedUpload
    from grafy_core.ports.invocation_cache import InvocationCacheRepositoryPort
    from grafy_core.ports.execution_history import (
        GraphExecutionHistoryRepositoryPort,
    )
    from grafy_core.ports.materialized_outputs import (
        MaterializedNodeOutputsRepositoryPort,
    )
    from grafy_core.ports.staged_uploads import StagedUploadRepositoryPort

from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey
from grafy_core.ports.artifacts import ArtifactRepositoryPort, UnitOfWorkPort
from grafy_core.domain.execution_history import TransientExecution
from grafy_core.domain.errors import (
    CollaborationActiveExecutionError,
    NotFoundError,
    ObjectAlreadyExistsError,
)


def _clone[T](value: T) -> T:
    return deepcopy(value)


@dataclass(slots=True)
class InMemoryDataStore:
    transient_executions: dict[UUID, TransientExecution] = field(default_factory=dict)
    artifacts: dict[UUID, ArtifactObject] = field(default_factory=dict)
    materialized_outputs: dict[
        tuple[UUID, UUID, int, str],
        "MaterializedNodeOutputs",
    ] = field(default_factory=dict)
    invocation_cache: dict[tuple[UUID, str], "InvocationCacheEntry"] = field(
        default_factory=dict
    )
    staged_uploads: dict[tuple[UUID, str], "StagedUpload"] = field(default_factory=dict)
    graph_executions: dict[
        UUID,
        "GraphExecution",
    ] = field(default_factory=dict)
    # One row per requested node: stable request position plus the optional
    # terminal result recorded at most once.
    graph_execution_nodes: dict[
        tuple[UUID, UUID, str],
        tuple[int, "GraphExecutionNodeResult | None"],
    ] = field(default_factory=dict)

    def clone(self) -> Self:
        return _clone(self)

    def replace_with(self, other: Self) -> None:
        self.transient_executions = _clone(other.transient_executions)
        self.artifacts = _clone(other.artifacts)
        self.materialized_outputs = _clone(other.materialized_outputs)
        self.invocation_cache = _clone(other.invocation_cache)
        self.staged_uploads = _clone(other.staged_uploads)
        self.graph_executions = _clone(other.graph_executions)
        self.graph_execution_nodes = _clone(other.graph_execution_nodes)


@final
class InMemoryArtifactRepository(ArtifactRepositoryPort):
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add(self, artifact: ArtifactObject) -> None:
        if artifact.id in self._store.artifacts:
            raise ObjectAlreadyExistsError(f"Artifact already exists: {artifact.id}")
        self._store.artifacts[artifact.id] = artifact

    @override
    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        artifact = self._store.artifacts.get(artifact_id)
        if artifact is None or artifact.workspace_id != workspace_id:
            return None
        return artifact

    @override
    async def get_many(
        self,
        workspace_id: UUID,
        artifact_ids: Collection[UUID],
    ) -> dict[UUID, ArtifactObject]:
        return {
            artifact_id: artifact
            for artifact_id in artifact_ids
            if (artifact := self._store.artifacts.get(artifact_id)) is not None
            and artifact.workspace_id == workspace_id
        }

    @override
    async def remove(self, workspace_id: UUID, artifact: ArtifactObject) -> None:
        if artifact.workspace_id != workspace_id:
            return
        stored = self._store.artifacts.get(artifact.id)
        if stored is not None and stored.workspace_id == workspace_id:
            self._store.artifacts.pop(artifact.id, None)

    @override
    async def list_by_type(
        self,
        workspace_id: UUID,
        key: ArtifactTypeKey,
    ) -> list[ArtifactObject]:
        return [
            artifact
            for artifact in self._store.artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.artifact_type == key.id
            and artifact.schema_version == key.schema_version
        ]


@final
class InMemoryMaterializedNodeOutputsRepository:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def upsert(self, value: "MaterializedNodeOutputs") -> None:
        key = (
            value.workspace_id,
            value.graph_id,
            value.graph_revision,
            value.node_id,
        )
        self._store.materialized_outputs[key] = _clone(value)

    async def get(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
        node_id: str,
    ) -> "MaterializedNodeOutputs | None":
        value = self._store.materialized_outputs.get(
            (workspace_id, graph_id, graph_revision, node_id)
        )
        return _clone(value) if value is not None else None

    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
    ) -> list["MaterializedNodeOutputs"]:
        values = [
            value
            for (saved_workspace_id, saved_graph_id, saved_revision, _), value in (
                self._store.materialized_outputs.items()
            )
            if (
                saved_workspace_id == workspace_id
                and saved_graph_id == graph_id
                and saved_revision == graph_revision
            )
        ]
        return _clone(sorted(values, key=lambda value: value.node_id))


@final
class InMemoryInvocationCacheRepository:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> "InvocationCacheEntry | None":
        entry = self._store.invocation_cache.get((workspace_id, key_sha256))
        return _clone(entry) if entry is not None else None

    async def put_if_absent(self, entry: "InvocationCacheEntry") -> bool:
        key = (entry.workspace_id, entry.key_sha256)
        if key in self._store.invocation_cache:
            return False
        self._store.invocation_cache[key] = _clone(entry)
        return True

    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        entry = self._store.invocation_cache.get((workspace_id, key_sha256))
        if entry is None or entry.generation != generation:
            return False
        del self._store.invocation_cache[(workspace_id, key_sha256)]
        return True


@final
class InMemoryGraphExecutionHistoryRepository:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def add_transient(self, execution: TransientExecution) -> None:
        if execution.execution_id in self._store.transient_executions:
            raise ObjectAlreadyExistsError(
                f"Transient execution already exists: {execution.execution_id}"
            )
        self._store.transient_executions[execution.execution_id] = execution

    async def remove_transient(self, execution_id: UUID, owner_id: UUID) -> None:
        execution = self._store.transient_executions.get(execution_id)
        if execution is not None and execution.owner_id == owner_id:
            del self._store.transient_executions[execution_id]

    async def list_transient(self) -> tuple[TransientExecution, ...]:
        return tuple(
            sorted(
                self._store.transient_executions.values(),
                key=lambda execution: (execution.created_at, execution.execution_id),
            )
        )

    async def clear_transient(self) -> None:
        self._store.transient_executions.clear()

    async def add(self, execution: "GraphExecution") -> None:
        execution_key = execution.execution_id
        if execution_key in self._store.graph_executions:
            raise ObjectAlreadyExistsError(
                f"Graph execution already exists: {execution.execution_id}"
            )
        if execution.idempotency_key is not None and any(
            stored.workspace_id == execution.workspace_id
            and stored.idempotency_key == execution.idempotency_key
            for stored in self._store.graph_executions.values()
        ):
            raise ObjectAlreadyExistsError(
                "Graph execution idempotency key already exists: "
                f"{execution.idempotency_key}"
            )
        active_execution_id = await self.find_active_execution_id(
            execution.workspace_id,
            execution.graph_id,
        )
        if active_execution_id is not None:
            raise CollaborationActiveExecutionError(
                workspace_id=execution.workspace_id,
                graph_id=execution.graph_id,
                execution_id=active_execution_id,
            )
        self._store.graph_executions[execution_key] = _clone(execution)
        for position, node_id in enumerate(execution.requested_node_ids):
            self._store.graph_execution_nodes[
                (execution.workspace_id, execution.execution_id, node_id)
            ] = (position, None)

    async def update(self, execution: "GraphExecution") -> None:
        current = self._store.graph_executions.get(execution.execution_id)
        if current is None or current.workspace_id != execution.workspace_id:
            raise NotFoundError("Graph execution", str(execution.execution_id))
        if (
            current.graph_id != execution.graph_id
            or current.graph_revision != execution.graph_revision
            or current.scope != execution.scope
            or current.requested_node_ids != execution.requested_node_ids
            or current.submitted_request != execution.submitted_request
            or current.idempotency_key != execution.idempotency_key
            or current.submitted_by_actor_id != execution.submitted_by_actor_id
            or current.created_at != execution.created_at
        ):
            raise ValueError(
                f"Graph execution {execution.execution_id} identity and request "
                "fields are immutable"
            )
        self._store.graph_executions[execution.execution_id] = _clone(execution)

    async def add_node_result(self, result: "GraphExecutionNodeResult") -> None:
        execution = self._store.graph_executions.get(result.execution_id)
        if execution is None or execution.workspace_id != result.workspace_id:
            raise NotFoundError("Graph execution", str(result.execution_id))
        key = (result.workspace_id, result.execution_id, result.node_id)
        row = self._store.graph_execution_nodes.get(key)
        if row is None:
            raise ValueError(
                f"Graph execution {result.execution_id} did not request node "
                f"{result.node_id!r}"
            )
        _, existing_result = row
        if existing_result is not None:
            raise ObjectAlreadyExistsError(
                "Graph execution node result already exists: "
                f"{result.execution_id}/{result.node_id}"
            )
        if any(
            stored_result is not None and stored_result.position == result.position
            for execution_key, (_, stored_result) in (
                self._store.graph_execution_nodes.items()
            )
            if execution_key[:2] == (result.workspace_id, result.execution_id)
        ):
            raise ObjectAlreadyExistsError(
                "Graph execution node result position already exists: "
                f"{result.execution_id}/{result.position}"
            )
        self._store.graph_execution_nodes[key] = (row[0], _clone(result))

    async def get(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> "GraphExecutionDetail | None":
        from grafy_core.domain.execution_history import GraphExecutionDetail

        execution = self._store.graph_executions.get(execution_id)
        if execution is None or execution.workspace_id != workspace_id:
            return None
        node_results = sorted(
            (
                result
                for stored_key, (_, result) in (
                    self._store.graph_execution_nodes.items()
                )
                if (
                    stored_key[0] == workspace_id
                    and stored_key[1] == execution_id
                    and result is not None
                )
            ),
            key=lambda result: (result.position, result.node_id),
        )
        return GraphExecutionDetail(
            execution=_clone(execution),
            node_results=tuple(_clone(node_results)),
        )

    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        limit: int,
        cursor: "GraphExecutionCursor | None" = None,
        graph_revision: int | None = None,
        status: "GraphExecutionStatus | None" = None,
        node_id: str | None = None,
    ) -> "GraphExecutionPage":
        from grafy_core.domain.execution_history import (
            GraphExecutionCursor,
            GraphExecutionListItem,
            GraphExecutionPage,
        )

        if limit < 1:
            raise ValueError("Graph execution page limit must be at least 1")
        if graph_revision is not None and graph_revision < 1:
            raise ValueError("Graph execution revision filter must be at least 1")
        normalized_node_id = None
        if node_id is not None:
            normalized_node_id = node_id.strip()
            if normalized_node_id == "":
                raise ValueError("Graph execution node filter must not be blank")

        values = [
            execution
            for execution in self._store.graph_executions.values()
            if execution.workspace_id == workspace_id
            and execution.graph_id == graph_id
            and (graph_revision is None or execution.graph_revision == graph_revision)
            and (status is None or execution.status == status)
            and (
                normalized_node_id is None
                or normalized_node_id in execution.requested_node_ids
            )
        ]
        if cursor is not None:
            values = [
                execution
                for execution in values
                if (execution.created_at, execution.execution_id.int)
                < (cursor.created_at, cursor.execution_id.int)
            ]
        values.sort(
            key=lambda execution: (
                execution.created_at,
                execution.execution_id.int,
            ),
            reverse=True,
        )
        has_more = len(values) > limit
        page_values = values[:limit]
        items: list[GraphExecutionListItem] = []
        for execution in page_values:
            results = [
                result
                for stored_key, (_, result) in (
                    self._store.graph_execution_nodes.items()
                )
                if (
                    stored_key[0] == workspace_id
                    and stored_key[1] == execution.execution_id
                    and result is not None
                )
            ]
            items.append(
                GraphExecutionListItem(
                    execution=_clone(execution),
                    node_count=len(results),
                    artifact_count=sum(result.artifact_count for result in results),
                )
            )
        next_cursor = None
        if has_more and page_values:
            last = page_values[-1]
            next_cursor = GraphExecutionCursor(
                created_at=last.created_at,
                execution_id=last.execution_id,
            )
        return GraphExecutionPage(items=tuple(items), next_cursor=next_cursor)

    async def find_active_execution_id(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> "UUID | None":
        active = [
            execution
            for execution in self._store.graph_executions.values()
            if execution.workspace_id == workspace_id
            and execution.graph_id == graph_id
            and execution.status in {"queued", "running", "cancelling"}
        ]
        if not active:
            return None
        return min(
            active,
            key=lambda execution: (execution.created_at, execution.execution_id.int),
        ).execution_id

    async def list_queued(self) -> tuple["GraphExecution", ...]:
        return tuple(
            _clone(execution)
            for execution in sorted(
                (
                    execution
                    for execution in self._store.graph_executions.values()
                    if execution.status == "queued"
                ),
                key=lambda execution: (
                    execution.created_at,
                    execution.execution_id.int,
                ),
            )
        )

    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> "GraphExecution | None":
        for execution in self._store.graph_executions.values():
            if (
                execution.workspace_id == workspace_id
                and execution.idempotency_key == idempotency_key
            ):
                return _clone(execution)
        return None

    async def claim_queued(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        *,
        started_at: datetime,
    ) -> bool:
        if started_at.tzinfo is None:
            raise ValueError("Graph execution start timestamp must be timezone-aware")
        execution = self._store.graph_executions.get(execution_id)
        if (
            execution is None
            or execution.workspace_id != workspace_id
            or execution.status != "queued"
        ):
            return False
        self._store.graph_executions[execution_id] = replace(
            execution,
            status="running",
            started_at=started_at,
        )
        return True

    async def interrupt_started(
        self,
        *,
        finished_at: datetime,
        error: str,
    ) -> tuple["GraphExecution", ...]:
        if finished_at.tzinfo is None:
            raise ValueError(
                "Graph execution interruption timestamp must be timezone-aware"
            )
        interrupted: list[GraphExecution] = []
        for execution_key, execution in list(self._store.graph_executions.items()):
            if execution.status not in {"running", "cancelling"}:
                continue
            interrupted.append(_clone(execution))
            self._store.graph_executions[execution_key] = replace(
                execution,
                status="failed",
                finished_at=finished_at,
                error=error,
            )
        return tuple(interrupted)


@final
class InMemoryStagedUploadRepository:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def add(self, upload: "StagedUpload") -> None:
        key = (upload.workspace_id, upload.upload_key)
        if key in self._store.staged_uploads:
            raise ObjectAlreadyExistsError(
                f"Staged upload already exists: {upload.workspace_id}/{upload.upload_key}"
            )
        self._store.staged_uploads[key] = _clone(upload)

    async def get(
        self,
        workspace_id: UUID,
        upload_key: str,
    ) -> "StagedUpload | None":
        upload = self._store.staged_uploads.get((workspace_id, upload_key))
        if upload is None:
            return None
        return _clone(upload)

    async def list_for_workspace(self, workspace_id: UUID) -> list["StagedUpload"]:
        uploads = [
            _clone(upload)
            for (stored_workspace_id, _), upload in self._store.staged_uploads.items()
            if stored_workspace_id == workspace_id
        ]
        uploads.sort(key=lambda upload: (upload.created_at, upload.upload_key))
        return uploads

    async def remove(self, workspace_id: UUID, upload_key: str) -> None:
        self._store.staged_uploads.pop((workspace_id, upload_key), None)


@dataclass(frozen=True, slots=True)
class _InMemoryUnitOfWorkState:
    working_store: InMemoryDataStore
    artifacts: ArtifactRepositoryPort
    materialized_outputs: "MaterializedNodeOutputsRepositoryPort"
    invocation_cache: "InvocationCacheRepositoryPort"
    staged_uploads: "StagedUploadRepositoryPort"
    execution_history: "GraphExecutionHistoryRepositoryPort"


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
    def materialized_outputs(self) -> "MaterializedNodeOutputsRepositoryPort":
        return self._entered_state().materialized_outputs

    @property
    def invocation_cache(self) -> "InvocationCacheRepositoryPort":
        return self._entered_state().invocation_cache

    @property
    def staged_uploads(self) -> "StagedUploadRepositoryPort":
        return self._entered_state().staged_uploads

    @property
    def execution_history(self) -> "GraphExecutionHistoryRepositoryPort":
        return self._entered_state().execution_history

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
                    artifacts=InMemoryArtifactRepository(working_store),
                    materialized_outputs=InMemoryMaterializedNodeOutputsRepository(
                        working_store
                    ),
                    invocation_cache=InMemoryInvocationCacheRepository(working_store),
                    staged_uploads=InMemoryStagedUploadRepository(working_store),
                    execution_history=InMemoryGraphExecutionHistoryRepository(
                        working_store
                    ),
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
