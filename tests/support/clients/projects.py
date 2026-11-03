from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient

from grafy_api.project_contracts import (
    AssignProjectFolderRequest,
    CheckpointProjectRequest,
    CheckpointProjectResponse,
    CopyExactHeadRequest,
    CreateProjectRequest,
    ProjectBrowserListResponse,
    ProjectCheckpointListResponse,
    ProjectCheckpointResponse,
    ProjectFolderListResponse,
    ProjectFolderResponse,
    ProjectFolderWriteRequest,
    ProjectHeadResponse,
    ProjectListResponse,
    ProjectOrganizationResponse,
    ProjectResponse,
    SubmitProjectCommandRequest,
    SubmitProjectCommandResponse,
    UserProjectStateResponse,
)
from tests.support.clients._http import _expect, _parse, _request


class ProjectBrowserApi:
    """The ``/v1/me/projects`` browser collection."""

    __slots__ = ("_client",)

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def list(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get("/v1/me/projects", headers=headers)

    def list_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> ProjectBrowserListResponse:
        return _parse(
            ProjectBrowserListResponse, _expect(self.list(headers=headers), 200)
        )


class ProjectFoldersApi:
    """The ``/v1/workspaces/{workspace_id}/project-folders`` endpoints."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    def list(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/project-folders", headers=headers
        )

    def list_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> ProjectFolderListResponse:
        return _parse(
            ProjectFolderListResponse, _expect(self.list(headers=headers), 200)
        )

    def create(
        self,
        payload: ProjectFolderWriteRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/project-folders",
            payload=payload,
            headers=headers,
        )

    def create_ok(
        self,
        payload: ProjectFolderWriteRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ProjectFolderResponse:
        return _parse(
            ProjectFolderResponse,
            _expect(self.create(payload, headers=headers), 201),
        )

    def rename(
        self,
        folder_id: UUID,
        payload: ProjectFolderWriteRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "PATCH",
            f"/v1/workspaces/{self._workspace_id}/project-folders/{folder_id}",
            payload=payload,
            headers=headers,
        )

    def rename_ok(
        self,
        folder_id: UUID,
        payload: ProjectFolderWriteRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ProjectFolderResponse:
        return _parse(
            ProjectFolderResponse,
            _expect(self.rename(folder_id, payload, headers=headers), 200),
        )

    def delete(
        self, folder_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(
            f"/v1/workspaces/{self._workspace_id}/project-folders/{folder_id}",
            headers=headers,
        )


class ProjectsApi:
    """The ``/v1/workspaces/{workspace_id}/projects`` endpoints."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    def _path(self, suffix: str = "") -> str:
        return f"/v1/workspaces/{self._workspace_id}/projects{suffix}"

    # -- the Project itself ---------------------------------------------------

    def list(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get(self._path(), headers=headers)

    def list_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> ProjectListResponse:
        return _parse(ProjectListResponse, _expect(self.list(headers=headers), 200))

    def create(
        self,
        payload: CreateProjectRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client, "POST", self._path(), payload=payload, headers=headers
        )

    def create_ok(
        self,
        payload: CreateProjectRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ProjectResponse:
        return _parse(
            ProjectResponse, _expect(self.create(payload, headers=headers), 201)
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
            self._path("/copies"),
            payload=payload,
            headers=headers,
        )

    def copy_ok(
        self,
        payload: CopyExactHeadRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ProjectResponse:
        return _parse(ProjectResponse, _expect(self.copy(payload, headers=headers), 201))

    def get(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.get(self._path(f"/{project_id}"), headers=headers)

    def get_ok(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> ProjectResponse:
        return _parse(
            ProjectResponse, _expect(self.get(project_id, headers=headers), 200)
        )

    def delete(
        self,
        project_id: UUID,
        *,
        expected_room_epoch: UUID | None = None,
        expected_sequence: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        params: dict[str, str] = {}
        if expected_room_epoch is not None:
            params["expected_room_epoch"] = str(expected_room_epoch)
        if expected_sequence is not None:
            params["expected_sequence"] = str(expected_sequence)
        return self._client.delete(
            self._path(f"/{project_id}"), params=params, headers=headers
        )

    # -- head and command batches ---------------------------------------------

    def get_head(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.get(self._path(f"/{project_id}/head"), headers=headers)

    def get_head_ok(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> ProjectHeadResponse:
        return _parse(
            ProjectHeadResponse,
            _expect(self.get_head(project_id, headers=headers), 200),
        )

    def submit_commands(
        self,
        project_id: UUID,
        payload: SubmitProjectCommandRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            self._path(f"/{project_id}/commands"),
            payload=payload,
            headers=headers,
        )

    def submit_commands_ok(
        self,
        project_id: UUID,
        payload: SubmitProjectCommandRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> SubmitProjectCommandResponse:
        return _parse(
            SubmitProjectCommandResponse,
            _expect(self.submit_commands(project_id, payload, headers=headers), 200),
        )

    # -- checkpoints ----------------------------------------------------------

    def checkpoint(
        self,
        project_id: UUID,
        payload: CheckpointProjectRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            self._path(f"/{project_id}/checkpoints"),
            payload=payload,
            headers=headers,
        )

    def checkpoint_ok(
        self,
        project_id: UUID,
        payload: CheckpointProjectRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> CheckpointProjectResponse:
        return _parse(
            CheckpointProjectResponse,
            _expect(self.checkpoint(project_id, payload, headers=headers), 200),
        )

    def list_checkpoints(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.get(
            self._path(f"/{project_id}/checkpoints"), headers=headers
        )

    def list_checkpoints_ok(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> ProjectCheckpointListResponse:
        return _parse(
            ProjectCheckpointListResponse,
            _expect(self.list_checkpoints(project_id, headers=headers), 200),
        )

    def get_checkpoint(
        self,
        project_id: UUID,
        revision: int,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._client.get(
            self._path(f"/{project_id}/checkpoints/{revision}"), headers=headers
        )

    def get_checkpoint_ok(
        self,
        project_id: UUID,
        revision: int,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ProjectCheckpointResponse:
        return _parse(
            ProjectCheckpointResponse,
            _expect(self.get_checkpoint(project_id, revision, headers=headers), 200),
        )

    def restore_checkpoint(
        self,
        project_id: UUID,
        revision: int,
        payload: CheckpointProjectRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            self._path(f"/{project_id}/checkpoints/{revision}/restore"),
            payload=payload,
            headers=headers,
        )

    def restore_checkpoint_ok(
        self,
        project_id: UUID,
        revision: int,
        payload: CheckpointProjectRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> CheckpointProjectResponse:
        return _parse(
            CheckpointProjectResponse,
            _expect(
                self.restore_checkpoint(project_id, revision, payload, headers=headers),
                200,
            ),
        )

    # -- organization and per-user state --------------------------------------

    def assign_folder(
        self,
        project_id: UUID,
        payload: AssignProjectFolderRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "PUT",
            self._path(f"/{project_id}/folder"),
            payload=payload,
            headers=headers,
        )

    def assign_folder_ok(
        self,
        project_id: UUID,
        payload: AssignProjectFolderRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ProjectOrganizationResponse:
        return _parse(
            ProjectOrganizationResponse,
            _expect(self.assign_folder(project_id, payload, headers=headers), 200),
        )

    def archive(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.put(self._path(f"/{project_id}/archive"), headers=headers)

    def archive_ok(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> ProjectOrganizationResponse:
        return _parse(
            ProjectOrganizationResponse,
            _expect(self.archive(project_id, headers=headers), 200),
        )

    def unarchive(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(
            self._path(f"/{project_id}/archive"), headers=headers
        )

    def unarchive_ok(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> ProjectOrganizationResponse:
        return _parse(
            ProjectOrganizationResponse,
            _expect(self.unarchive(project_id, headers=headers), 200),
        )

    def star(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.put(self._path(f"/{project_id}/star"), headers=headers)

    def star_ok(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> UserProjectStateResponse:
        return _parse(
            UserProjectStateResponse, _expect(self.star(project_id, headers=headers), 200)
        )

    def unstar(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(self._path(f"/{project_id}/star"), headers=headers)

    def unstar_ok(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> UserProjectStateResponse:
        return _parse(
            UserProjectStateResponse,
            _expect(self.unstar(project_id, headers=headers), 200),
        )

    def record_open(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.post(self._path(f"/{project_id}/opened"), headers=headers)

    def record_open_ok(
        self, project_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> UserProjectStateResponse:
        return _parse(
            UserProjectStateResponse,
            _expect(self.record_open(project_id, headers=headers), 200),
        )
