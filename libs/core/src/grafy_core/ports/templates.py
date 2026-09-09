from typing import Protocol
from uuid import UUID

from grafy_core.domain.templates import Template
from grafy_core.ports.collaboration import CollaborationRepositoryPort
from grafy_core.ports.identity import IdentityRepositoryPort
from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort
from grafy_core.ports.transactions import TransactionPort


class TemplateRepositoryPort(Protocol):
    async def add(self, template: Template) -> None: ...

    async def get(
        self,
        workspace_id: UUID,
        template_id: UUID,
    ) -> Template | None: ...

    async def list(
        self,
        workspace_id: UUID,
        *,
        query: str | None,
        include_archived: bool,
    ) -> list[Template]: ...


class TemplateUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def graphs(self) -> SavedGraphRepositoryPort: ...

    @property
    def collaboration(self) -> CollaborationRepositoryPort: ...

    @property
    def identity(self) -> IdentityRepositoryPort: ...

    @property
    def templates(self) -> TemplateRepositoryPort: ...


__all__ = ["TemplateRepositoryPort", "TemplateUnitOfWorkPort"]
