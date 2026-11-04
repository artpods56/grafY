"""Configuration sections, their environment binding, and the composed parent."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from grafy_shared.config import (
    AgentsConfig,
    AppConfig,
    AuthConfig,
    EgressConfig,
    ExecutionConfig,
    KeysConfig,
    RealtimeConfig,
    StorageConfig,
    UploadConfig,
)
from grafy_shared.config.app import (
    _working_tree_build_digest,  # pyright: ignore[reportPrivateUsage]
)

from grafy_api.services.application import workbench_egress_policy
from grafy_api.realtime.hub import ProjectRoomHub
from grafy_api.settings import Settings
from grafy_core.domain.identity import parse_oidc_domain_workspace_grants
from grafy_core.egress import TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE

REPO_ROOT = Path(__file__).resolve().parents[3]

CONFIG_SECTIONS: tuple[type, ...] = (
    AgentsConfig,
    AppConfig,
    AuthConfig,
    KeysConfig,
    ExecutionConfig,
    RealtimeConfig,
    StorageConfig,
    UploadConfig,
    EgressConfig,
)

# Advertised by .env.example but owned by nothing: a stale entry with no reader
# anywhere in the tree. Deleting it is an operator-facing documentation change and
# deliberately out of scope here, so the environment-binding test names it instead
# of pretending it resolves.
ADVERTISED_BUT_UNOWNED_VARIABLES = frozenset({"GRAFY_OIDC_BOOTSTRAP_SUBJECT"})


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
    # into the others. Every section is probed with a variable nothing else sets.
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
                'GRAFY_EGRESS_TRUSTED_DESTINATIONS=["models.internal:11434"]',
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
    assert honoured.egress.egress_trusted_destinations == ("models.internal:11434",)

    isolated = Settings.from_environment(env_file=None)

    assert isolated.app.log_level == "INFO"
    assert isolated.auth.oidc_auth_wrapping_key_version == 1
    assert isolated.keys.credential_encryption_key is None
    assert isolated.execution.map_max_concurrency == 4
    assert isolated.realtime.graph_room_presence_max_updates_per_second == 20
    assert isolated.storage.storage_bucket == "workbench-artifacts"
    assert isolated.uploads.upload_lifetime_seconds == 86400
    assert isolated.egress.egress_trusted_destinations == ()


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


def test_project_computation_concurrency_can_be_selected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.setenv("GRAFY_PROJECT_COMPUTATION_CONCURRENCY", "6")

    assert ExecutionConfig(_env_file=None).project_computation_concurrency == 6  # pyright: ignore[reportCallIssue]


# pyright: ignore[reportCallIssue]
@pytest.mark.parametrize("value", [0, 33])
def test_project_computation_concurrency_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        ExecutionConfig(_env_file=None, project_computation_concurrency=value)  # pyright: ignore[reportCallIssue]


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
def test_agent_default_model_is_a_whole_choice_or_none() -> None:
    """Half a deployment default is not a default, and the missing part is named.

    A model name with no endpoint would dial api.openai.com by SDK accident, so the
    resolver refuses to guess and says which variable the operator still owes.
    """

    complete = AgentsConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        agent_default_base_url="https://models.internal/v1",
        agent_default_model="gpt-5-mini",
        agent_default_api_key=SecretStr("deployment-key"),
    )
    assert complete.is_configured
    assert complete.incomplete_default() is None

    # A private endpoint is a configuration the egress authority decides about, not here.
    assert complete.agent_default_base_url is not None
    assert complete.agent_default_base_url.host == "models.internal"

    no_model = AgentsConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        agent_default_base_url="https://models.internal/v1",
        agent_default_api_key=SecretStr("deployment-key"),
    )
    assert no_model.incomplete_default() == "GRAFY_AGENT_DEFAULT_MODEL"
    no_endpoint = AgentsConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        agent_default_model="gpt-5-mini",
        agent_default_api_key=SecretStr("deployment-key"),
    )
    assert no_endpoint.incomplete_default() == "GRAFY_AGENT_DEFAULT_BASE_URL"
    empty_key = AgentsConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        agent_default_base_url="https://models.internal/v1",
        agent_default_model="gpt-5-mini",
        agent_default_api_key=SecretStr("   "),
    )
    assert empty_key.incomplete_default() == "GRAFY_AGENT_DEFAULT_API_KEY"


@pytest.mark.parametrize(
    ("endpoint", "refusal"),
    [
        ("https://user:hunter2@models.example/v1", "embedded credentials"),
        ("https://models.example/v1?key=leak", "query-free service endpoint"),
        ("ftp://models.example/v1", "URL scheme"),
    ],
)
def test_a_malformed_agent_default_endpoint_is_refused_at_startup(
    endpoint: str, refusal: str
) -> None:
    """A wrong default fails the process that was configured wrong, and says so."""

    with pytest.raises(ValidationError, match=refusal):
        AgentsConfig(  # pyright: ignore[reportCallIssue]
            _env_file=None,  # pyright: ignore[reportCallIssue]
            agent_default_base_url=endpoint,
        )


def test_the_agent_default_key_is_redacted_from_serialized_settings() -> None:
    deployment_key = "sensitive-deployment-agent-key"
    settings = Settings(
        agents=AgentsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            agent_default_base_url="https://models.example/v1",
            agent_default_model="gpt-5-mini",
            agent_default_api_key=SecretStr(deployment_key),
        )
    )

    assert deployment_key not in repr(settings)
    assert deployment_key not in str(settings.model_dump())
    assert deployment_key not in settings.model_dump_json()


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


def test_realtime_presence_bounds_are_independent_of_execution(
    monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportCallIssue]
) -> None:
    monkeypatch.setenv("GRAFY_GRAPH_ROOM_HEARTBEAT_SECONDS", "3")

    realtime = RealtimeConfig(_env_file=None)  # pyright: ignore[reportCallIssue]
    hub = ProjectRoomHub.from_settings(realtime)

    assert realtime.graph_room_heartbeat_seconds == 3.0
    assert hub.heartbeat_seconds == 3.0


def test_trusted_egress_destinations_are_the_grants_the_workbench_dials_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One variable: the section reads it, the workbench policy acts on it."""

    monkeypatch.setenv(
        TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE,
        '["models.internal:11434", "10.0.0.0/8"]',
    )

    policy = workbench_egress_policy(EgressConfig(_env_file=None))  # pyright: ignore[reportCallIssue]

    assert policy.trusts_host("models.internal", 11434) is True
    assert policy.trusts_host("models.internal", 443) is False
    assert policy.trusts_address("10.20.30.40") is True
    assert policy.trusts_address("93.184.216.34") is False


@pytest.mark.parametrize(
    "entry",
    ["models.internal:http", "models.internal:99999", "[models.internal:11434"],
)
def test_a_malformed_trusted_egress_destination_names_the_variable_it_came_from(
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    """The grant list is read while the app starts, and says where it came from.

    The destination grammar belongs to `grafy_core.egress`; the operator still
    needs to know which variable to fix, and a failure at startup is the only
    moment a malformed grant is cheap to report.
    """

    monkeypatch.setenv(TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE, json.dumps([entry]))

    with pytest.raises(ValueError) as raised:
        workbench_egress_policy(EgressConfig(_env_file=None))  # pyright: ignore[reportCallIssue]

    assert TRUSTED_DESTINATIONS_ENVIRONMENT_VARIABLE in str(raised.value)
    assert entry in str(raised.value)


def _git_repository(root: Path) -> Path:
    """Create a throwaway repository holding one committed file.

    The development build digest is read from the working tree, so these tests need a
    repository that answers the same way on every machine: no global or system git
    config, and an identity supplied per command rather than borrowed from whoever
    runs the suite.
    """

    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }

    def run(*arguments: str) -> None:
        subprocess.run(
            ("git", *arguments),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
        )

    root.mkdir(parents=True, exist_ok=True)
    run("init", "-q", "--initial-branch=main")
    (root / "operator.py").write_text("VALUE = 1\n", encoding="utf-8")
    run("add", "operator.py")
    run(
        "-c",
        "user.email=grafy@example.invalid",
        "-c",
        "user.name=Grafy Test",
        "commit",
        "-q",
        "-m",
        "source",
    )
    return root


def _tree_digest(root: Path) -> str | None:
    """Read the working-tree digest now, bypassing the one-read-per-process cache.

    A restart is exactly that: a fresh read of the tree. Asserting through the uncached
    derivation is what lets a test say something about a second process, which the
    process that runs the test cannot be.
    """

    return _working_tree_build_digest(root)


def _inside_repository(root: Path) -> bool:
    completed = subprocess.run(
        ("git", "-C", str(root), "rev-parse", "--show-toplevel"),
        capture_output=True,
    )
    return completed.returncode == 0


def _development_digest() -> str:
    """The digest a development process gives itself in the current directory."""

    return AppConfig(
        environment="development",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    ).resolved_build_digest


def test_the_development_digest_is_a_property_of_the_tree_not_of_the_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restart that changed no source must keep what the last run produced.

    Materialized outputs and cached invocations carry the build digest as their
    identity. A development process invented a new digest every boot, so restarting the
    API presented every output card as never materialized even though the source was
    byte-identical. The identity comes from the tree instead, and a tree answers the
    same question the same way twice.
    """

    repository = _git_repository(tmp_path / "repo")
    monkeypatch.chdir(repository)

    assert _tree_digest(repository) == _tree_digest(repository)
    assert _development_digest() == _tree_digest(repository)


def test_editing_source_moves_the_development_digest(tmp_path: Path) -> None:
    """A stable digest still has to move when the code behind an output changes.

    Stability alone would be worse than the digest it replaced: an output produced by
    different code must never be served as current. Both ways an edit reaches a running
    process count — a tracked file rewritten, and a new file picked up without ever
    being committed.
    """

    repository = _git_repository(tmp_path / "repo")
    committed = _tree_digest(repository)

    (repository / "operator.py").write_text("VALUE = 2\n", encoding="utf-8")
    edited = _tree_digest(repository)
    (repository / "operator.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert committed is not None
    assert edited is not None
    assert edited != committed
    assert _tree_digest(repository) == committed

    (repository / "new_operator.py").write_text("VALUE = 3\n", encoding="utf-8")
    assert _tree_digest(repository) != committed


def test_ignored_paths_are_not_source_for_the_development_digest(
    tmp_path: Path,
) -> None:
    """The local database, object store and secrets do not identify the code.

    Reading the tree happens at startup, so `.gitignore` is what keeps a development
    database and a rewritten `.env` from being hashed as if they were source — and what
    keeps an unrelated write from discarding every cached output.
    """

    repository = _git_repository(tmp_path / "repo")
    (repository / ".gitignore").write_text("*.sqlite3\n", encoding="utf-8")
    before = _tree_digest(repository)

    (repository / "grafy.sqlite3").write_bytes(b"\x00" * 4096)

    assert _tree_digest(repository) == before


def test_a_source_tree_that_cannot_be_read_falls_back_to_invalidating_everything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Where no identity can be verified, none is claimed.

    Outside a repository the digest cannot be derived, so the process keeps the
    per-process digest it had before: every materialized output reads as foreign to it,
    which is the safe direction to be wrong in.
    """

    if _inside_repository(tmp_path):
        pytest.skip("the temporary directory sits inside a repository")
    monkeypatch.chdir(tmp_path)

    digest = _development_digest()

    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest == _development_digest()


def test_an_explicit_build_digest_wins_over_the_working_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deployment always states its own identity; derivation is only the fallback."""

    monkeypatch.chdir(_git_repository(tmp_path / "repo"))
    monkeypatch.setenv("GRAFY_BUILD_DIGEST", "b" * 64)

    assert _development_digest() == "b" * 64


def test_production_refuses_to_derive_its_build_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container's digest names an immutable image, so a working tree never stands in."""

    monkeypatch.chdir(_git_repository(tmp_path / "repo"))

    with pytest.raises(ValueError, match="GRAFY_BUILD_DIGEST"):
        AppConfig(  # pyright: ignore[reportCallIssue]
            environment="production",
            _env_file=None,  # pyright: ignore[reportCallIssue]
        ).resolved_build_digest
