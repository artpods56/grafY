from typing import final, override
from uuid import UUID

from grafy_core.domain.collaboration import (
    ProjectCheckpointMapping,
    ProjectCommandReceipt,
    ProjectHead,
)
from grafy_core.domain.errors import ConcurrentWriteError, ObjectAlreadyExistsError
from grafy_core.ports.collaboration import CollaborationRepositoryPort

from grafy_core.runtime.in_memory.store import InMemoryDataStore, clone


@final
class InMemoryCollaborationRepository(CollaborationRepositoryPort):
    """The Project head, its command receipts, and its checkpoint mappings.

    Receipts and mappings are append-only and raise ``ConcurrentWriteError`` on a
    repeated key, the same way the SQL adapter turns its primary-key violation.
    The head is handed out as a copy: the service mutates what it read and writes
    it back with ``save_head``, and a copy never leaks an uncommitted change into
    the store.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add_head(self, head: ProjectHead) -> None:
        key = (head.workspace_id, head.project_id)
        if key in self._store.project_heads:
            raise ObjectAlreadyExistsError(f"Project head already exists: {key[1]}")
        self._store.project_heads[key] = clone(head)

    @override
    async def get_head(
        self, workspace_id: UUID, project_id: UUID
    ) -> ProjectHead | None:
        head = self._store.project_heads.get((workspace_id, project_id))
        return None if head is None else clone(head)

    @override
    async def lock_head(
        self, workspace_id: UUID, project_id: UUID
    ) -> ProjectHead | None:
        # One in-process transaction runs at a time: the unit of work's
        # transaction lock is this store's row lock.
        return await self.get_head(workspace_id, project_id)

    @override
    async def save_head(self, head: ProjectHead) -> None:
        key = (head.workspace_id, head.project_id)
        if key not in self._store.project_heads:
            return
        self._store.project_heads[key] = clone(head)

    @override
    async def remove_head(self, workspace_id: UUID, project_id: UUID) -> None:
        _ = self._store.project_heads.pop((workspace_id, project_id), None)

    @override
    async def get_receipt(
        self, workspace_id: UUID, project_id: UUID, command_id: UUID
    ) -> ProjectCommandReceipt | None:
        return self._store.project_command_receipts.get(
            (workspace_id, project_id, command_id)
        )

    @override
    async def add_receipt(self, receipt: ProjectCommandReceipt) -> None:
        key = (receipt.workspace_id, receipt.project_id, receipt.command_id)
        if key in self._store.project_command_receipts:
            raise ConcurrentWriteError(
                f"Project command receipt already recorded: {receipt.project_id}"
                f"/{receipt.command_id}"
            )
        self._store.project_command_receipts[key] = receipt

    @override
    async def get_checkpoint_mapping(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        room_epoch: UUID,
        collaboration_sequence: int,
    ) -> ProjectCheckpointMapping | None:
        return self._store.project_checkpoint_mappings.get(
            (workspace_id, project_id, room_epoch, collaboration_sequence)
        )

    @override
    async def add_checkpoint_mapping(self, mapping: ProjectCheckpointMapping) -> None:
        key = (
            mapping.workspace_id,
            mapping.project_id,
            mapping.room_epoch,
            mapping.collaboration_sequence,
        )
        if key in self._store.project_checkpoint_mappings:
            raise ConcurrentWriteError(
                f"Project checkpoint mapping already recorded: {mapping.project_id}"
                f"/{mapping.room_epoch}/{mapping.collaboration_sequence}"
            )
        self._store.project_checkpoint_mappings[key] = mapping
