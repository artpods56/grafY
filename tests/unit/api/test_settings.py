from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from grafy_api.plugins.runtime.network_policy import (
    NetworkAccessPlane,
    NetworkProfileMode,
)
from grafy_api.settings import Settings
from grafy_api.plugins.runtime.egress import PluginEgressProtocol


@pytest.fixture(autouse=True)
def isolate_network_policy_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy-policy tests independent from deployment configuration."""

    monkeypatch.delenv("GRAFY_NETWORK_POLICY_MANIFEST", raising=False)


def test_pytest_process_requires_explicit_external_plugin_runtime_opt_in() -> None:
    assert Settings().plugin_runtime_enabled is False
    assert Settings(plugin_runtime_enabled=True).plugin_runtime_enabled is True


def test_default_workspace_does_not_reuse_legacy_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    legacy_workspace = tmp_path / ".notarius-artifacts" / "workbench"
    legacy_workspace.mkdir(parents=True)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.workspace == Path(".grafy-artifacts/workbench")


def test_plugin_roots_resolve_from_the_deployment_allowlist(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_roots=(tmp_path / "team-plugins", tmp_path / "examples"),
    )

    assert settings.resolved_plugin_roots == (
        (tmp_path / "team-plugins").resolve(),
        (tmp_path / "examples").resolve(),
    )


def test_agent_authoring_paths_are_deployment_owned(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_authoring_root=tmp_path / "team-plugins",
        plugin_sdk_project=tmp_path / "sdk",
    )

    assert (
        settings.resolved_plugin_authoring_root == (tmp_path / "team-plugins").resolve()
    )
    assert settings.resolved_plugin_sdk_project == (tmp_path / "sdk").resolve()


def test_plugin_publisher_scratch_root_resolves_from_configuration(
    tmp_path: Path,
) -> None:
    scratch_root = tmp_path / "publisher-scratch"
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_publisher_scratch_root=scratch_root,
    )

    assert settings.resolved_plugin_publisher_scratch_root == scratch_root.resolve()


def test_default_authoring_root_does_not_overlap_system_plugin_packages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.plugin_authoring_root == Path(".grafy-artifacts/workspace-plugins")
    assert settings.plugin_authoring_root in settings.plugin_roots
    assert settings.plugin_authoring_root != Path("plugins")


def test_system_plugin_deployment_manifest_is_absent_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GRAFY_SYSTEM_PLUGIN_DEPLOYMENT_MANIFEST", raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.system_plugin_deployment_manifest is None
    assert settings.resolved_system_plugin_deployment_manifest is None


def test_system_plugin_deployment_manifest_resolves_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "deployment" / "system-plugins.json"
    monkeypatch.setenv("GRAFY_SYSTEM_PLUGIN_DEPLOYMENT_MANIFEST", str(manifest))

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.system_plugin_deployment_manifest == manifest
    assert settings.resolved_system_plugin_deployment_manifest == manifest.resolve()


def test_database_url_does_not_reuse_legacy_database(tmp_path: Path) -> None:
    legacy_database = tmp_path / "notarius.sqlite3"
    legacy_database.touch()

    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        workspace=tmp_path,
    )

    expected_database = (tmp_path / "grafy.sqlite3").resolve()
    assert settings.resolved_database_url == f"sqlite+aiosqlite:///{expected_database}"


def test_execution_defaults_with_bounded_map_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GRAFY_MAP_MAX_CONCURRENCY", raising=False)
    monkeypatch.delenv("GRAFY_MAX_ACTIVE_EXECUTIONS", raising=False)
    # Defaults must be tested independently from a developer's local .env.
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.map_max_concurrency == 4
    assert settings.max_active_executions == 2
    assert settings.max_pending_graphs == 20
    assert settings.max_active_plugin_invocations == 4
    assert settings.plugin_invocation_wall_time_seconds_by_slug == {}
    assert settings.max_live_plugin_sandboxes == 4
    assert settings.max_distinct_plugin_releases_per_graph == 4


def test_map_max_concurrency_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAFY_MAP_MAX_CONCURRENCY", "7")

    assert Settings().map_max_concurrency == 7


def test_map_max_concurrency_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(map_max_concurrency=0)


def test_max_active_executions_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAFY_MAX_ACTIVE_EXECUTIONS", "6")

    assert Settings().max_active_executions == 6


@pytest.mark.parametrize("value", [0, 33])
def test_max_active_executions_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(max_active_executions=value)


def test_max_pending_graphs_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAFY_MAX_PENDING_GRAPHS", "80")

    assert Settings().max_pending_graphs == 80


@pytest.mark.parametrize("value", [0, 1_001])
def test_max_pending_graphs_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(max_pending_graphs=value)


def test_plugin_capacity_dimensions_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAFY_MAX_ACTIVE_PLUGIN_INVOCATIONS", "6")
    monkeypatch.setenv("GRAFY_MAX_LIVE_PLUGIN_SANDBOXES", "8")
    monkeypatch.setenv("GRAFY_MAX_DISTINCT_PLUGIN_RELEASES_PER_GRAPH", "7")

    settings = Settings()
    assert settings.max_active_plugin_invocations == 6
    assert settings.max_live_plugin_sandboxes == 8
    assert settings.max_distinct_plugin_releases_per_graph == 7


def test_plugin_invocation_wall_times_can_be_selected_by_exact_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GRAFY_PLUGIN_INVOCATION_WALL_TIME_SECONDS_BY_SLUG",
        '{"external.notarius":900}',
    )

    assert Settings().plugin_invocation_wall_time_seconds_by_slug == {
        "external.notarius": 900,
    }


@pytest.mark.parametrize(
    ("slug", "seconds"),
    [("Invalid slug", 60), ("external.notarius", 0), ("external.notarius", 3_601)],
)
def test_plugin_invocation_wall_time_overrides_are_bounded(
    slug: str,
    seconds: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(plugin_invocation_wall_time_seconds_by_slug={slug: seconds})


def test_distinct_plugin_release_limit_cannot_exceed_live_sandboxes() -> None:
    with pytest.raises(ValidationError):
        Settings(
            max_live_plugin_sandboxes=4,
            max_distinct_plugin_releases_per_graph=5,
        )


def test_plugin_egress_requires_a_pinned_broker_and_exact_destinations() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_egress_broker_image=("registry.example/grafy-egress@sha256:" + "a" * 64),
        plugin_http_egress_destinations=("https://api.example.com:443",),
        plugin_postgresql_egress_destinations=(
            "postgresql://database.example.com:5432",
        ),
    )

    policy = settings.resolved_plugin_egress_policy

    assert policy.available is True
    assert policy.destinations_for(PluginEgressProtocol.HTTPS)[0].host == (
        "api.example.com"
    )
    assert policy.destinations_for(PluginEgressProtocol.POSTGRESQL)[0].port == 5432


@pytest.mark.parametrize(
    "values",
    [
        {"plugin_http_egress_destinations": ("https://api.example.com:443",)},
        {
            "plugin_egress_broker_image": (
                "registry.example/grafy-egress@sha256:" + "a" * 64
            )
        },
        {
            "plugin_egress_broker_image": "registry.example/grafy-egress:latest",
            "plugin_http_egress_destinations": ("https://api.example.com:443",),
        },
        {
            "plugin_egress_broker_image": (
                "registry.example/grafy-egress@sha256:" + "a" * 64
            ),
            "plugin_http_egress_destinations": (
                "postgresql://database.example.com:5432",
            ),
        },
    ],
)
def test_plugin_egress_partial_or_mistyped_configuration_fails_closed(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def test_oidc_signing_algorithms_are_strictly_allowlisted() -> None:
    with pytest.raises(ValidationError):
        Settings(oidc_allowed_signing_algorithms=("none",))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("oidc_client_id", ""),
        ("oidc_auth_wrapping_key", SecretStr("")),
        ("oidc_client_secret", SecretStr("")),
    ],
)
def test_oidc_configuration_rejects_empty_security_values(
    field: str,
    value: str | SecretStr,
) -> None:
    configured: dict[str, object] = {
        "oidc_issuer": "https://issuer.example.test",
        "oidc_client_id": "grafy-web",
        "oidc_auth_wrapping_key": SecretStr("wrapping-key"),
    }
    configured[field] = value

    with pytest.raises(ValidationError):
        Settings.model_validate(configured)


def test_database_url_is_redacted_from_serialized_settings() -> None:
    database_url = "sqlite+aiosqlite:///sensitive-database-name.sqlite3"
    settings = Settings(database_url=SecretStr(database_url))

    assert settings.resolved_database_url == database_url
    assert database_url not in repr(settings)
    dumped_url = settings.model_dump()["database_url"]
    assert isinstance(dumped_url, SecretStr)
    assert dumped_url.get_secret_value() == database_url
    assert database_url not in str(settings.model_dump())


def test_s3_credentials_are_redacted_from_serialized_settings() -> None:
    access_key = "sensitive-access-key"
    secret_key = "sensitive-secret-key"
    settings = Settings(
        storage_backend="s3",
        s3_access_key_id=SecretStr(access_key),
        s3_secret_access_key=SecretStr(secret_key),
    )

    assert access_key not in repr(settings)
    assert secret_key not in repr(settings)
    assert access_key not in str(settings.model_dump())
    assert secret_key not in str(settings.model_dump())


def test_credential_encryption_key_is_redacted_from_serialized_settings() -> None:
    encryption_key = "sensitive-node-secret-encryption-key"
    settings = Settings(
        credential_encryption_key=SecretStr(encryption_key),
    )

    assert encryption_key not in repr(settings)
    assert encryption_key not in str(settings.model_dump())


def test_command_hmac_key_is_redacted_and_resolved() -> None:
    hmac_key = "sensitive-command-hmac-key"
    settings = Settings(
        command_hmac_key=SecretStr(hmac_key),
        command_hmac_key_version=2,
    )

    assert settings.resolved_command_hmac_key() == hmac_key.encode("utf-8")
    assert settings.command_hmac_key_version == 2
    assert hmac_key not in repr(settings)
    assert hmac_key not in str(settings.model_dump())


def test_command_hmac_key_fails_closed_when_missing() -> None:
    settings = Settings(command_hmac_key=None)
    with pytest.raises(ValueError, match="GRAFY_COMMAND_HMAC_KEY"):
        settings.resolved_command_hmac_key()


def test_command_hmac_key_fails_closed_when_empty() -> None:
    settings = Settings(command_hmac_key=SecretStr(""))
    with pytest.raises(ValueError, match="must not be empty"):
        settings.resolved_command_hmac_key()


def _write_manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "network-policy.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_sandbox_variant_limit_cannot_exceed_live_sandbox_limit() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        Settings(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            max_live_plugin_sandboxes=2,
            max_plugin_sandbox_variants_per_execution=3,
        )


def test_network_policy_manifest_resolves_named_profiles(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path,
        """
schema_version = 1

[profiles."plugin-execution".llm-public]
mode = "configured-public"
allowed_origins = ["https://api.example.com:443"]
""",
    )
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        network_policy_manifest=manifest,
    )

    policy = settings.resolved_network_policy
    profile = policy.profile(NetworkAccessPlane.PLUGIN_EXECUTION, "llm-public")
    assert profile is not None
    assert len(profile.allowed_origins) == 1


def test_legacy_egress_env_translates_with_deprecation_warning() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_egress_broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
        plugin_http_egress_destinations=("https://api.example.com:443",),
    )

    with pytest.warns(DeprecationWarning, match="deprecated"):
        policy = settings.resolved_network_policy

    default = policy.default_profile(NetworkAccessPlane.PLUGIN_EXECUTION)
    assert default is not None
    assert default.mode is NetworkProfileMode.CURATED
    assert any(
        origin.protocol is PluginEgressProtocol.HTTPS
        for origin in default.allowed_origins
    )


def test_manifest_takes_precedence_and_excludes_legacy_http(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        network_policy_manifest=_write_manifest(
            tmp_path,
            """
schema_version = 1

[profiles."plugin-execution".deps]
mode = "curated"
allowed_origins = ["https://pypi.org:443"]
""",
        ),
        plugin_egress_broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
        plugin_http_egress_destinations=("https://legacy.example.com:443",),
        plugin_postgresql_egress_destinations=(
            "postgresql://database.example.com:5432",
        ),
    )

    policy = settings.resolved_network_policy
    assert policy.profile(NetworkAccessPlane.PLUGIN_EXECUTION, "deps") is not None

    egress = settings.resolved_plugin_egress_policy
    assert egress.available is True
    assert {origin.host for origin in egress.destinations} == {"database.example.com"}
