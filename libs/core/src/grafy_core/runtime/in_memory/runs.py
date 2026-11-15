from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override
from uuid import UUID

if TYPE_CHECKING:
    from grafy_core.domain.artifact_outputs import ArtifactOutputValue

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.domain.runs import Run, RunStatus
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import FailureRecord, InstancePointer, StoredResult
from grafy_core.ports.runs import ResultStoreRepositoryPort, RunRepositoryPort

from grafy_core.runtime.in_memory.store import InMemoryDataStore, newest_first


@final
class InMemoryRunRepository(RunRepositoryPort):
    """Run bookkeeping. The results a Run caused belong to instances, not to it."""

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add(self, run: Run) -> None:
        if run.id in self._store.runs:
            raise ObjectAlreadyExistsError(f"Run already exists: {run.id}")
        self._store.runs[run.id] = replace(run)

    @override
    async def get(
        self, workspace_id: UUID, project_id: UUID, run_id: UUID
    ) -> Run | None:
        run = self._store.runs.get(run_id)
        if (
            run is None
            or run.workspace_id != workspace_id
            or run.project_id != project_id
        ):
            return None
        return replace(run)

    @override
    async def save(self, run: Run) -> None:
        # A transition writes status, finish stamp and error, and nothing else.
        stored = self._store.runs.get(run.id)
        if (
            stored is None
            or stored.workspace_id != run.workspace_id
            or stored.project_id != run.project_id
        ):
            return
        stored.status = run.status
        stored.finished_at = run.finished_at
        stored.error = run.error

    @override
    async def list_for_project(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[Run]:
        runs = [
            replace(run)
            for run in self._store.runs.values()
            if run.workspace_id == workspace_id
            and run.project_id == project_id
            and (not active_only or run.status is RunStatus.RUNNING)
        ]
        return newest_first(
            runs, stamp=lambda run: run.created_at, ident=lambda run: run.id
        )[:limit]

    @override
    async def interrupt_unfinished(self, *, at: datetime, error: str) -> list[Run]:
        unfinished = [
            run for run in self._store.runs.values() if run.status is RunStatus.RUNNING
        ]
        for run in unfinished:
            run.status = RunStatus.INTERRUPTED
            run.finished_at = at
            run.error = error
        return [replace(run) for run in unfinished]


@final
class InMemoryResultStoreRepository(ResultStoreRepositoryPort):
    """Append-once results plus the one mutable pointer per node instance.

    Results are keyed by ``(workspace_id, fingerprint)`` so the same fingerprint in
    two Workspaces holds two rows, and a stored output payload is copied in and out
    so nothing can rewrite an appended result.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def artifact_is_referenced(
        self, workspace_id: UUID, artifact_id: UUID
    ) -> bool:
        # Only the typed refs count: an id that appears in free metadata text is
        # not a reference, exactly as the SQL adapter decides.
        for (result_workspace, _), row in self._store.node_results.items():
            if result_workspace != workspace_id:
                continue
            for value in row.outputs.values():
                if isinstance(value, ArtifactRefSequence):
                    if any(ref.artifact_id == artifact_id for ref in value.item_refs):
                        return True
                elif (
                    isinstance(value, ArtifactRef) and value.artifact_id == artifact_id
                ):
                    return True
        return False

    @override
    async def get_result(
        self, workspace_id: UUID, fingerprint: str
    ) -> StoredResult | None:
        row = self._store.node_results.get((workspace_id, fingerprint))
        if row is None:
            return None
        return StoredResult(
            fingerprint=row.fingerprint,
            outputs=MappingProxyType(dict(row.outputs)),
            created_at=row.created_at,
        )

    @override
    async def put_result_if_absent(
        self,
        workspace_id: UUID,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
        *,
        created_at: datetime,
    ) -> StoredResult:
        key = (workspace_id, fingerprint)
        row = self._store.node_results.get(key)
        if row is None:
            row = StoredResult(
                fingerprint=fingerprint,
                outputs={
                    port: value.model_copy(deep=True) for port, value in outputs.items()
                },
                created_at=created_at,
            )
            self._store.node_results[key] = row
        # Whatever happened, the row that is there is the answer: a fingerprint
        # that already had a result keeps it unchanged. The stored row keeps a
        # plain dict because a mapping proxy cannot be deep-copied, and the store
        # clones itself at every transaction boundary.
        return StoredResult(
            fingerprint=row.fingerprint,
            outputs=MappingProxyType(dict(row.outputs)),
            created_at=row.created_at,
        )

    @override
    async def get_pointer(
        self, workspace_id: UUID, instance: InstanceKey
    ) -> InstancePointer | None:
        return self._store.pointers.get((workspace_id, instance))

    @override
    async def list_pointers(
        self, workspace_id: UUID, project_id: UUID
    ) -> Mapping[InstanceKey, InstancePointer]:
        return {
            instance: pointer
            for (pointer_workspace, instance), pointer in self._store.pointers.items()
            if pointer_workspace == workspace_id
            and instance.project_id == str(project_id)
        }

    @override
    async def set_success_pointer(
        self, workspace_id: UUID, instance: InstanceKey, fingerprint: str
    ) -> None:
        self._store.pointers[(workspace_id, instance)] = InstancePointer(
            last_result_fingerprint=fingerprint, last_failure=None
        )

    @override
    async def set_failure_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
        failure: FailureRecord,
    ) -> None:
        # The previous result pointer is deliberately kept: a failure replaces the
        # failure and leaves the instance's last result where it was.
        previous = self._store.pointers.get((workspace_id, instance))
        self._store.pointers[(workspace_id, instance)] = InstancePointer(
            last_result_fingerprint=(
                None if previous is None else previous.last_result_fingerprint
            ),
            last_failure=failure,
        )
