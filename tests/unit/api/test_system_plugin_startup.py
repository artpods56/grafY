from tests.testkit import with_setting_values
from pathlib import Path
from unittest.mock import AsyncMock
from grafy_shared.config import AppConfig, KeysConfig, RealtimeConfig

from grafy_api.plugins.runtime.docker import DockerPluginRuntime
from grafy_api.app_state import get_resources

from asgi_lifespan import LifespanManager
from pydantic import SecretStr
import pytest

from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata
from grafy_workbench import BUILTIN_FAMILIES

from grafy_api.main import create_app
from grafy_api.settings import Settings


@pytest.fixture
async def startup_settings(tmp_path: Path) -> Settings:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'startup.sqlite3'}"
    database = create_database(database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    await database.dispose()
    return Settings(
        app=AppConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
            require_single_api_owner=False,
        ),
        keys=KeysConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            command_hmac_key=SecretStr("test-builtin-startup-hmac-key"),  # pyright: ignore[reportCallIssue]
        ),
        realtime=RealtimeConfig(_env_file=None, graph_room_heartbeat_seconds=0),  # pyright: ignore[reportCallIssue]
    )


@pytest.mark.asyncio
async def test_startup_registers_builtin_families_without_host_deployment(
    startup_settings: Settings,
) -> None:
    application = create_app(startup_settings)

    async with LifespanManager(application):
        registry = application.state.resources.workbench.plugin_registry
        expected_slugs = {family.slug for family in BUILTIN_FAMILIES}

        assert {plugin.slug for plugin in registry.plugins} == expected_slugs
        assert {("module.input", 1), ("module.output", 1)}.issubset(
            {node.key for node in registry.nodes}
        )
        admission = application.state.resources.workbench.release_admission
        assert admission is not None
        assert admission.isolated_adapter_available is False
        assert admission.runtime_profile is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_hmac_key",
    [None, SecretStr("")],
    ids=["missing", "empty"],
)
async def test_startup_reports_actionable_command_hmac_key_error(
    startup_settings: Settings,
    command_hmac_key: SecretStr | None,
) -> None:
    keys = KeysConfig(_env_file=None, command_hmac_key=command_hmac_key)
    application = create_app(startup_settings.model_copy(update={"keys": keys}))

    with pytest.raises(ValueError) as error:
        async with LifespanManager(application):
            pass

    message = str(error.value)
    assert "API startup failed" in message
    assert "GRAFY_COMMAND_HMAC_KEY" in message
    assert ".env" in message
    assert "export GRAFY_COMMAND_HMAC_KEY" in message
    assert "openssl rand -hex 32" in message


@pytest.mark.asyncio
async def test_runtime_startup_without_owner_does_not_reap_other_workers(
    startup_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    orphan_recovery = AsyncMock(
        side_effect=AssertionError("No authority to reap workers")
    )
    monkeypatch.setattr(DockerPluginRuntime, "check_ready", AsyncMock())
    monkeypatch.setattr(DockerPluginRuntime, "recover_orphans", orphan_recovery)
    monkeypatch.setattr(DockerPluginRuntime, "shutdown", AsyncMock())
    application = create_app(
        with_setting_values(startup_settings, plugin_runtime_enabled=True)
    )
    async with LifespanManager(application):
        assert get_resources(application).workbench.plugin_runtime is not None
    orphan_recovery.assert_not_awaited()
