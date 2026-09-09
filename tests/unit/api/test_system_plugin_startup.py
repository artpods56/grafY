from pathlib import Path

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
        _env_file=None,  # pyright: ignore[reportCallIssue]
        workspace=tmp_path / "workbench",
        database_url=SecretStr(database_url),
        command_hmac_key=SecretStr("test-builtin-startup-hmac-key"),
        require_single_api_owner=False,
        graph_room_heartbeat_seconds=0,
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
async def test_configured_host_deployment_manifest_is_ignored(
    startup_settings: Settings,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "deployment" / "system-plugins.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text("{}", encoding="utf-8")
    configured = startup_settings.model_copy(
        update={"system_plugin_deployment_manifest": manifest_path}
    )
    application = create_app(configured)

    async with LifespanManager(application):
        resources = application.state.resources
        expected_slugs = {family.slug for family in BUILTIN_FAMILIES}
        assert {
            plugin.slug for plugin in resources.workbench.plugin_registry.plugins
        } == (expected_slugs)
        admission = resources.workbench.release_admission
        assert admission is not None
        assert admission.isolated_adapter_available is False
        assert admission.runtime_profile is None
