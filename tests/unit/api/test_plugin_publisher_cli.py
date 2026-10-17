import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest


from grafy_shared.config import AppConfig, EgressConfig, PluginsConfig, StorageConfig
from pydantic import SecretStr

from grafy_api.settings import Settings
from grafy_api import cli
from grafy_api.cli_credentials import CredentialDigest
from grafy_api.plugins.publication.source import PluginPublishingError
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventoryError,
)
from grafy_core.domain.plugin_revocations import PluginReleaseRevocationError
from grafy_core.domain.identity import PlatformTokenPrincipal
from grafy_core.domain.plugin_releases import PlatformPluginActor


class FakeDatabase:
    sessions = object()

    async def dispose(self) -> None:
        pass


class FakePluginReleaseService:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs


class FakePluginOciImageBuilder:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs


class FakeIdentityService:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def authenticate_platform_access_token(
        self, **kwargs: object
    ) -> PlatformTokenPrincipal:
        del kwargs
        return PlatformTokenPrincipal(
            principal_reference="ci:test",
            credential_reference="platform-token:test",
            scopes=frozenset(),
            token_id=UUID("00000000-0000-0000-0000-000000000004"),
        )


def platform_credential(_database_url: str) -> CredentialDigest:
    return CredentialDigest("platform", "gpat_test", b"digest")


class RecordingPluginChecker:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def verify(
        self,
        directory: Path,
    ) -> SimpleNamespace:
        assert directory == Path("tests/fixtures/plugin-notes")
        return SimpleNamespace(
            loader_target="verified_plugin:PLUGIN",
            catalog=SimpleNamespace(
                slug="notes",
                nodes=(object(), object()),
                artifact_types=(object(),),
            ),
            capabilities=SimpleNamespace(capabilities=()),
            source_archive=b"verified source",
            source_digest=(
                "a4d4e45e121b5a09d0219a01e0dc212a76cb9198f016a79e9901c720cf32487f"
            ),
            lock_digest="1" * 64,
            runtime_profile="python-uv",
        )


def create_fake_database(database_url: str) -> FakeDatabase:
    del database_url
    return FakeDatabase()


def configured_fake_storage(cfg: object, workspace: object) -> object:
    del cfg, workspace
    return object()


def fake_isolated_release_admission(**kwargs: object) -> object:
    del kwargs
    return object()


def test_check_valid_plugin_is_read_only_and_reports_the_verified_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        plugins=PluginsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            plugin_runtime_profile="python-uv",
            plugin_roots=(Path("tests/fixtures"),),
        )
    )

    def fail_if_database_is_opened(_database_url: str) -> object:
        raise AssertionError("plugin check must not open the database")

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_database", fail_if_database_is_opened)
    monkeypatch.setattr(cli, "PluginDirectoryPublisher", RecordingPluginChecker)
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "check", "tests/fixtures/plugin-notes"],
    )

    cli.main()

    output = capsys.readouterr().out
    assert '"status": "valid"' in output
    assert '"slug": "notes"' in output
    assert '"loader_target": "verified_plugin:PLUGIN"' in output
    assert '"node_count": 2' in output
    assert '"artifact_type_count": 1' in output
    assert '"source_digest": "' in output


def test_check_incomplete_plugin_reports_the_missing_requirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "incomplete"
    (project / "src" / "grafy_plugin").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'incomplete'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    settings = Settings(
        plugins=PluginsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            plugin_runtime_profile="python-uv",
            plugin_roots=(tmp_path,),
        )
    )

    def fail_if_database_is_opened(_database_url: str) -> object:
        raise AssertionError("plugin check must not open the database")

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_database", fail_if_database_is_opened)
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "check", str(project)],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 1
    assert (
        "Plugin check failed: Plugin source archive is missing 'uv.lock'"
        in capsys.readouterr().err
    )


def test_check_rejects_a_plugin_outside_the_configured_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    project = tmp_path / "outside"
    project.mkdir()
    settings = Settings(
        plugins=PluginsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            plugin_runtime_profile="python-uv",
            plugin_roots=(allowed_root,),
        )
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "check", str(project)],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 1
    message = capsys.readouterr().err
    assert "Plugin check failed:" in message
    assert "outside configured roots" in message


def test_check_rejects_a_symlinked_source_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "symlinked"
    project.mkdir()
    outside_source = tmp_path / "outside-source"
    outside_source.mkdir()
    (project / "src").symlink_to(outside_source, target_is_directory=True)
    (project / "tests").mkdir()
    (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    settings = Settings(
        plugins=PluginsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            plugin_runtime_profile="python-uv",
            plugin_roots=(tmp_path,),
        )
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "check", str(project)],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 1
    message = capsys.readouterr().err
    assert "Plugin check failed:" in message
    assert "unsupported symlinked directory" in message
    assert str(outside_source) in message


class RecordingSystemPublisher:
    observed_loader_target: str | None = None
    observed_scratch_root: Path | None = None

    def __init__(
        self,
        *args: object,
        scratch_root: Path | None = None,
        **kwargs: object,
    ) -> None:
        del args, kwargs
        type(self).observed_scratch_root = scratch_root

    def verify(
        self,
        directory: object,
        *,
        expected_slug: str | None = None,
        loader_target: str,
    ) -> object:
        del directory
        assert expected_slug == "external.llm"
        type(self).observed_loader_target = loader_target
        return object()


class FakeSystemPublicationWorkflow:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def publish_verified(
        self,
        verified: object,
        *,
        platform_actor: PlatformPluginActor,
    ) -> SimpleNamespace:
        del verified, platform_actor
        return SimpleNamespace(release=SimpleNamespace(slug="external.llm", revision=1))


def test_publish_requires_the_sandbox_image_at_parse_time(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "publish", "/plugins/notes", "--slug", "external.llm"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
    assert "--sandbox-image" in capsys.readouterr().err


def test_publish_help_offers_no_workspace_or_target_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "publish", "--help"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "--slug" in output
    assert "--sandbox-image" in output
    assert "--global" not in output
    assert "--workspace" not in output
    assert "--actor" not in output


def test_global_publish_inspects_with_checked_in_loader_target(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    publisher_scratch_root = Path("/docker-visible/plugin-publisher")
    settings = Settings(
        app=AppConfig(_env_file=None, database_url=SecretStr("sqlite+aiosqlite://")),  # pyright: ignore[reportCallIssue]
        storage=StorageConfig(_env_file=None, storage_bucket="plugins"),  # pyright: ignore[reportCallIssue]
        plugins=PluginsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            plugin_runtime_profile="python-uv",
            plugin_roots=(),
            plugin_publisher_scratch_root=publisher_scratch_root,
        ),
        egress=EgressConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            plugin_egress_broker_image=("registry.example/grafy@sha256:" + "a" * 64),
            plugin_http_egress_destinations=("https://api.example.com:443",),
        ),
    )
    RecordingSystemPublisher.observed_loader_target = None
    RecordingSystemPublisher.observed_scratch_root = None
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_database", create_fake_database)
    monkeypatch.setattr(cli, "configured_file_storage", configured_fake_storage)
    monkeypatch.setattr(cli, "PluginReleaseService", FakePluginReleaseService)
    monkeypatch.setattr(cli, "PluginOciImageBuilder", FakePluginOciImageBuilder)
    monkeypatch.setattr(cli, "IdentityService", FakeIdentityService)
    monkeypatch.setattr(cli, "_load_credential_digest", platform_credential)
    monkeypatch.setattr(
        cli,
        "isolated_release_admission",
        fake_isolated_release_admission,
    )
    monkeypatch.setattr(
        cli,
        "DockerPluginDirectoryPublisher",
        RecordingSystemPublisher,
    )
    monkeypatch.setattr(
        cli,
        "SystemPluginPublicationWorkflow",
        FakeSystemPublicationWorkflow,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "grafy",
            "plugin",
            "publish",
            "plugins/llm",
            "--slug",
            "external.llm",
            "--sandbox-image",
            "grafy-publisher:test",
        ],
    )

    cli.main()

    assert (
        RecordingSystemPublisher.observed_loader_target == "grafy_plugin_llm.plugin:LLM"
    )
    assert RecordingSystemPublisher.observed_scratch_root == publisher_scratch_root
    assert (
        "Published System Plugin external.llm release 1; promote it explicitly "
        "to activate it" in capsys.readouterr().out
    )


def test_global_promotion_is_a_distinct_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "promote", "--help"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "release" in output
    assert "--if-generation" in output
    assert "--deployment-manifest" not in output
    assert "--actor" not in output


def test_publish_rejects_legacy_scope_and_actor_options(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "grafy",
            "plugin",
            "publish",
            "plugins/llm",
            "--workspace",
            "00000000-0000-0000-0000-000000000001",
            "--slug",
            "external.llm",
            "--actor",
            "ci:test",
            "--sandbox-image",
            "grafy-publisher:test",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_global_revocation_uses_release_reference_and_derived_platform_actor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "revoke", "--help"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "release" in output
    assert "--reason" in output
    assert "security" in output
    assert "--platform-actor" not in output


def test_auth_and_platform_token_commands_do_not_accept_raw_token_arguments(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "admin", "platform-token", "create", "--help"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "--principal" in output
    assert "--label" in output
    assert "--scope" in output
    assert "--expires-at" in output
    assert "--token" not in output

    monkeypatch.setattr(sys, "argv", ["grafy", "auth", "login", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert "--token" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure",
    (
        PluginPublishingError("Plugin publisher sandbox lock check failed"),
        PluginReleaseRevocationError(
            "System Plugin revocation requires a drained execution queue"
        ),
        SystemPluginInventoryError("System Plugin 'llm' is not registered"),
    ),
)
def test_cli_renders_publication_failures_without_a_traceback(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(_args: object) -> None:
        raise failure

    monkeypatch.setattr(cli, "_run", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "plugin", "check", "plugins/llm"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
    error = capsys.readouterr().err
    assert str(failure) in error
    assert "Traceback" not in error


@pytest.mark.parametrize("arguments", [("--help",), ("plugin", "--help")])
def test_cli_help_omits_retired_tooling(
    arguments: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["grafy", *arguments])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "system-cutover" not in output
    assert "build-system-deployment" not in output
