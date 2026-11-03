"""Persistence ports for Runs and the persistent result store (ADR 0020).

The kernel's ``ResultStore`` protocol is workspace-agnostic. Adapters bind a
Workspace and implement it over ``ResultStoreRepositoryPort``, so the same
fingerprint in two Workspaces never shares a result (decision 5).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.runs import Run
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import FailureRecord, InstancePointer, StoredResult
from grafy_core.ports.transactions import TransactionPort


class RunRepositoryPort(Protocol):
    async def add(self, run: Run) -> None: ...

    async def get(
        self,
        workspace_id: UUID,
        project_id: UUID,
        run_id: UUID,
    ) -> Run | None: ...

    async def save(self, run: Run) -> None:
        """Persist status, ``finished_at`` and ``error`` of an existing Run."""
        ...

    async def list_for_project(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[Run]:
        """Newest first by ``created_at`` then id."""
        ...

    async def interrupt_unfinished(self, *, at: datetime, error: str) -> list[Run]:
        """Mark every running Run, in every Workspace, interrupted. Startup only."""
        ...


class ResultStoreRepositoryPort(Protocol):
    async def get_result(
        self,
        workspace_id: UUID,
        fingerprint: str,
    ) -> StoredResult | None: ...

    async def put_result_if_absent(
        self,
        workspace_id: UUID,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
        *,
        created_at: datetime,
    ) -> StoredResult:
        """Append once. A fingerprint that already has a result keeps it unchanged."""
        ...

    async def get_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
    ) -> InstancePointer | None: ...

    async def list_pointers(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> Mapping[InstanceKey, InstancePointer]: ...

    async def set_success_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
        fingerprint: str,
    ) -> None:
        """Point at ``fingerprint`` and clear the last failure."""
        ...

    async def set_failure_pointer(
        self,
        workspace_id: UUID,
        instance: InstanceKey,
        failure: FailureRecord,
    ) -> None:
        """Keep the last result pointer; replace the last failure."""
        ...


class RunUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def runs(self) -> RunRepositoryPort: ...

    @property
    def results(self) -> ResultStoreRepositoryPort: ...


__all__ = [
    "ResultStoreRepositoryPort",
    "RunRepositoryPort",
    "RunUnitOfWorkPort",
]
