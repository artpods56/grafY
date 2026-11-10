"""One-API-owner startup fence and restart recovery of Runs."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from grafy_api.app_state import get_resources
from grafy_api.main import create_app
from grafy_api.realtime.hub import ProjectRoomHub
from grafy_api.settings import Settings
from grafy_api.single_owner import ApiOwnerLease, assert_single_http_worker
from grafy_api.artifacts.service import ArtifactService
from grafy_core.application.collaboration import CollaborationService
from grafy_core.domain.identity import ActorContext, WorkspaceRole
from grafy_core.domain.runs import Run, RunStatus
from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig, KeysConfig
from pydantic import SecretStr

from tests.support.factories.identity import IdentitySeeder

pytestmark = pytest.mark.single_api_owner


def test_require_single_api_owner_defaults_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GRAFY_REQUIRE_SINGLE_API_OWNER", raising=False)
    assert AppConfig(_env_file=None).require_single_api_owner is True  # pyright: ignore[reportCallIssue]


def test_assert_single_http_worker_rejects_multi_worker_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError, match="exactly one API HTTP worker"):
        assert_single_http_worker()


def test_api_owner_lease_rejects_second_holder(tmp_path: Path) -> None:
    lock_path = tmp_path / ".grafy-api-owner.lock"
    first = ApiOwnerLease(lock_path)
    first.acquire()
    try:
        second = ApiOwnerLease(lock_path)
        with pytest.raises(RuntimeError, match="Another Grafy API owner"):
            second.acquire()
    finally:
        first.release()


def _settings(tmp_path: Path, database_url: str, *, single_owner: bool) -> Settings:
    return Settings(
        app=AppConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
            require_single_api_owner=single_owner,
        ),
        keys=KeysConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            command_hmac_key=SecretStr("test-single-owner-hmac-key"),  # pyright: ignore[reportCallIssue]
        ),
    )


@pytest.mark.asyncio
async def test_create_app_startup_acquires_owner_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'owner.sqlite3'}"
    database = create_database(database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    await database.dispose()

    shutdown_order: list[str] = []
    original_hub_shutdown = ProjectRoomHub.shutdown
    original_artifact_close = ArtifactService.close

    async def close_rooms(hub: ProjectRoomHub) -> None:
        shutdown_order.append("rooms")
        await original_hub_shutdown(hub)

    async def close_artifacts(artifacts: ArtifactService) -> None:
        shutdown_order.append("artifacts")
        await original_artifact_close(artifacts)

    monkeypatch.setattr(ProjectRoomHub, "shutdown", close_rooms)
    monkeypatch.setattr(ArtifactService, "close", close_artifacts)
    app = create_app(_settings(tmp_path, database_url, single_owner=True))
    async with LifespanManager(app):
        lock_path = tmp_path / "workbench" / ".grafy-api-owner.lock"
        assert lock_path.is_file()
        contested = ApiOwnerLease(lock_path)
        with pytest.raises(RuntimeError, match="Another Grafy API owner"):
            contested.acquire()
    assert shutdown_order == ["rooms", "artifacts"]
    with pytest.raises(RuntimeError, match="not initialized"):
        get_resources(app)
    contested.acquire()
    contested.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["recovered", "lease_contended"])
async def test_startup_interrupts_unfinished_runs_only_with_the_owner_lease(
    tmp_path: Path, mode: str
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'recovery.sqlite3'}"
    database = create_database(database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
    owner = await seeder.user(email="owner@example.test", display_name="Owner")
    workspace = await seeder.workspace(slug="team", name="Team")
    await seeder.membership(user=owner, workspace=workspace, role=WorkspaceRole.OWNER)
    creation = await CollaborationService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        command_hmac_key=b"test-single-owner-hmac-key",
        command_hmac_key_version=1,
    ).create_project(
        actor=ActorContext(user_id=owner.id, credential_reference="test-seed"),
        workspace_id=workspace.id,
        name="Recovery",
    )
    run = Run(
        workspace_id=workspace.id,
        project_id=creation.project.id,
        graph_id="main",
        targets=(),
        started_by_user_id=owner.id,
        created_at=datetime.now(UTC),
    )
    app = create_app(_settings(tmp_path, database_url, single_owner=True))
    lock = ApiOwnerLease(tmp_path / "workbench" / ".grafy-api-owner.lock")
    if mode == "lease_contended":
        lock.acquire()
    try:
        async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
            await transaction.runs.add(run)
            await transaction.commit()
        if mode == "recovered":
            async with LifespanManager(app):
                get_resources(app)
            expected = RunStatus.INTERRUPTED
        else:
            with pytest.raises(RuntimeError, match="Another Grafy API owner"):
                async with LifespanManager(app):
                    pytest.fail("Unsafe recovery must not serve requests")
            expected = RunStatus.RUNNING
        async with SqlAlchemyUnitOfWork(database.sessions) as transaction:
            stored = await transaction.runs.get(
                run.workspace_id, run.project_id, run.id
            )
        assert stored is not None
        assert stored.status is expected
    finally:
        if mode == "lease_contended":
            lock.release()
        await database.dispose()
