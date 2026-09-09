"""Test harness for the Grafy API.

This module provides typed, reusable helpers that replace the two
distinct injection mechanisms with a single coherent harness:

* ``create_app(settings)`` — application composition (lifespan resources)
* ``app.dependency_overrides`` — request-scoped FastAPI ``Depends()`` graph

The harness keeps those concerns separate so tests can replace
either one without confusion.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from grafy_api.main import create_app
from grafy_api.settings import Settings
from grafy_core.domain import (
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceKind,
    WorkspaceRole,
)
from grafy_persistence import SqlAlchemyUnitOfWork
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from tests.support.factories.identity import IdentitySeeder
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID

# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

type AppDependency = Callable[..., Any]
"""A FastAPI dependency callable used as ``Depends(callable)`` in a route."""

type DependencyOverride = Callable[..., Any]
"""A replacement callable registered via ``app.dependency_overrides[dep]``."""

# ---------------------------------------------------------------------------
# Async API harness
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AsyncApiHarness:
    """A running FastAPI application with an async HTTP client.

    The harness enters the ASGI lifespan before yielding so
    ``app.state.resources`` is fully populated.
    """

    app: FastAPI
    """The live FastAPI application (lifespan has already run)."""

    client: AsyncClient
    """An ``httpx.AsyncClient`` backed by ``ASGITransport`` for this app."""

    def override(
        self,
        dependency: AppDependency,
        override: DependencyOverride,
    ) -> None:
        """Replace one FastAPI dependency for the lifetime of this harness."""
        self.app.dependency_overrides[dependency] = override

    def clear_override(self, dependency: AppDependency) -> None:
        """Remove an earlier override, restoring the original dependency."""
        self.app.dependency_overrides.pop(dependency, None)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def app_with_overrides(
    *,
    settings: Settings,
    overrides: dict[AppDependency, DependencyOverride] | None = None,
) -> FastAPI:
    """Create a FastAPI app with the given *settings* and optional overrides.

    ``settings`` is forwarded directly to ``create_app()``, so every
    application-level resource (database, storage, plugin registry)
    is built from those values.

    ``overrides`` are bulk-applied to ``app.dependency_overrides``
    after the app is created.  They only affect the FastAPI
    ``Depends(...)`` graph, not the resources constructed during
    lifespan.
    """
    app = create_app(settings)

    if overrides:
        app.dependency_overrides.update(overrides)

    return app


# ---------------------------------------------------------------------------
# Async client context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def async_client_with_overrides(
    *,
    settings: Settings,
    overrides: dict[AppDependency, DependencyOverride] | None = None,
) -> AsyncIterator[AsyncApiHarness]:
    """Create an app, enter its lifespan, and yield a typed harness.

    Usage::

        async with async_client_with_overrides(settings=test_settings) as api:
            api.override(run_execution_manager, lambda: execution_manager)
            response = await api.client.get("/ready")
    """
    app = app_with_overrides(
        settings=settings,
        overrides=overrides,
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield AsyncApiHarness(
                app=app,
                client=client,
            )


# ---------------------------------------------------------------------------
# Synchronous TestClient context manager
# ---------------------------------------------------------------------------


@contextmanager
def client_with_overrides(
    *,
    settings: Settings,
    overrides: dict[AppDependency, DependencyOverride] | None = None,
) -> Iterator[TestClient]:
    """Create an app, enter its lifespan, and yield a ``TestClient``.

    The context manager form is required because Starlette only
    invokes lifespan events when ``TestClient`` is entered via
    ``with``.  Constructing ``TestClient(app)`` without entering it
    skips startup, so ``app.state.resources`` would be missing.

    Usage::

        with client_with_overrides(settings=test_settings) as client:
            response = client.get("/ready")
    """
    app = app_with_overrides(
        settings=settings,
        overrides=overrides,
    )

    with TestClient(app) as client:
        yield client


async def seed(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[User, Workspace, WorkspaceMembership]:
    seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork.from_factory(session_factory))
    user = await seeder.user()
    workspace = await seeder.workspace(
        kind=WorkspaceKind.PERSONAL, personal_owner_user_id=user.id
    )
    membership = await seeder.membership(
        user=user, workspace=workspace, role=WorkspaceRole.OWNER
    )
    return user, workspace, membership


async def seed_shared_workspace(
    database: Database,
    *,
    user_id: UUID = TEST_USER_ID,
    workspace_id: UUID = WORKSPACE_ID,
) -> tuple[User, Workspace, WorkspaceMembership]:
    """Seed the fixed-ID owner behind the built-in workbench clients.

    ``TEST_USER_ID`` and ``WORKSPACE_ID`` are the identities the shared
    browser-actor override and the workspace URL helpers assume; the
    workspace is shared and therefore carries no personal owner.
    """

    user = User(id=user_id, email="owner@example.test", display_name="Owner")
    workspace = Workspace(
        id=workspace_id,
        slug="team",
        name="Team",
        kind="shared",
    )
    membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=user_id,
        role=WorkspaceRole.OWNER,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.identity.add_user(user)
        await unit_of_work.identity.add_workspace(workspace)
        await unit_of_work.identity.add_membership(membership)
        await unit_of_work.commit()
    return user, workspace, membership


@asynccontextmanager
async def db(database_url: str) -> AsyncGenerator[Database]:
    database = create_database(database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

        yield database
    await database.dispose()


def create_db_url(tmp_path: Path, test_name: str) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / test_name}"
