from typing import Protocol, runtime_checkable
from uuid import UUID

from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.ports.invocation_cache import InvocationCacheRepositoryPort
from grafy_core.ports.execution_history import ExecutionHistoryUnitOfWorkPort
from grafy_core.ports.uploads import UploadRepositoryPort


@runtime_checkable
class MaterializedNodeOutputsRepositoryPort(Protocol):
    async def upsert(self, value: MaterializedNodeOutputs) -> None: ...

    async def get(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
        node_id: str,
    ) -> MaterializedNodeOutputs | None: ...

    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
    ) -> list[MaterializedNodeOutputs]: ...


class WorkbenchUnitOfWorkPort(ExecutionHistoryUnitOfWorkPort, Protocol):
    @property
    def materialized_outputs(self) -> MaterializedNodeOutputsRepositoryPort: ...

    @property
    def invocation_cache(self) -> InvocationCacheRepositoryPort: ...

    @property
    def uploads(self) -> UploadRepositoryPort: ...
