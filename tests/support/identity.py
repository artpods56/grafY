"""Shared test identity constants and helpers for the Grafy API test suite."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import FastAPI

from grafy_core.domain.identity import (
    ActorContext,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
TEST_USER_ID = UUID(int=1)
TEST_COMMAND_HMAC_KEY = "test-api-command-hmac-key"


def workspace_api_path(suffix: str) -> str:
    normalized = suffix if suffix.startswith("/") else f"/{suffix}"
    return f"/v1/workspaces/{WORKSPACE_ID}{normalized}"


def browser_actor_override() -> ActorContext:
    """The shared test actor, usable directly as a dependency override."""
    return ActorContext(
        user_id=TEST_USER_ID,
        credential_reference="test-session",
    )


def install_browser_actor_override(application: FastAPI) -> None:
    """Install the shared actor for browser-only and workspace HTTP routes."""

    application.dependency_overrides[browser_actor] = browser_actor_override
    application.dependency_overrides[workspace_actor] = browser_actor_override


@dataclass
class ActorSwitcher:
    """A browser-actor override that a test can repoint at another user.

    Register ``ActorSwitcher(user_id).actor`` for both ``browser_actor`` and
    ``workspace_actor``, then call ``as_user()`` to switch the acting user
    without re-registering anything.
    """

    user_id: UUID

    def actor(self) -> ActorContext:
        return ActorContext(
            user_id=self.user_id,
            credential_reference="test-session",
        )

    def as_user(self, user_id: UUID) -> None:
        self.user_id = user_id


async def create_schema(database_url: str) -> None:
    """Create the database schema and seed the shared test user/workspace."""

    database = create_database(database_url)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await unit_of_work.identity.add_user(
                User(
                    id=TEST_USER_ID,
                    email="owner@example.test",
                    display_name="Owner",
                )
            )
            await unit_of_work.identity.add_workspace(
                Workspace(
                    id=WORKSPACE_ID,
                    slug="team",
                    name="Team",
                    kind="shared",
                )
            )
            await unit_of_work.identity.add_membership(
                WorkspaceMembership(
                    workspace_id=WORKSPACE_ID,
                    user_id=TEST_USER_ID,
                    role=WorkspaceRole.OWNER,
                )
            )
            await unit_of_work.commit()
    finally:
        await database.dispose()


__all__ = [
    "TEST_COMMAND_HMAC_KEY",
    "TEST_USER_ID",
    "WORKSPACE_ID",
    "ActorSwitcher",
    "browser_actor_override",
    "create_schema",
    "install_browser_actor_override",
    "workspace_api_path",
]
