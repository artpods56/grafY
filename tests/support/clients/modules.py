from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient

from grafy_api.v1.routes.modules.models import (
    ModuleListResponse,
    ModuleResponse,
    PublishModuleReleaseRequest,
)
from tests.support.clients._http import _expect, _parse, _request


class ModulesApi:
    """The ``/v1/workspaces/{workspace_id}/modules`` library endpoints."""

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    def list(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/modules", headers=headers
        )

    def list_ok(
        self, *, headers: Mapping[str, str] | None = None
    ) -> ModuleListResponse:
        return _parse(ModuleListResponse, _expect(self.list(headers=headers), 200))

    def get(
        self, module_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/modules/{module_id}",
            headers=headers,
        )

    def get_ok(
        self, module_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> ModuleResponse:
        return _parse(
            ModuleResponse, _expect(self.get(module_id, headers=headers), 200)
        )

    def publish(
        self,
        payload: PublishModuleReleaseRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/modules/publish",
            payload=payload,
            headers=headers,
        )

    def publish_ok(
        self,
        payload: PublishModuleReleaseRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ModuleResponse:
        return _parse(
            ModuleResponse, _expect(self.publish(payload, headers=headers), 201)
        )
