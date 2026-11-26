from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from pydantic import Field

from grafy_core.artifacts import ArtifactRef, LibraryProvenance
from .models import ClientModel
from .transport import HttpTransport


class LibraryFolder(ClientModel):
    folder_id: UUID
    workspace_id: UUID
    parent_id: UUID | None
    name: str
    created_at: datetime
    updated_at: datetime


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

    @property
    def ref(self) -> ArtifactRef:
        """The exact reference an origin or card must carry, content hash included."""
        return ArtifactRef(
            artifact_id=self.artifact.artifact_id,
            artifact_type=self.artifact.artifact_type,
            schema_version=self.artifact.schema_version,
            content_hash=self.artifact.sha256,
        )


class LibraryClient:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def list(self, workspace_id: UUID) -> list[LibraryItem]:
        payload = await self._transport.request_json(
            operation="list Library artifacts",
            method="GET",
            path=f"/v1/workspaces/{workspace_id}/library/artifacts",
        )
        if not isinstance(payload, dict):
            raise TypeError("Expected a Library listing object")
        items = cast(dict[str, object], payload).get("items")
        if not isinstance(items, list):
            raise TypeError("Expected a Library listing with items")
        return [LibraryItem.model_validate(item) for item in cast(list[object], items)]

    async def save_from_upload(
        self,
        workspace_id: UUID,
        *,
        artifact_id: UUID,
        original_filename: str,
    ) -> LibraryItem:
        """Place an uploaded artifact in the Workspace Library under its file name."""
        payload = await self._transport.request_json(
            operation="save upload to Library",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/library/artifacts/from-upload",
            json_payload={
                "artifact_id": str(artifact_id),
                "original_filename": original_filename,
            },
        )
        return LibraryItem.model_validate(payload)

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

    async def delete(self, workspace_id: UUID, artifact_id: UUID) -> None:
        """Delete one Library artifact."""
        _ = await self._transport.send(
            operation="delete Library artifact",
            method="DELETE",
            path=f"/v1/workspaces/{workspace_id}/library/artifacts/{artifact_id}",
        )

    async def list_folders(self, workspace_id: UUID) -> list[LibraryFolder]:
        payload = await self._transport.request_json(
            operation="list Library folders",
            method="GET",
            path=f"/v1/workspaces/{workspace_id}/library/folders",
        )
        if not isinstance(payload, dict):
            raise TypeError("Expected a Library folder listing object")
        folders = cast(dict[str, object], payload).get("folders")
        if not isinstance(folders, list):
            raise TypeError("Expected a Library folder listing with folders")
        return [
            LibraryFolder.model_validate(folder)
            for folder in cast(list[object], folders)
        ]

    async def create_folder(
        self,
        workspace_id: UUID,
        *,
        name: str,
        parent_id: UUID | None = None,
    ) -> LibraryFolder:
        payload = await self._transport.request_json(
            operation="create Library folder",
            method="POST",
            path=f"/v1/workspaces/{workspace_id}/library/folders",
            json_payload={
                "name": name,
                "parent_id": str(parent_id) if parent_id is not None else None,
            },
        )
        return LibraryFolder.model_validate(payload)

    async def rename_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
        *,
        name: str,
    ) -> LibraryFolder:
        payload = await self._transport.request_json(
            operation="rename Library folder",
            method="PATCH",
            path=f"/v1/workspaces/{workspace_id}/library/folders/{folder_id}",
            json_payload={"name": name},
        )
        return LibraryFolder.model_validate(payload)

    async def delete_folder(self, workspace_id: UUID, folder_id: UUID) -> None:
        _ = await self._transport.send(
            operation="delete Library folder",
            method="DELETE",
            path=f"/v1/workspaces/{workspace_id}/library/folders/{folder_id}",
        )

    async def move_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
        *,
        parent_id: UUID | None,
    ) -> LibraryFolder:
        payload = await self._transport.request_json(
            operation="move Library folder",
            method="PUT",
            path=f"/v1/workspaces/{workspace_id}/library/folders/{folder_id}/parent",
            json_payload={
                "parent_id": str(parent_id) if parent_id is not None else None,
            },
        )
        return LibraryFolder.model_validate(payload)

    async def move_artifacts(
        self,
        workspace_id: UUID,
        *,
        artifact_ids: Sequence[UUID],
        folder_id: UUID | None,
    ) -> None:
        if not artifact_ids:
            raise ValueError("At least one artifact_id is required")
        _ = await self._transport.send(
            operation="move Library artifacts",
            method="PUT",
            path=f"/v1/workspaces/{workspace_id}/library/placements",
            json_payload={
                "artifact_ids": [str(artifact_id) for artifact_id in artifact_ids],
                "folder_id": str(folder_id) if folder_id is not None else None,
            },
        )


__all__ = [
    "LibraryArtifactSummary",
    "LibraryClient",
    "LibraryFolder",
    "LibraryItem",
]
