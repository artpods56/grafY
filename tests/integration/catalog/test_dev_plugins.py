import asyncio
from pathlib import Path

import pytest
from pydantic import SecretStr

from grafy_api.dev_plugins import DevPluginError
from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_shared.config import AppConfig, PluginsConfig
from tests.support.identity import (
    browser_actor_override,
    create_schema,
    workspace_api_path,
)
from tests.testkit import client_with_overrides


def test_dev_plugin_nodes_in_catalog(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'catalog.sqlite3'}"
    asyncio.run(create_schema(database_url))
    with client_with_overrides(
        settings=Settings(
            app=AppConfig(
                workspace=tmp_path / "workbench", database_url=SecretStr(database_url)
            ),
            plugins=PluginsConfig(
                dev_plugins=("external.image",), plugin_runtime_enabled=False
            ),
        ),
        overrides={
            browser_actor: browser_actor_override,
            workspace_actor: browser_actor_override,
        },
    ) as client:
        response = client.get(workspace_api_path("/nodes"))
        assert response.status_code == 200
        assert any(
            node["operator_id"] == "image.draw_regions"
            and node["operator_version"] == 1
            for node in response.json()["nodes"]
        )


def test_production_rejects_dev_plugins(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'production.sqlite3'}"
    asyncio.run(create_schema(database_url))
    with pytest.raises(DevPluginError, match="development-only.*production"):
        with client_with_overrides(
            settings=Settings(
                app=AppConfig(
                    environment="production",
                    build_digest="a" * 64,
                    workspace=tmp_path / "workbench",
                    database_url=SecretStr(database_url),
                ),
                plugins=PluginsConfig(
                    dev_plugins=("external.image",), plugin_runtime_enabled=False
                ),
            ),
        ):
            pass
