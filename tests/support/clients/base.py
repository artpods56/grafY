"""The ``GrafyApi`` facade assembling the per-resource clients."""

from __future__ import annotations

from uuid import UUID

from starlette.testclient import TestClient

from grafy_api.auth import IssuedSession
from tests.support.clients.auth import AuthApi
from tests.support.clients.projects import ProjectBrowserApi
from tests.support.clients.workspaces import WorkspaceApi, WorkspacesApi


class GrafyApi:
    """Entry point wrapping an existing ``TestClient``.

    ``raw`` is the deliberate escape hatch for tests that exercise the
    HTTP boundary itself: malformed payloads, wrong methods, hostile
    headers, or routes the facade does not cover yet.
    """

    __slots__ = ("raw", "auth", "workspaces", "project_browser")

    def __init__(self, client: TestClient) -> None:
        self.raw = client
        self.auth = AuthApi(client)
        self.workspaces = WorkspacesApi(client)
        self.project_browser = ProjectBrowserApi(client)

    def authenticate(self, issued: IssuedSession) -> None:
        """Install browser session cookies obtained from ``issue_session``."""

        self.raw.cookies.set("grafy_session", issued.cookie_value)
        self.raw.cookies.set("grafy_csrf", issued.csrf_value)

    def workspace(self, workspace_id: UUID) -> WorkspaceApi:
        """Return a client scoped to one workspace's members and tokens."""

        return WorkspaceApi(self.raw, workspace_id)
