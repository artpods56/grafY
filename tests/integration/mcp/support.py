"""Shared test stage for driving the `/mcp` endpoint with real PAT credentials."""

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx2
from fastapi.testclient import TestClient
from pydantic import SecretStr

from grafy_api.auth import AuthService
from grafy_api.settings import Settings
from grafy_core.application.identity import IdentityService
from grafy_core.domain.identity import (
    ActorContext,
    Workspace,
    WorkspaceCapability,
    WorkspaceKind,
    WorkspaceRole,
)
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig

from tests.support.factories.identity import IdentitySeeder
from tests.testkit import client_with_overrides, create_db_url, db, with_setting_values

EDITOR_SCOPES = (
    WorkspaceCapability.VIEW_PROJECT,
    WorkspaceCapability.VIEW_ARTIFACTS,
    WorkspaceCapability.VIEW_RUNS,
    WorkspaceCapability.CREATE_PROJECT,
    WorkspaceCapability.EDIT_PROJECT,
    WorkspaceCapability.CHECKPOINT_PROJECT,
    WorkspaceCapability.START_RUN,
    WorkspaceCapability.CANCEL_RUN,
)
READER_SCOPES = (
    WorkspaceCapability.VIEW_PROJECT,
    WorkspaceCapability.VIEW_ARTIFACTS,
)
ACCEPT = "application/json, text/event-stream"


@dataclass(frozen=True)
class Stage:
    client: TestClient
    workspace: Workspace
    other_workspace: Workspace
    editor_token: str
    reader_token: str
    session_cookie: str
    csrf_value: str

    def rpc(
        self,
        method: str,
        params: dict[str, object],
        *,
        token: str | None,
        cookies: dict[str, str] | None = None,
    ) -> httpx2.Response:
        headers = {"Accept": ACCEPT}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        self.client.cookies.clear()
        for name, value in (cookies or {}).items():
            self.client.cookies.set(name, value)
        try:
            return self.client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                headers=headers,
            )
        finally:
            self.client.cookies.clear()

    def tool(
        self, name: str, arguments: dict[str, object], *, token: str
    ) -> dict[str, Any]:
        """Call one tool and return its JSON-RPC result (``isError`` included)."""

        response = self.rpc(
            "tools/call", {"name": name, "arguments": arguments}, token=token
        )
        assert response.status_code == 200, response.text
        body = cast(dict[str, Any], response.json())
        assert "result" in body, body
        return cast(dict[str, Any], body["result"])

    def ok(self, name: str, arguments: dict[str, object], *, token: str) -> Any:
        result = self.tool(name, arguments, token=token)
        assert not result.get("isError"), result
        structured = cast(dict[str, Any], result["structuredContent"])
        return structured.get("result", structured)


def _auth_service(settings: Settings, database: Database) -> AuthService:
    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    return AuthService(
        auth=settings.auth,
        public_origin=settings.app.public_origin,
        unit_of_work_factory=unit_of_work_factory,
        identity_service=IdentityService(unit_of_work_factory),
    )


@contextmanager
def stage_for(tmp_path: Path, name: str) -> Generator[Stage]:
    database_url = create_db_url(tmp_path, name)
    settings = with_setting_values(
        Settings(
            app=AppConfig(
                public_origin="http://testserver",
                database_url=SecretStr("sqlite+aiosqlite:///"),
            )
        ),
        database_url=SecretStr(database_url),
        workspace=tmp_path / "workbench",
    )

    async def prepare() -> tuple[Workspace, Workspace, str, str, str, str]:
        async with db(database_url) as database:
            seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
            owner = await seeder.user(email="owner@example.test", display_name="Owner")
            workspace = Workspace(slug="lab", name="Lab", kind=WorkspaceKind.SHARED)
            other = Workspace(slug="other", name="Other", kind=WorkspaceKind.SHARED)
            async with SqlAlchemyUnitOfWork(database.sessions) as uow:
                await uow.identity.add_workspace(workspace)
                await uow.identity.add_workspace(other)
                await uow.commit()
            for target in (workspace, other):
                await seeder.membership(
                    user=owner, workspace=target, role=WorkspaceRole.OWNER
                )
            auth = _auth_service(settings, database)
            identity = IdentityService(lambda: SqlAlchemyUnitOfWork(database.sessions))
            raw_tokens: list[str] = []
            for label, scopes in (("editor", EDITOR_SCOPES), ("reader", READER_SCOPES)):
                token, raw = auth.issue_personal_access_token(
                    user_id=owner.id,
                    workspace_id=workspace.id,
                    label=label,
                    scopes=scopes,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
                _ = await identity.create_personal_access_token(
                    actor=ActorContext(user_id=owner.id), token=token
                )
                raw_tokens.append(raw)
            session = await auth.issue_session(owner.id)
            return (
                workspace,
                other,
                raw_tokens[0],
                raw_tokens[1],
                session.cookie_value,
                session.csrf_value,
            )

    workspace, other, editor, reader, cookie, csrf_value = asyncio.run(prepare())
    with client_with_overrides(settings=settings) as client:
        yield Stage(
            client=client,
            workspace=workspace,
            other_workspace=other,
            editor_token=editor,
            reader_token=reader,
            session_cookie=cookie,
            csrf_value=csrf_value,
        )
