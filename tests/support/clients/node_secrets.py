from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient

from grafy_api.v1.routes.node_secrets.models import (
    ConfigureNodeSecretRequest,
    NodeSecretStatusResponse,
    ProjectNodeSecretsResponse,
)
from tests.support.clients._http import _expect, _parse


class NodeSecretsApi:
    """Node secrets under ``/v1/workspaces/{workspace_id}/projects``."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    def _base(self, project_id: UUID) -> str:
        return f"/v1/workspaces/{self._workspace_id}/projects/{project_id}"

    # -- Project-scoped secret status -----------------------------------------

    def list_secrets(
        self,
        project_id: UUID,
        *,
        graph_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        params = {} if graph_id is None else {"graph_id": graph_id}
        return self._client.get(
            f"{self._base(project_id)}/node-secrets",
            params=params,
            headers=headers,
        )

    def list_secrets_ok(
        self,
        project_id: UUID,
        *,
        graph_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ProjectNodeSecretsResponse:
        return _parse(
            ProjectNodeSecretsResponse,
            _expect(
                self.list_secrets(project_id, graph_id=graph_id, headers=headers), 200
            ),
        )

    # -- per-node secret configuration ----------------------------------------

    def configure_secret(
        self,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        payload: ConfigureNodeSecretRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Configure one node secret.

        ``ConfigureNodeSecretRequest.value`` is a redacting ``SecretStr``;
        the generic ``model_dump(mode="json")`` path would send the
        redaction sentinel, so the body is assembled from the model dump
        with only the secret un-redacted.
        """

        body = payload.model_dump(mode="json")
        body["value"] = payload.value.get_secret_value()
        return self._client.put(
            f"{self._base(project_id)}/graphs/{graph_id}/nodes/{node_id}/secrets/{name}",
            json=body,
            headers=headers,
        )

    def configure_secret_ok(
        self,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        payload: ConfigureNodeSecretRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> NodeSecretStatusResponse:
        return _parse(
            NodeSecretStatusResponse,
            _expect(
                self.configure_secret(
                    project_id, graph_id, node_id, name, payload, headers=headers
                ),
                200,
            ),
        )

    def remove_secret(
        self,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        expected_head_sequence: int,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._client.delete(
            f"{self._base(project_id)}/graphs/{graph_id}/nodes/{node_id}/secrets/{name}",
            params={"expected_head_sequence": expected_head_sequence},
            headers=headers,
        )
