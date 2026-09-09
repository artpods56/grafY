from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from pydantic import SecretStr

from grafy_core.domain.node_secrets import (
    EncryptedNodeSecret,
    JsonValue,
)
from grafy_core.ports.transactions import TransactionPort

if TYPE_CHECKING:
    from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort


class NodeSecretUnavailableError(RuntimeError):
    pass


class NodeSecretResolverPort(Protocol):
    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr: ...

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str: ...


class UnavailableNodeSecretResolver(NodeSecretResolverPort):
    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        raise NodeSecretUnavailableError("Node secrets are unavailable in this runtime")

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        raise NodeSecretUnavailableError("Node secrets are unavailable in this runtime")


class NodeSecretRepositoryPort(Protocol):
    async def upsert(self, secret: EncryptedNodeSecret) -> None: ...

    async def get(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        node_id: str,
        name: str,
    ) -> EncryptedNodeSecret | None: ...

    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[EncryptedNodeSecret]: ...

    async def remove(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        node_id: str,
        name: str,
    ) -> None: ...


class NodeSecretUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def graphs(self) -> "SavedGraphRepositoryPort": ...

    @property
    def node_secrets(self) -> NodeSecretRepositoryPort: ...
