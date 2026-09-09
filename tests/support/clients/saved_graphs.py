from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient

from grafy_api.graph_contracts import (
    AssignGraphFolderRequest,
    CheckpointGraphRequest,
    CheckpointGraphResponse,
    CollaborativeHeadResponse,
    CopyExactHeadRequest,
    CreateSavedGraphRequest,
    GraphBrowserListResponse,
    GraphFolderListResponse,
    GraphFolderResponse,
    GraphFolderWriteRequest,
    GraphOrganizationResponse,
    SavedGraphListResponse,
    SavedGraphResponse,
    SubmitGraphCommandRequest,
    SubmitGraphCommandResponse,
    UpdateSavedGraphRequest,
    UserGraphStateResponse,
)
from tests.support.clients._http import _expect, _parse, _request


class GraphBrowserApi:
    """The ``/v1/me/graphs`` browser collection."""

    __slots__ = ("_client",)

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def list(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get("/v1/me/graphs", headers=headers)

    def list_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> GraphBrowserListResponse:
        return _parse(
            GraphBrowserListResponse, _expect(self.list(headers=headers), 200)
        )


class GraphFoldersApi:
    """The ``/v1/workspaces/{workspace_id}/graph-folders`` endpoints."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    def list(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/graph-folders", headers=headers
        )

    def list_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> GraphFolderListResponse:
        return _parse(GraphFolderListResponse, _expect(self.list(headers=headers), 200))

    def create(
        self,
        payload: GraphFolderWriteRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/graph-folders",
            payload=payload,
            headers=headers,
        )

    def create_ok(
        self,
        payload: GraphFolderWriteRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> GraphFolderResponse:
        return _parse(
            GraphFolderResponse,
            _expect(self.create(payload, headers=headers), 201),
        )

    def rename(
        self,
        folder_id: UUID,
        payload: GraphFolderWriteRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "PATCH",
            f"/v1/workspaces/{self._workspace_id}/graph-folders/{folder_id}",
            payload=payload,
            headers=headers,
        )

    def rename_ok(
        self,
        folder_id: UUID,
        payload: GraphFolderWriteRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> GraphFolderResponse:
        return _parse(
            GraphFolderResponse,
            _expect(self.rename(folder_id, payload, headers=headers), 200),
        )

    def delete(
        self, folder_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(
            f"/v1/workspaces/{self._workspace_id}/graph-folders/{folder_id}",
            headers=headers,
        )


class SavedGraphsApi:
    """The ``/v1/workspaces/{workspace_id}/graphs`` endpoints."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    # -- documents ------------------------------------------------------------

    def list(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/graphs", headers=headers
        )

    def list_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> SavedGraphListResponse:
        return _parse(SavedGraphListResponse, _expect(self.list(headers=headers), 200))

    def create(
        self,
        payload: CreateSavedGraphRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/graphs",
            payload=payload,
            headers=headers,
        )

    def create_ok(
        self,
        payload: CreateSavedGraphRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> SavedGraphResponse:
        return _parse(
            SavedGraphResponse,
            _expect(self.create(payload, headers=headers), 201),
        )

    def copy(
        self,
        payload: CopyExactHeadRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/graphs/copies",
            payload=payload,
            headers=headers,
        )

    def copy_ok(
        self,
        payload: CopyExactHeadRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> SavedGraphResponse:
        return _parse(
            SavedGraphResponse,
            _expect(self.copy(payload, headers=headers), 201),
        )

    def get(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}", headers=headers
        )

    def get_ok(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> SavedGraphResponse:
        return _parse(
            SavedGraphResponse, _expect(self.get(graph_id, headers=headers), 200)
        )

    def update(
        self,
        graph_id: UUID,
        payload: UpdateSavedGraphRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "PUT",
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}",
            payload=payload,
            headers=headers,
        )

    def update_ok(
        self,
        graph_id: UUID,
        payload: UpdateSavedGraphRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> SavedGraphResponse:
        return _parse(
            SavedGraphResponse,
            _expect(self.update(graph_id, payload, headers=headers), 200),
        )

    def delete(
        self,
        graph_id: UUID,
        *,
        expected_revision: int,
        expected_room_epoch: UUID | None = None,
        expected_sequence: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        params: dict[str, str] = {"expected_revision": str(expected_revision)}
        if expected_room_epoch is not None:
            params["expected_room_epoch"] = str(expected_room_epoch)
        if expected_sequence is not None:
            params["expected_sequence"] = str(expected_sequence)
        return self._client.delete(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}",
            params=params,
            headers=headers,
        )

    # -- collaboration --------------------------------------------------------

    def get_head(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/head",
            headers=headers,
        )

    def get_head_ok(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> CollaborativeHeadResponse:
        return _parse(
            CollaborativeHeadResponse,
            _expect(self.get_head(graph_id, headers=headers), 200),
        )

    def submit_command(
        self,
        graph_id: UUID,
        payload: SubmitGraphCommandRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/commands",
            payload=payload,
            headers=headers,
        )

    def submit_command_ok(
        self,
        graph_id: UUID,
        payload: SubmitGraphCommandRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> SubmitGraphCommandResponse:
        return _parse(
            SubmitGraphCommandResponse,
            _expect(self.submit_command(graph_id, payload, headers=headers), 200),
        )

    def checkpoint(
        self,
        graph_id: UUID,
        payload: CheckpointGraphRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/checkpoint",
            payload=payload,
            headers=headers,
        )

    def checkpoint_ok(
        self,
        graph_id: UUID,
        payload: CheckpointGraphRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> CheckpointGraphResponse:
        return _parse(
            CheckpointGraphResponse,
            _expect(self.checkpoint(graph_id, payload, headers=headers), 200),
        )

    # -- organization ---------------------------------------------------------

    def assign_folder(
        self,
        graph_id: UUID,
        payload: AssignGraphFolderRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "PUT",
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/folder",
            payload=payload,
            headers=headers,
        )

    def assign_folder_ok(
        self,
        graph_id: UUID,
        payload: AssignGraphFolderRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> GraphOrganizationResponse:
        return _parse(
            GraphOrganizationResponse,
            _expect(self.assign_folder(graph_id, payload, headers=headers), 200),
        )

    def archive(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.put(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/archive",
            headers=headers,
        )

    def archive_ok(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> GraphOrganizationResponse:
        return _parse(
            GraphOrganizationResponse,
            _expect(self.archive(graph_id, headers=headers), 200),
        )

    def restore(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/archive",
            headers=headers,
        )

    def restore_ok(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> GraphOrganizationResponse:
        return _parse(
            GraphOrganizationResponse,
            _expect(self.restore(graph_id, headers=headers), 200),
        )

    def star(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.put(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/star",
            headers=headers,
        )

    def star_ok(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> UserGraphStateResponse:
        return _parse(
            UserGraphStateResponse, _expect(self.star(graph_id, headers=headers), 200)
        )

    def unstar(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/star",
            headers=headers,
        )

    def unstar_ok(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> UserGraphStateResponse:
        return _parse(
            UserGraphStateResponse,
            _expect(self.unstar(graph_id, headers=headers), 200),
        )

    def record_open(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.post(
            f"/v1/workspaces/{self._workspace_id}/graphs/{graph_id}/opened",
            headers=headers,
        )

    def record_open_ok(
        self, graph_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> UserGraphStateResponse:
        return _parse(
            UserGraphStateResponse,
            _expect(self.record_open(graph_id, headers=headers), 200),
        )
