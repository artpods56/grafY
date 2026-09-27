"""Shared pytest fixtures for the Grafy test suite."""

import pytest
from pydantic import SecretStr

from grafy_shared.config import AppConfig, AuthConfig

from grafy_api.settings import Settings
from tests.support.identity import TEST_COMMAND_HMAC_KEY


@pytest.fixture(autouse=True)
def _disable_single_api_owner_by_default(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Unit tests create many short-lived apps; the owner lease is opt-in."""

    if request.node.get_closest_marker("single_api_owner") is not None:
        return
    monkeypatch.setenv("GRAFY_REQUIRE_SINGLE_API_OWNER", "false")


@pytest.fixture(autouse=True)
def _configure_command_hmac_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAFY_COMMAND_HMAC_KEY", TEST_COMMAND_HMAC_KEY)
    monkeypatch.setenv("GRAFY_COMMAND_HMAC_KEY_VERSION", "1")


@pytest.fixture(autouse=True)
def _disable_external_plugin_runtime_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests opt into the host Docker runtime instead of inheriting local .env."""

    monkeypatch.setenv("GRAFY_PLUGIN_RUNTIME_ENABLED", "false")


DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///"
DEFAULT_PUBLIC_ORIGIN = "http://testserver"
DEFAULT_IDLE_SECONDS = 1800
DEFAULT_COOKIE_SECURE = False


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        app=AppConfig(
            public_origin=DEFAULT_PUBLIC_ORIGIN,
            database_url=SecretStr(DEFAULT_DATABASE_URL),
        ),
        auth=AuthConfig(
            auth_cookie_secure=DEFAULT_COOKIE_SECURE,
            auth_session_idle_seconds=DEFAULT_IDLE_SECONDS,
        ),
    )
