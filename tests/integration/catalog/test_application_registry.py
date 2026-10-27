import asyncio
from pathlib import Path

import pytest
from pydantic import SecretStr

from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_shared.config import AppConfig, PluginsConfig
from tests.support.identity import (
    browser_actor_override,
    create_schema,
    workspace_api_path,
)
from tests.testkit import client_with_overrides


@pytest.mark.parametrize("environment", ["development", "production"])
def test_same_catalog_in_every_environment_without_releases(
    tmp_path: Path,
    environment: str,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'catalog.sqlite3'}"
    asyncio.run(create_schema(database_url))
    with client_with_overrides(
        settings=Settings(
            app=AppConfig(
                environment=environment,
                build_digest="a" * 64,
                workspace=tmp_path / "workbench",
                database_url=SecretStr(database_url),
            ),
            # Historical deployment flags cannot enable the retired Docker path
            # or add arbitrary Python/SQL families to this static registry.
            plugins=PluginsConfig(
                dev_plugins=("external.python", "external.sql"),
                plugin_runtime_enabled=True,
                plugin_docker_binary="/no/docker",
            ),
        ),
        overrides={
            browser_actor: browser_actor_override,
            workspace_actor: browser_actor_override,
        },
    ) as client:
        response = client.get(workspace_api_path("/nodes"))
        assert response.status_code == 200, response.text
        nodes = {node["operator_id"]: node for node in response.json()["nodes"]}
        assert nodes["gis.raster_scan.import"]["origin"] == "builtin"
        assert nodes["gis.raster_scan.import"]["runnable"] is True
        assert nodes["image.draw_regions"]["origin"] == "builtin"
        assert (
            nodes["llm.openai_compatible.chat_completion"]["secret_inputs"][0]["name"]
            == "api_key"
        )
        assert not any(operator.startswith(("python.", "sql.")) for operator in nodes)
        assert all(node["plugin_release"] is None for node in nodes.values())
