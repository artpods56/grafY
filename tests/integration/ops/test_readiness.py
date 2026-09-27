from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import grafy_api.main as main_module
from grafy_api.settings import Settings, get_settings
from grafy_persistence.database import Database
from tests.testkit import client_with_overrides, create_db_url, db
from tests.testkit import with_setting_values


class _SwitchableReadinessEngine:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self.available = True

    def connect(self) -> AsyncConnection:
        if not self.available:
            raise OSError("database unavailable")
        return self._engine.connect()

    async def dispose(self) -> None:
        await self._engine.dispose()


async def test_readiness_reports_database_failure_without_breaking_liveness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    database_url = create_db_url(tmp_path, "readiness.sqlite3")
    async with db(database_url) as database:
        readiness_engine = _SwitchableReadinessEngine(database.engine)
        readiness_database = Database(
            engine=cast(AsyncEngine, readiness_engine),
            sessions=database.sessions,
        )
        # create_app builds the database inside its own closure, so the only
        # way to install the switchable engine is the module-level factory.
        monkeypatch.setattr(
            main_module,
            "create_database",
            lambda _database_url: readiness_database,
        )
        app_settings = with_setting_values(
            settings, database_url=SecretStr(database_url)
        )

        with client_with_overrides(settings=app_settings) as client:
            healthy = client.get("/ready")
            assert healthy.status_code == 200
            assert healthy.json() == {"status": "ok"}

            readiness_engine.available = False
            response = client.get("/ready")

            assert response.status_code == 503
            assert response.json()["detail"] == "Service unavailable"
            assert response.json()["code"] == "http.unavailable"
            UUID(response.json()["error_id"])
            liveness = client.get("/health")
            assert liveness.status_code == 200
            assert liveness.json() == {"status": "ok"}


async def test_readiness_uses_the_settings_attached_to_its_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    database_url = create_db_url(tmp_path, "readiness-settings.sqlite3")
    async with db(database_url):
        app_settings = with_setting_values(
            settings, database_url=SecretStr(database_url)
        )
        monkeypatch.setenv("GRAFY_MAP_MAX_CONCURRENCY", "7")
        get_settings.cache_clear()

        try:
            assert get_settings().execution.map_max_concurrency == 7

            with client_with_overrides(settings=app_settings) as client:
                response = client.get("/ready")

                assert response.status_code == 200
                assert response.json() == {"status": "ok"}
        finally:
            get_settings.cache_clear()


async def test_readiness_translates_uninitialized_resources_to_unavailable(
    tmp_path: Path,
    settings: Settings,
) -> None:
    database_url = create_db_url(tmp_path, "readiness-uninitialized.sqlite3")
    async with db(database_url):
        app_settings = with_setting_values(
            settings, database_url=SecretStr(database_url)
        )

        with client_with_overrides(settings=app_settings) as client:
            # The failure mode under test is a missing lifespan artifact, so
            # application.state.resources must be removed directly.
            application = cast(FastAPI, client.app)
            resources = application.state.resources
            del application.state.resources
            try:
                response = client.get("/ready")
            finally:
                application.state.resources = resources

            assert response.status_code == 503
            assert response.json()["detail"] == "Service unavailable"
            assert response.json()["code"] == "http.unavailable"
            UUID(response.json()["error_id"])
