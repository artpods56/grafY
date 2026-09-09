"""Phase 7 one-API-owner startup fence."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from asgi_lifespan import LifespanManager
from grafy_api.app_state import get_resources
from grafy_api.execution.manager import RunExecutionManager
from grafy_api.main import create_app
from grafy_api.plugins.runtime.docker import DockerPluginRuntime
from grafy_api.realtime.hub import GraphRoomHub
from grafy_api.settings import Settings
from grafy_api.single_owner import ApiOwnerLease, assert_single_http_worker
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata
from pydantic import SecretStr

pytestmark = pytest.mark.single_api_owner


def test_require_single_api_owner_defaults_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GRAFY_REQUIRE_SINGLE_API_OWNER", raising=False)
    assert Settings().require_single_api_owner is True


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


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_runtime_enabled", [False, True])
async def test_create_app_startup_acquires_owner_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin_runtime_enabled: bool,
) -> None:
    workspace = tmp_path / "workbench"
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'owner.sqlite3'}"
    database = create_database(database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    await database.dispose()

    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        workspace=workspace,
        database_url=SecretStr(database_url),
        command_hmac_key=SecretStr("test-single-owner-hmac-key"),
        require_single_api_owner=True,
        plugin_runtime_enabled=plugin_runtime_enabled,
    )
    shutdown_order: list[str] = []
    original_hub_shutdown = GraphRoomHub.shutdown
    original_execution_shutdown = RunExecutionManager.shutdown
    original_artifact_close = ArtifactService.close

    async def close_rooms(hub: GraphRoomHub) -> None:
        shutdown_order.append("rooms")
        await original_hub_shutdown(hub)

    async def stop_executions(manager: RunExecutionManager) -> None:
        shutdown_order.append("executions")
        await original_execution_shutdown(manager)

    async def close_artifacts(artifacts: ArtifactService) -> None:
        shutdown_order.append("artifacts")
        await original_artifact_close(artifacts)

    async def stop_plugin_runtime(runtime: DockerPluginRuntime) -> None:
        shutdown_order.append("plugins")

    monkeypatch.setattr(GraphRoomHub, "shutdown", close_rooms)
    monkeypatch.setattr(RunExecutionManager, "shutdown", stop_executions)
    monkeypatch.setattr(ArtifactService, "close", close_artifacts)
    monkeypatch.setattr(DockerPluginRuntime, "shutdown", stop_plugin_runtime)
    monkeypatch.setattr(DockerPluginRuntime, "check_ready", AsyncMock())
    monkeypatch.setattr(DockerPluginRuntime, "recover_orphans", AsyncMock())
    app = create_app(settings)
    async with LifespanManager(app):
        lock_path = workspace / ".grafy-api-owner.lock"
        assert lock_path.is_file()
        contested = ApiOwnerLease(lock_path)
        with pytest.raises(RuntimeError, match="Another Grafy API owner"):
            contested.acquire()

        resources = get_resources(app)
        workbench = resources.workbench
        assert workbench.release_admission is not None
        if workbench.plugin_runtime is not None:
            assert (
                workbench.release_admission
                == workbench.plugin_runtime.release_admission
            )
        else:
            assert workbench.release_admission.isolated_adapter_available is False
        capacity = await resources.capacity_diagnostics()
        assert capacity.execution_admission.active_executions == 0
        assert (capacity.plugin_sandboxes is not None) is plugin_runtime_enabled
        assert (capacity.plugin_invocations is not None) is plugin_runtime_enabled
    expected = ["rooms", "executions", "plugins", "artifacts"]
    if not plugin_runtime_enabled:
        expected.remove("plugins")
    assert shutdown_order == expected
    with pytest.raises(RuntimeError, match="not initialized"):
        get_resources(app)
    contested.acquire()
    contested.release()
