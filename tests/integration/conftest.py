"""Fixtures for API integration tests (full-app workbench clients)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient
from pydantic import SecretStr


from grafy_shared.config import AppConfig

from grafy_api.services.composition import (
    build_workbench_components,
)
from grafy_api.settings import Settings

from tests.support.identity import create_schema
from tests.support.system_plugins import (
    build_selected_system_plugin_deployment,
)
from tests.support.workbench import workbench_dependency_overrides
from tests.testkit import client_with_overrides


@pytest.fixture
def builtin_client(tmp_path: Path) -> Iterator[TestClient]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'api.sqlite3'}"
    asyncio.run(create_schema(database_url))
    deployment = build_selected_system_plugin_deployment()
    components = build_workbench_components(
        plugin_registry=deployment.registry,
        workspace=tmp_path / "workbench",
        unit_of_work=SqlAlchemyUnitOfWork(create_database(database_url).sessions),
    )
    with client_with_overrides(
        settings=Settings(
            app=AppConfig(
                workspace=tmp_path / "workbench",
                database_url=SecretStr(database_url),
            )
        ),
        overrides=workbench_dependency_overrides(components),
    ) as client:
        yield client
