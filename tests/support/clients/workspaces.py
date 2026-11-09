from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient

from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreateRequest,
    PersonalAccessTokenCreatedResponse,
    WorkspaceCreateRequest,
    WorkspaceInvitationCreateRequest,
)
from tests.support.clients._http import _expect, _parse, _request
from tests.support.clients.artifacts import ArtifactsApi
from tests.support.clients.catalog import CatalogApi
from tests.support.clients.node_secrets import NodeSecretsApi
from tests.support.clients.projects import ProjectFoldersApi, ProjectsApi
from tests.support.clients.uploads import UploadsApi


class WorkspaceApi:
    """Resources scoped to one workspace: members and personal access tokens."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    # -- scoped clients ------------------------------------------------------

    @property
    def projects(self) -> ProjectsApi:
        return ProjectsApi(self._client, self._workspace_id)

    @property
    def project_folders(self) -> ProjectFoldersApi:
        return ProjectFoldersApi(self._client, self._workspace_id)

    @property
    def artifacts(self) -> ArtifactsApi:
        return ArtifactsApi(self._client, self._workspace_id)

    @property
    def catalog(self) -> CatalogApi:
        return CatalogApi(self._client, self._workspace_id)

    @property
    def uploads(self) -> UploadsApi:
        return UploadsApi(self._client, self._workspace_id)

    @property
    def node_secrets(self) -> NodeSecretsApi:
        return NodeSecretsApi(self._client, self._workspace_id)

    # -- members -----------------------------------------------------------

    def list_members(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/members", headers=headers
        )

    def create_invitation(
        self,
        payload: WorkspaceInvitationCreateRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/invitations",
            payload=payload,
            headers=headers,
        )

    def remove_member(
        self, user_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(
            f"/v1/workspaces/{self._workspace_id}/members/{user_id}", headers=headers
        )

    # -- personal access tokens ---------------------------------------------

    def list_tokens(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/personal-access-tokens",
            headers=headers,
        )

    def create_token(
        self,
        payload: PersonalAccessTokenCreateRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/personal-access-tokens",
            payload=payload,
            headers=headers,
        )

    def create_token_ok(
        self,
        payload: PersonalAccessTokenCreateRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> PersonalAccessTokenCreatedResponse:
        """Create a PAT; the raw token is readable once via ``.token``."""

        return _parse(
            PersonalAccessTokenCreatedResponse,
            _expect(self.create_token(payload, headers=headers), 201),
        )

    def revoke_token(
        self, token_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(
            f"/v1/workspaces/{self._workspace_id}/personal-access-tokens/{token_id}",
            headers=headers,
        )


class WorkspacesApi:
    """The ``/v1/workspaces`` collection endpoints."""

    __slots__ = ("_client",)

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def list(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get("/v1/workspaces", headers=headers)

    def create(
        self,
        payload: WorkspaceCreateRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            "/v1/workspaces",
            payload=payload,
            headers=headers,
        )
