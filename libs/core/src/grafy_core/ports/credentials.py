from datetime import datetime
from typing import Protocol
from uuid import UUID

from grafy_core.domain.credentials import (
    EncryptedCredential,
    NodeSharedCredentialBinding,
    NodeUserCredentialOverride,
)


class CredentialRepositoryPort(Protocol):
    async def insert(self, record: EncryptedCredential) -> None: ...
    async def get_by_id(self, credential_id: UUID) -> EncryptedCredential | None: ...
    async def list_personal(
        self, owner_user_id: UUID, provider_kind: str | None = None
    ) -> list[EncryptedCredential]: ...
    async def list_shared(
        self, workspace_id: UUID, provider_kind: str | None = None
    ) -> list[EncryptedCredential]: ...
    async def update(
        self, record: EncryptedCredential, *, expected_updated_at: datetime
    ) -> bool: ...
    async def delete(self, credential_id: UUID) -> None: ...


class NodeCredentialSelectionRepositoryPort(Protocol):
    async def get_shared_binding(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
    ) -> NodeSharedCredentialBinding | None: ...
    async def list_shared_bindings_for_graph(
        self, workspace_id: UUID, project_id: UUID, graph_id: str
    ) -> list[NodeSharedCredentialBinding]: ...
    async def upsert_shared_binding(
        self, binding: NodeSharedCredentialBinding
    ) -> None: ...
    async def delete_shared_binding(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
    ) -> None: ...
    async def get_user_override(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        user_id: UUID,
    ) -> NodeUserCredentialOverride | None: ...
    async def list_user_overrides_for_graph(
        self, workspace_id: UUID, project_id: UUID, graph_id: str, user_id: UUID
    ) -> list[NodeUserCredentialOverride]: ...
    async def upsert_user_override(
        self, override: NodeUserCredentialOverride
    ) -> None: ...
    async def delete_user_override(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        user_id: UUID,
    ) -> None: ...
