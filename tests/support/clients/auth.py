from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient


class AuthApi:
    """``/v1/auth`` session endpoints."""

    __slots__ = ("_client",)

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def get_session(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.get("/v1/auth/session", headers=headers)

    def logout(self, *, headers: Mapping[str, str] | None = None) -> Response:
        return self._client.delete("/v1/auth/session", headers=headers)

    def revoke_session(
        self, session_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.delete(f"/v1/auth/sessions/{session_id}", headers=headers)
