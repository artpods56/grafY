from pathlib import Path
from grafy_shared.config import AppConfig, KeysConfig, RealtimeConfig

from asgi_lifespan import LifespanManager
from pydantic import SecretStr
import pytest

from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata
from grafy_api.services.families import APPLICATION_FAMILIES

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
        expected_slugs = {family.slug for family in APPLICATION_FAMILIES}

        assert {plugin.slug for plugin in registry.plugins} == expected_slugs
        assert not any(node.key[0].startswith("module.") for node in registry.nodes)


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
