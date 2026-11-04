from uuid import UUID

from pydantic import Field

from grafy_core.artifacts import LibraryProvenance
from .models import ClientModel
from .transport import HttpTransport


class LibraryArtifactSummary(ClientModel):
    artifact_id: UUID
    artifact_type: str
    schema_version: int
    content_type: str
    byte_size: int | None = None
    sha256: str | None = None
    text: str | None = None
    content_url: str | None = None
    download_formats: tuple[dict[str, object], ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)


class LibraryItem(ClientModel):
    artifact: LibraryArtifactSummary
    name: str
    provenance: LibraryProvenance
    folder_id: UUID | None = None


class LibraryClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def save_from_instance(
        self,
        workspace_id: UUID,
        *,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        result_fingerprint: str,
        output_port: str,
        name: str,
        call_path: tuple[str, ...] = (),
        map_index: int | None = None,
        item_index: int | None = None,
    ) -> LibraryItem:
        payload = await self._transport.request_json(
            operation="save node result to Library",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/library/artifacts/from-instance",
            json_payload={
                "project_id": str(project_id),
                "graph_id": graph_id,
                "node_id": node_id,
                "call_path": list(call_path),
                "map_index": map_index,
                "result_fingerprint": result_fingerprint,
                "output_port": output_port,
                "item_index": item_index,
                "name": name,
            },
        )
        return LibraryItem.model_validate(payload)
