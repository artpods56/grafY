from types import TracebackType
from typing import Self
from uuid import UUID

import httpx
from pydantic import SecretStr

from grafy_core.domain.graph_documents import GraphDocument

from .execution import ExecutionHandle
from .library import LibraryClient
from .models import (
    ExecutionState,
    NodeCatalog,
    NodeSecretStatus,
    SavedGraph,
    UploadItem,
)
from .transport import HttpTransport


class CatalogClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def get(self, workspace_id: UUID) -> NodeCatalog:
        payload = await self._transport.request_json(
            operation="get workspace node catalog",
            method="GET",
            path=f"/v1/workspaces/{workspace_id}/nodes",
        )
        return NodeCatalog.model_validate(payload)


class GraphClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def create(
        self,
        workspace_id: UUID,
        *,
        name: str,
        document: GraphDocument,
    ) -> SavedGraph:
        payload = await self._transport.request_json(
            operation="create saved graph",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/graphs",
            json_payload={
                "name": name,
                "document": document.model_dump(mode="json"),
            },
        )
        return SavedGraph.model_validate(payload)

    async def get(self, workspace_id: UUID, graph_id: UUID) -> SavedGraph:
        payload = await self._transport.request_json(
            operation="get saved graph",
            method="GET",
            path=f"/v1/workspaces/{workspace_id}/graphs/{graph_id}",
        )
        return SavedGraph.model_validate(payload)

    async def update(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        name: str,
        document: GraphDocument,
        expected_revision: int,
    ) -> SavedGraph:
        payload = await self._transport.request_json(
            operation="update saved graph",
            method="PUT",
            path=f"/v1/workspaces/{workspace_id}/graphs/{graph_id}",
            json_payload={
                "name": name,
                "document": document.model_dump(mode="json"),
                "expected_revision": expected_revision,
            },
        )
        return SavedGraph.model_validate(payload)

    async def configure_secret(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        node_id: str,
        secret_name: str,
        value: SecretStr,
        expected_revision: int,
    ) -> NodeSecretStatus:
        secret = value.get_secret_value()
        if secret == "":
            raise ValueError("Graph node secret value must not be empty")
        payload = await self._transport.request_json(
            operation="configure graph node secret",
            method="PUT",
            path=(
                f"/v1/workspaces/{workspace_id}/graphs/{graph_id}/nodes/"
                f"{node_id}/secrets/{secret_name}"
            ),
            json_payload={
                "value": secret,
                "expected_graph_revision": expected_revision,
            },
            sensitive_values=(secret,),
        )
        return NodeSecretStatus.model_validate(payload)

    async def execute(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        expected_revision: int,
        idempotency_key: str | None = None,
    ) -> ExecutionHandle:
        headers: dict[str, str] = {}
        if idempotency_key is not None:
            if idempotency_key.strip() == "":
                raise ValueError("Execution idempotency key must not be blank")
            headers["Idempotency-Key"] = idempotency_key
        payload = await self._transport.request_json(
            operation="start saved graph execution",
            method="POST",
            path=(f"/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions"),
            json_payload={"expected_revision": expected_revision},
            headers=headers,
        )
        return ExecutionHandle(
            transport=self._transport,
            workspace_id=workspace_id,
            state=ExecutionState.model_validate(payload),
        )


class UploadClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def create(
        self,
        workspace_id: UUID,
        *,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> UploadItem:
        if filename.strip() == "":
            raise ValueError("Upload filename must not be blank")
        payload = await self._transport.request_json(
            operation="upload workspace file",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/uploads",
            files={"file": (filename, content, content_type)},
        )
        return UploadItem.model_validate(payload)


class GrafyClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: SecretStr,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._transport = HttpTransport(
            base_url=base_url,
            token=token,
            timeout=timeout,
            transport=transport,
        )
        self.catalog = CatalogClient(self._transport)
        self.graphs = GraphClient(self._transport)
        self.uploads = UploadClient(self._transport)
        self.library = LibraryClient(self._transport)

    def __repr__(self) -> str:
        return f"GrafyClient(base_url={self._transport.base_url!r}, token=<redacted>)"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._transport.close()


__all__ = ["CatalogClient", "GrafyClient", "GraphClient", "UploadClient"]
