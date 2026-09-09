from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient

from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreateRequest,
    PersonalAccessTokenCreatedResponse,
    PersonalAccessTokenResponse,
    WorkspaceCreateRequest,
    WorkspaceInvitationCandidateRequest,
    WorkspaceInvitationCandidateResponse,
    WorkspaceInvitationCreateRequest,
    WorkspaceInvitationOwnerResponse,
    WorkspaceMemberResponse,
    WorkspaceMemberRoleRequest,
    WorkspaceResponse,
)
from tests.support.clients._http import _expect, _parse, _parse_list, _request
from tests.support.clients.artifacts import ArtifactsApi
from tests.support.clients.catalog import CatalogApi
from tests.support.clients.executions import ExecutionsApi
from tests.support.clients.modules import ModulesApi
from tests.support.clients.node_secrets import NodeSecretsApi
from tests.support.clients.saved_graphs import GraphFoldersApi, SavedGraphsApi
from tests.support.clients.templates import TemplatesApi
from tests.support.clients.uploads import UploadsApi


class WorkspaceApi:
    """Resources scoped to one workspace: members and personal access tokens."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    # -- scoped clients ------------------------------------------------------

    @property
    def graphs(self) -> SavedGraphsApi:
        return SavedGraphsApi(self._client, self._workspace_id)

    @property
    def graph_folders(self) -> GraphFoldersApi:
        return GraphFoldersApi(self._client, self._workspace_id)

    @property
    def executions(self) -> ExecutionsApi:
        return ExecutionsApi(self._client, self._workspace_id)

    @property
    def artifacts(self) -> ArtifactsApi:
        return ArtifactsApi(self._client, self._workspace_id)

    @property
    def modules(self) -> ModulesApi:
        return ModulesApi(self._client, self._workspace_id)

    @property
    def catalog(self) -> CatalogApi:
        return CatalogApi(self._client, self._workspace_id)

    @property
    def templates(self) -> TemplatesApi:
        return TemplatesApi(self._client, self._workspace_id)

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

    def list_members_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> list[WorkspaceMemberResponse]:
        response = _expect(self.list_members(headers=headers), 200)
        return _parse_list(WorkspaceMemberResponse, response)

    def resolve_invitation_candidate(
        self,
        payload: WorkspaceInvitationCandidateRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/invitation-candidates/resolve",
            payload=payload,
            headers=headers,
        )

    def resolve_invitation_candidate_ok(
        self,
        payload: WorkspaceInvitationCandidateRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> WorkspaceInvitationCandidateResponse:
        return _parse(
            WorkspaceInvitationCandidateResponse,
            _expect(self.resolve_invitation_candidate(payload, headers=headers), 200),
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

    def create_invitation_ok(
        self,
        payload: WorkspaceInvitationCreateRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> WorkspaceInvitationOwnerResponse:
        return _parse(
            WorkspaceInvitationOwnerResponse,
            _expect(self.create_invitation(payload, headers=headers), 201),
        )

    def change_member_role(
        self,
        user_id: UUID,
        payload: WorkspaceMemberRoleRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "PATCH",
            f"/v1/workspaces/{self._workspace_id}/members/{user_id}",
            payload=payload,
            headers=headers,
        )

    def change_member_role_ok(
        self,
        user_id: UUID,
        payload: WorkspaceMemberRoleRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> WorkspaceMemberResponse:
        return _parse(
            WorkspaceMemberResponse,
            _expect(self.change_member_role(user_id, payload, headers=headers), 200),
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

    def list_tokens_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> list[PersonalAccessTokenResponse]:
        response = _expect(self.list_tokens(headers=headers), 200)
        return _parse_list(PersonalAccessTokenResponse, response)

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

    def list_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> list[WorkspaceResponse]:
        response = _expect(self.list(headers=headers), 200)
        return _parse_list(WorkspaceResponse, response)

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

    def create_ok(
        self,
        payload: WorkspaceCreateRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> WorkspaceResponse:
        return _parse(
            WorkspaceResponse, _expect(self.create(payload, headers=headers), 201)
        )
