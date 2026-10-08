"""Configuration sections, their environment binding, and the composed parent."""

import re
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from grafy_shared.config import (
    AppConfig,
    AuthConfig,
    EgressConfig,
    ExecutionConfig,
    KeysConfig,
    PluginsConfig,
    RealtimeConfig,
    StorageConfig,
    UploadConfig,
)

from grafy_api.plugins.runtime.egress import (
    PluginEgressBrokerPolicy,
    PluginEgressProtocol,
)
from grafy_api.plugins.runtime.network_policy import (
    NetworkAccessPlane,
    NetworkPolicy,
    NetworkProfileMode,
)
from grafy_api.realtime.hub import GraphRoomHub
from grafy_api.settings import Settings
from grafy_core.domain.identity import parse_oidc_domain_workspace_grants

REPO_ROOT = Path(__file__).resolve().parents[3]

CONFIG_SECTIONS: tuple[type, ...] = (
    AppConfig,
    AuthConfig,
    KeysConfig,
    ExecutionConfig,
    RealtimeConfig,
    StorageConfig,
    UploadConfig,
    PluginsConfig,
    EgressConfig,
)

# Advertised by .env.example but owned by nothing: a stale entry with no reader
# anywhere in the tree. Deleting it is an operator-facing documentation change and
# deliberately out of scope here, so the environment-binding test names it instead
# of pretending it resolves.
ADVERTISED_BUT_UNOWNED_VARIABLES = frozenset({"GRAFY_OIDC_BOOTSTRAP_SUBJECT"})


@pytest.fixture(autouse=True)
def isolate_network_policy_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy-policy tests independent from deployment configuration."""

    monkeypatch.delenv("GRAFY_NETWORK_POLICY_MANIFEST", raising=False)


def test_no_setting_field_is_owned_by_more_than_one_section() -> None:
    # A field in two sections would bind one GRAFY_ variable twice and let one section
    # silently shadow another's value.
    owned = [name for section in CONFIG_SECTIONS for name in section.model_fields]

    assert len(owned) == len(set(owned)), "a field is owned by two sections"


def test_every_advertised_environment_variable_resolves_to_one_section() -> None:
    advertised = {
        match.group(1)
        for line in (REPO_ROOT / ".env.example").read_text().splitlines()
        for match in [re.match(r"\s*#?\s*(GRAFY_[A-Z0-9_]+)\s*=", line)]
        if match
    }
    owner_counts = {
        name: sum(
            1
            for section in CONFIG_SECTIONS
            if name.removeprefix("GRAFY_").lower() in section.model_fields
        )
        for name in (advertised - ADVERTISED_BUT_UNOWNED_VARIABLES)
    }

    assert {name for name, count in owner_counts.items() if count != 1} == set()


def test_no_section_uses_a_nested_environment_delimiter() -> None:
    # GRAFY_STORAGE_BUCKET would become GRAFY_STORAGE__BUCKET: an operator-visible
    # break paid for an internal refactor.
    for section in CONFIG_SECTIONS:
        assert section.model_config.get("env_nested_delimiter") is None
        assert section.model_config.get("env_prefix") == "GRAFY_"
        assert section.model_config.get("extra") == "ignore"


def test_parent_rejects_a_field_name_owned_by_a_section() -> None:
    # Before the split, Settings(workspace=...) meant "use this workspace". As a plain
    # BaseModel with extra="ignore" it would still build, silently keeping the default
    # AppConfig, so the app ran against the wrong workspace and database while every
    # assertion about them passed. A flat name has to fail at the call that has it.
    with pytest.raises(ValidationError, match="workspace"):
        Settings(workspace=Path("/tmp/grafy-flat"))

    # The parent reads no environment, so forwarding the section-only knob here is a bug
    # too: a caller would believe it had suppressed a developer .env.
    with pytest.raises(ValidationError, match="_env_file"):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_parent_copy_routes_only_whole_sections() -> None:
    # model_copy(update=...) writes straight into __dict__ without validating, so flat
    # keys used to land as unreachable attributes on the parent.
    settings = Settings()

    with pytest.raises(TypeError, match="app"):
        _ = settings.model_copy(
            update={"database_url": SecretStr("sqlite+aiosqlite:///x")}
        )

    copied = settings.model_copy(
        update={"app": settings.app.model_copy(update={"log_level": "DEBUG"})}
    )

    assert copied.app.log_level == "DEBUG"
    assert settings.app.log_level != "DEBUG"


def test_parent_reads_one_env_file_for_every_section(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # The sharpest trap in the split: a plain-BaseModel parent does not forward
    # _env_file to its children. That forwarding is one line per section, so a test
    # that checked one section would pass green while a developer's .env still leaked
    # into the other eight. Every section is probed with a variable nothing else sets.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "GRAFY_LOG_LEVEL=DEBUG",
                "GRAFY_OIDC_AUTH_WRAPPING_KEY_VERSION=7",
                "GRAFY_CREDENTIAL_ENCRYPTION_KEY=env-file-credential-key",
                "GRAFY_MAP_MAX_CONCURRENCY=42",
                "GRAFY_GRAPH_ROOM_PRESENCE_MAX_UPDATES_PER_SECOND=33",
                "GRAFY_STORAGE_BUCKET=env-file-bucket",
                "GRAFY_UPLOAD_LIFETIME_SECONDS=3600",
                "GRAFY_PLUGIN_DOCKER_BINARY=/usr/bin/env-file-docker",
                "GRAFY_NETWORK_POLICY_MANIFEST=env-file-policy.json",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    honoured = Settings.from_environment()

    assert honoured.app.log_level == "DEBUG"
    assert honoured.auth.oidc_auth_wrapping_key_version == 7
    assert honoured.keys.credential_encryption_key is not None
    assert honoured.keys.credential_encryption_key.get_secret_value() == (
        "env-file-credential-key"
    )
    assert honoured.execution.map_max_concurrency == 42
    assert honoured.realtime.graph_room_presence_max_updates_per_second == 33
    assert honoured.storage.storage_bucket == "env-file-bucket"
    assert honoured.uploads.upload_lifetime_seconds == 3600
    assert honoured.plugins.plugin_docker_binary == "/usr/bin/env-file-docker"
    assert honoured.egress.network_policy_manifest == Path("env-file-policy.json")

    isolated = Settings.from_environment(env_file=None)

    assert isolated.app.log_level == "INFO"
    assert isolated.auth.oidc_auth_wrapping_key_version == 1
    assert isolated.keys.credential_encryption_key is None
    assert isolated.execution.map_max_concurrency == 4
    assert isolated.realtime.graph_room_presence_max_updates_per_second == 20
    assert isolated.storage.storage_bucket == "workbench-artifacts"
    assert isolated.uploads.upload_lifetime_seconds == 86400
    assert isolated.plugins.plugin_docker_binary == "docker"
    assert isolated.egress.network_policy_manifest is None


def test_pytest_process_requires_explicit_external_plugin_runtime_opt_in() -> None:
    assert PluginsConfig(_env_file=None).plugin_runtime_enabled is False  # pyright: ignore[reportCallIssue]
    assert PluginsConfig(plugin_runtime_enabled=True).plugin_runtime_enabled is True


def test_default_workspace_does_not_reuse_legacy_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)  # pyright: ignore[reportCallIssue]
    legacy_workspace = tmp_path / ".notarius-artifacts" / "workbench"
    legacy_workspace.mkdir(parents=True)

    config = AppConfig(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert config.workspace == Path(".grafy-artifacts/workbench")


# pyright: ignore[reportCallIssue]


def test_plugin_roots_resolve_from_the_deployment_allowlist(tmp_path: Path) -> None:
    config = PluginsConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_roots=(tmp_path / "team-plugins", tmp_path / "examples"),
    )

    assert config.resolved_plugin_roots == (
        (tmp_path / "team-plugins").resolve(),
        (tmp_path / "examples").resolve(),
    )


# pyright: ignore[reportCallIssue]


def test_agent_authoring_paths_are_deployment_owned(tmp_path: Path) -> None:
    config = PluginsConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_authoring_root=tmp_path / "team-plugins",
        plugin_sdk_project=tmp_path / "sdk",
    )

    assert (
        config.resolved_plugin_authoring_root == (tmp_path / "team-plugins").resolve()
    )
    assert config.resolved_plugin_sdk_project == (tmp_path / "sdk").resolve()


def test_plugin_publisher_scratch_root_resolves_from_configuration(
    tmp_path: Path,  # pyright: ignore[reportCallIssue]
) -> None:
    scratch_root = tmp_path / "publisher-scratch"

    config = PluginsConfig(_env_file=None, plugin_publisher_scratch_root=scratch_root)  # pyright: ignore[reportCallIssue]

    assert config.resolved_plugin_publisher_scratch_root == scratch_root.resolve()


def test_default_authoring_root_does_not_overlap_system_plugin_packages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.chdir(tmp_path)

    config = PluginsConfig(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert config.plugin_authoring_root == Path(".grafy-artifacts/workspace-plugins")
    assert config.plugin_authoring_root in config.plugin_roots
    assert config.plugin_authoring_root != Path("plugins")


def test_database_url_does_not_reuse_legacy_database(tmp_path: Path) -> None:  # pyright: ignore[reportCallIssue]
    legacy_database = tmp_path / "notarius.sqlite3"
    legacy_database.touch()

    config = AppConfig(_env_file=None, workspace=tmp_path)  # pyright: ignore[reportCallIssue]

    expected_database = (tmp_path / "grafy.sqlite3").resolve()
    assert config.resolved_database_url == f"sqlite+aiosqlite:///{expected_database}"


def test_map_max_concurrency_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.setenv("GRAFY_MAP_MAX_CONCURRENCY", "7")

    assert ExecutionConfig(_env_file=None).map_max_concurrency == 7  # pyright: ignore[reportCallIssue]


# pyright: ignore[reportCallIssue]


def test_map_max_concurrency_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ExecutionConfig(_env_file=None, map_max_concurrency=0)  # pyright: ignore[reportCallIssue]


def test_max_active_executions_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.setenv("GRAFY_MAX_ACTIVE_EXECUTIONS", "6")

    assert ExecutionConfig(_env_file=None).max_active_executions == 6  # pyright: ignore[reportCallIssue]


# pyright: ignore[reportCallIssue]
@pytest.mark.parametrize("value", [0, 33])
def test_max_active_executions_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        ExecutionConfig(_env_file=None, max_active_executions=value)  # pyright: ignore[reportCallIssue]


def test_max_pending_graphs_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.setenv("GRAFY_MAX_PENDING_GRAPHS", "80")

    assert ExecutionConfig(_env_file=None).max_pending_graphs == 80  # pyright: ignore[reportCallIssue]


# pyright: ignore[reportCallIssue]
@pytest.mark.parametrize("value", [0, 1_001])
def test_max_pending_graphs_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        ExecutionConfig(_env_file=None, max_pending_graphs=value)  # pyright: ignore[reportCallIssue]


def test_plugin_capacity_dimensions_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAFY_MAX_ACTIVE_PLUGIN_INVOCATIONS", "6")  # pyright: ignore[reportCallIssue]
    monkeypatch.setenv("GRAFY_MAX_LIVE_PLUGIN_SANDBOXES", "8")
    monkeypatch.setenv("GRAFY_MAX_DISTINCT_PLUGIN_RELEASES_PER_GRAPH", "7")

    config = PluginsConfig(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert config.max_active_plugin_invocations == 6
    assert config.max_live_plugin_sandboxes == 8
    assert config.max_distinct_plugin_releases_per_graph == 7


def test_plugin_invocation_wall_times_can_be_selected_by_exact_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GRAFY_PLUGIN_INVOCATION_WALL_TIME_SECONDS_BY_SLUG",
        '{"external.notarius":900}',  # pyright: ignore[reportCallIssue]
    )

    assert PluginsConfig(
        _env_file=None  # pyright: ignore[reportCallIssue]
    ).plugin_invocation_wall_time_seconds_by_slug == {
        "external.notarius": 900,
    }


@pytest.mark.parametrize(
    ("slug", "seconds"),
    [("Invalid slug", 60), ("external.notarius", 0), ("external.notarius", 3_601)],
)
def test_plugin_invocation_wall_time_overrides_are_bounded(
    slug: str,
    seconds: int,  # pyright: ignore[reportCallIssue]
) -> None:
    with pytest.raises(ValidationError):
        PluginsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            plugin_invocation_wall_time_seconds_by_slug={slug: seconds},
        )


# pyright: ignore[reportCallIssue]
def test_distinct_plugin_release_limit_cannot_exceed_live_sandboxes() -> None:
    with pytest.raises(ValidationError):
        PluginsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            max_live_plugin_sandboxes=4,
            max_distinct_plugin_releases_per_graph=5,
        )


# pyright: ignore[reportCallIssue]
def test_sandbox_variant_limit_cannot_exceed_live_sandbox_limit() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        PluginsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            max_live_plugin_sandboxes=2,
            max_plugin_sandbox_variants_per_execution=3,
        )


# pyright: ignore[reportCallIssue]


def test_plugin_egress_requires_a_pinned_broker_and_exact_destinations() -> None:
    egress = EgressConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_egress_broker_image=("registry.example/grafy-egress@sha256:" + "a" * 64),
        plugin_http_egress_destinations=("https://api.example.com:443",),
        plugin_postgresql_egress_destinations=(
            "postgresql://database.example.com:5432",
        ),
    )

    policy = PluginEgressBrokerPolicy.from_config(egress)

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
    ],
)
def test_plugin_egress_partial_configuration_fails_closed(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        EgressConfig(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    "values",
    [
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
def test_plugin_egress_mistyped_configuration_fails_closed(
    values: dict[str, object],
) -> None:  # pyright: ignore[reportCallIssue]
    # The destination grammar and the pinned-image rule belong to the Plugin runtime,
    # so they fail when the composition root builds the policy, not when EgressConfig
    # parses its strings.
    egress = EgressConfig(_env_file=None, **values)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError):
        PluginEgressBrokerPolicy.from_config(egress)


def test_oidc_domain_workspaces_stay_raw_for_the_api_to_parse() -> None:  # pyright: ignore[reportCallIssue]
    # grafy-shared is a leaf, so it cannot import grafy_core's grant type. The API
    # owns the parse; the section owns only the deployment strings.
    config = AuthConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        oidc_domain_workspaces="ihpan.edu.pl:ihpan:IHPAN",  # pyright: ignore[reportCallIssue]
    )

    grants = parse_oidc_domain_workspace_grants(config.oidc_domain_workspaces)

    assert len(grants) == 1
    assert grants[0].email_domain == "ihpan.edu.pl"
    assert grants[0].workspace_slug == "ihpan"
    assert grants[0].workspace_name == "IHPAN"


def test_oidc_domain_workspaces_parse_from_environment(
    monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.setenv("GRAFY_OIDC_DOMAIN_WORKSPACES", "ihpan.edu.pl:ihpan:IHPAN")

    config = AuthConfig(_env_file=None)  # pyright: ignore[reportCallIssue]
    grants = parse_oidc_domain_workspace_grants(config.oidc_domain_workspaces)

    assert grants[0].workspace_slug == "ihpan"


def test_oidc_domain_workspaces_treat_empty_environment_as_unset(
    monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.setenv("GRAFY_OIDC_DOMAIN_WORKSPACES", "")

    assert AuthConfig(_env_file=None).oidc_domain_workspaces == ()  # pyright: ignore[reportCallIssue]


def test_oidc_domain_workspaces_reject_malformed_grants() -> None:
    config = AuthConfig(_env_file=None, oidc_domain_workspaces="ihpan.edu.pl")  # pyright: ignore[reportCallIssue]

    with pytest.raises(ValueError, match="domain:slug"):
        parse_oidc_domain_workspace_grants(config.oidc_domain_workspaces)


# pyright: ignore[reportCallIssue]


def test_oidc_signing_algorithms_are_strictly_allowlisted() -> None:
    with pytest.raises(ValidationError):
        AuthConfig(_env_file=None, oidc_allowed_signing_algorithms=("none",))  # pyright: ignore[reportCallIssue]


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
        AuthConfig.model_validate(configured)  # pyright: ignore[reportCallIssue]


def test_oidc_callback_url_joins_the_deployment_origin() -> None:
    config = AuthConfig(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert (
        config.resolved_callback_url("https://grafy.example.test")
        == "https://grafy.example.test/api/v1/auth/oidc/callback"
    )


def test_database_url_is_redacted_from_serialized_settings() -> None:
    database_url = "sqlite+aiosqlite:///sensitive-database-name.sqlite3"
    settings = Settings(app=AppConfig(database_url=SecretStr(database_url)))

    assert settings.app.resolved_database_url == database_url
    assert database_url not in repr(settings)
    assert database_url not in str(settings.model_dump())
    assert database_url not in settings.model_dump_json()


def test_s3_credentials_are_redacted_from_serialized_settings() -> None:
    access_key = "sensitive-access-key"
    secret_key = "sensitive-secret-key"
    settings = Settings(
        storage=StorageConfig(
            storage_backend="s3",
            s3_access_key_id=SecretStr(access_key),
            s3_secret_access_key=SecretStr(secret_key),
        )
    )

    assert access_key not in repr(settings)
    assert secret_key not in repr(settings)
    assert access_key not in str(settings.model_dump())
    assert secret_key not in settings.model_dump_json()
    assert secret_key not in settings.model_dump_json()


def test_credential_encryption_key_is_redacted_from_serialized_settings() -> None:
    encryption_key = "sensitive-node-secret-encryption-key"
    settings = Settings(
        keys=KeysConfig(credential_encryption_key=SecretStr(encryption_key))
    )

    assert encryption_key not in repr(settings)
    assert encryption_key not in str(settings.model_dump())
    assert encryption_key not in settings.model_dump_json()


# pyright: ignore[reportCallIssue]
def test_command_hmac_key_is_redacted_and_resolved() -> None:
    hmac_key = "sensitive-command-hmac-key"
    keys = KeysConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        command_hmac_key=SecretStr(hmac_key),
        command_hmac_key_version=2,  # pyright: ignore[reportCallIssue]
    )

    assert keys.resolved_command_hmac_key() == hmac_key.encode("utf-8")
    assert keys.command_hmac_key_version == 2
    assert hmac_key not in repr(keys)
    assert hmac_key not in keys.model_dump_json()  # pyright: ignore[reportCallIssue]


def test_command_hmac_key_fails_closed_when_missing() -> None:
    keys = KeysConfig(_env_file=None, command_hmac_key=None)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match="GRAFY_COMMAND_HMAC_KEY"):
        keys.resolved_command_hmac_key()  # pyright: ignore[reportCallIssue]


def test_command_hmac_key_fails_closed_when_empty() -> None:
    keys = KeysConfig(_env_file=None, command_hmac_key=SecretStr(""))  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match="is missing or empty"):
        keys.resolved_command_hmac_key()


def _write_manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "network-policy.toml"
    path.write_text(text, encoding="utf-8")
    return path


# pyright: ignore[reportCallIssue]


def test_network_policy_manifest_resolves_named_profiles(tmp_path: Path) -> None:
    egress = EgressConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        network_policy_manifest=_write_manifest(
            tmp_path,
            """
schema_version = 1

[profiles."plugin-execution".llm-public]
mode = "configured-public"
allowed_origins = ["https://api.example.com:443"]
""",
        ),
    )

    policy = NetworkPolicy.from_config(egress)

    profile = policy.profile(NetworkAccessPlane.PLUGIN_EXECUTION, "llm-public")
    assert profile is not None
    assert len(profile.allowed_origins) == 1


# pyright: ignore[reportCallIssue]


def test_legacy_egress_env_translates_with_deprecation_warning() -> None:
    egress = EgressConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        plugin_egress_broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
        plugin_http_egress_destinations=("https://api.example.com:443",),
    )

    with pytest.warns(DeprecationWarning, match="deprecated"):
        policy = NetworkPolicy.from_config(egress)

    default = policy.default_profile(NetworkAccessPlane.PLUGIN_EXECUTION)
    assert default is not None
    assert default.mode is NetworkProfileMode.CURATED
    assert any(
        origin.protocol is PluginEgressProtocol.HTTPS
        for origin in default.allowed_origins
    )


# pyright: ignore[reportCallIssue]


def test_manifest_takes_precedence_and_excludes_legacy_http(tmp_path: Path) -> None:
    egress = EgressConfig(
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

    policy = NetworkPolicy.from_config(egress)
    assert policy.profile(NetworkAccessPlane.PLUGIN_EXECUTION, "deps") is not None

    broker = PluginEgressBrokerPolicy.from_config(egress)
    assert broker.available is True
    assert {origin.host for origin in broker.destinations} == {"database.example.com"}


def test_realtime_presence_bounds_are_independent_of_execution(
    monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.setenv("GRAFY_GRAPH_ROOM_HEARTBEAT_SECONDS", "3")

    realtime = RealtimeConfig(_env_file=None)  # pyright: ignore[reportCallIssue]
    hub = GraphRoomHub.from_settings(realtime)

    assert realtime.graph_room_heartbeat_seconds == 3.0
    assert hub.heartbeat_seconds == 3.0
