"""SQL adapters that bind the kernel's Workspace-agnostic seams to persistence.

``PersistentResultStore`` is the kernel ``ResultStore`` for one Workspace: it
binds the Workspace id into every call, so two Workspaces holding the same
fingerprint read and write different rows. Each mutation opens its own
transaction through the injected unit-of-work factory, commits, and releases the
session, which is what lets the scheduler store a result the moment a
computation finishes without holding a transaction across computation work.

``RepositoryProjectDocuments`` reads the live head document of a Project through
the collaboration unit of work; the read is scoped to the Workspace and Project
pair, and a missing Project answers ``NotFoundError`` as the run service expects.

Neither adapter imports HTTP or route modules.
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import override
from uuid import UUID

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.errors import NotFoundError
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import (
    FailureRecord,
    InstancePointer,
    ResultStore,
    StoredResult,
)
from grafy_core.ports.collaboration import CollaborationUnitOfWorkPort
from grafy_core.ports.runs import RunUnitOfWorkPort
from grafy_core.kernel.project import ProjectDocument

from grafy_api.runs.ports import ProjectDocumentSource


class PersistentResultStore(ResultStore):
    """A Workspace-bound ``ResultStore`` over the SQL result-store repository."""

    def __init__(
        self,
        *,
        workspace_id: UUID,
        uow_factory: Callable[[], RunUnitOfWorkPort],
    ) -> None:
        self._workspace_id = workspace_id
        self._uow_factory = uow_factory

    @override
    async def get_result(self, fingerprint: str) -> StoredResult | None:
        async with self._uow_factory() as uow:
            return await uow.results.get_result(self._workspace_id, fingerprint)

    @override
    async def put_result(
        self,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
    ) -> StoredResult:
        async with self._uow_factory() as uow:
            stored = await uow.results.put_result_if_absent(
                self._workspace_id,
                fingerprint,
                outputs,
                created_at=datetime.now(UTC),
            )
            await uow.commit()
            return stored

    @override
    async def get_pointer(self, instance: InstanceKey) -> InstancePointer | None:
        async with self._uow_factory() as uow:
            return await uow.results.get_pointer(self._workspace_id, instance)

    @override
    async def record_success(self, instance: InstanceKey, fingerprint: str) -> None:
        async with self._uow_factory() as uow:
            if (await uow.results.get_result(self._workspace_id, fingerprint)) is None:
                raise KeyError(f"No stored result for fingerprint {fingerprint!r}")
            await uow.results.set_success_pointer(
                self._workspace_id, instance, fingerprint
            )
            await uow.commit()

    @override
    async def record_failure(
        self,
        instance: InstanceKey,
        failure: FailureRecord,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.results.set_failure_pointer(self._workspace_id, instance, failure)
            await uow.commit()


class RepositoryProjectDocuments(ProjectDocumentSource):
    """Reads the live Project head document for the run service."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], CollaborationUnitOfWorkPort],
    ) -> None:
        self._uow_factory = uow_factory

    @override
    async def head_document(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectDocument:
        async with self._uow_factory() as uow:
            head = await uow.collaboration.get_head(workspace_id, project_id)
        if head is None:
            raise NotFoundError("Project", str(project_id))
        return head.document


__all__ = ["PersistentResultStore", "RepositoryProjectDocuments"]
