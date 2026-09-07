from pathlib import Path
import subprocess

import pytest

from grafy_api.plugins.publication.sandbox import (
    DockerPluginDirectoryPublisher,
    DockerPublisherSandbox,
    PublisherSandboxResult,
)
from grafy_api.plugins.publication.source import PluginPublishingError
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
)
from grafy_core.plugin_inspector import InspectionResult


def test_candidate_command_is_networkless_read_only_and_resource_bounded(
    tmp_path: Path,
) -> None:
    sandbox = DockerPublisherSandbox(image="grafy-publisher@sha256:abc")

    command = sandbox.command(
        ("/venv/bin/python", "-m", "pytest", "-q"),
        source=tmp_path / "snapshot",
        source_read_only=True,
        environment_directory=tmp_path / "venv",
        cache_directory=tmp_path / "cache",
        network_enabled=False,
        environment_read_only=True,
    )

    assert command[:3] == ("docker", "run", "--rm")
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--pids-limit") + 1] == "128"
    assert command[command.index("--memory") + 1] == "1g"
    assert command[command.index("--memory-swap") + 1] == "1g"
    assert command[command.index("--cpus") + 1] == "1.0"
    mounts = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--mount"
    ]
    assert mounts == [
        f"type=bind,src={tmp_path / 'snapshot'},dst=/candidate,readonly",
        f"type=bind,src={tmp_path / 'venv'},dst=/venv,readonly",
        f"type=bind,src={tmp_path / 'cache'},dst=/cache,readonly",
    ]
    assert not any("SECRET" in value or "DATABASE_URL" in value for value in command)


def test_dependency_fetch_is_the_only_network_enabled_phase(tmp_path: Path) -> None:
    sandbox = DockerPublisherSandbox(image="grafy-publisher:local")

    command = sandbox.command(
        ("uv", "sync", "--locked", "--active"),
        source=tmp_path / "snapshot",
        source_read_only=False,
        environment_directory=tmp_path / "venv",
        cache_directory=tmp_path / "cache",
        network_enabled=True,
        environment_read_only=False,
    )

    assert command[command.index("--network") + 1] == "bridge"
    mounts = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--mount"
    ]
    assert mounts[0].endswith("dst=/candidate")
    assert mounts[1].endswith("dst=/venv")
    assert mounts[2].endswith("dst=/cache")
    assert all(not mount.endswith("readonly") for mount in mounts[1:])


def test_directory_publisher_resolves_the_locked_vendored_wheel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "candidate"
    (project / "src" / "grafy_plugin").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "wheels").mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\n"
        'name = "candidate"\n'
        'version = "0.1.0"\n'
        'dependencies = ["grafy-core==0.1.0"]\n',
        encoding="utf-8",
    )
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (project / "src" / "grafy_plugin" / "__init__.py").write_text(
        "PLUGIN = None\n",
        encoding="utf-8",
    )
    (project / "tests" / "test_plugin.py").write_text(
        "def test_plugin() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    (project / "wheels" / "grafy_core-0.1.0-py3-none-any.whl").write_bytes(
        b"wheel"
    )
    inspected = InspectionResult(
        catalog=PluginCatalogManifest(
            slug="candidate",
            title="Candidate",
            nodes=(
                PluginNodeContract(
                    operator_id="candidate.echo",
                    operator_version=1,
                    title="Echo",
                    description="Echo",
                    config_schema={"type": "object"},
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    inputs=(),
                    outputs=(),
                ),
            ),
        ),
        capabilities=PluginCapabilityManifest(),
    )
    commands: list[tuple[str, ...]] = []

    def record(
        _sandbox: DockerPublisherSandbox,
        command: tuple[str, ...],
        **_arguments: object,
    ) -> PublisherSandboxResult:
        commands.append(command)
        stdout = (
            inspected.model_dump_json().encode()
            if "grafy_core.plugin_inspector" in command
            else b""
        )
        return PublisherSandboxResult(
            returncode=0,
            stdout=stdout,
            stderr=b"",
            output_truncated=False,
        )

    monkeypatch.setattr(DockerPublisherSandbox, "run", record)

    DockerPluginDirectoryPublisher(
        (tmp_path,),
        runtime_profile="python-uv",
        image="publisher:local",
    ).verify(
        project,
        expected_slug="candidate",
        loader_target="grafy_plugin_candidate.plugin:CANDIDATE",
    )

    sync_command = next(command for command in commands if command[:2] == ("uv", "sync"))
    assert "--no-editable" in sync_command
    assert sync_command[-2:] == ("--find-links", "/candidate/wheels")
    inspection_command = next(
        command for command in commands if "grafy_core.plugin_inspector" in command
    )
    assert inspection_command[-1] == "grafy_plugin_candidate.plugin:CANDIDATE"


def test_sandbox_fails_closed_when_output_exceeds_the_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = DockerPublisherSandbox(
        image="grafy-publisher:local",
        log_limit_bytes=16,
    )

    def truncated(_command: tuple[str, ...]) -> PublisherSandboxResult:
        return PublisherSandboxResult(
            returncode=0,
            stdout=b"truncated output",
            stderr=b"",
            output_truncated=True,
        )

    monkeypatch.setattr(
        sandbox,
        "_spawn",
        truncated,
    )

    with pytest.raises(PluginPublishingError, match="output limit"):
        sandbox.run(
            ("uv", "lock", "--check"),
            source=tmp_path / "snapshot",
            source_read_only=True,
            environment_directory=tmp_path / "venv",
            cache_directory=tmp_path / "cache",
            network_enabled=True,
            environment_read_only=False,
            operation="lock check",
        )


def test_sandbox_wraps_timeout_with_operation_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = DockerPublisherSandbox(image="grafy-publisher:local")

    def timeout(_command: tuple[str, ...]) -> PublisherSandboxResult:
        raise subprocess.TimeoutExpired(("docker", "run"), 600)

    monkeypatch.setattr(sandbox, "_spawn", timeout)

    with pytest.raises(PluginPublishingError, match="catalog inspection") as excinfo:
        sandbox.run(
            ("/venv/bin/python", "-m", "grafy_core.plugin_inspector"),
            source=tmp_path / "snapshot",
            source_read_only=True,
            environment_directory=tmp_path / "venv",
            cache_directory=tmp_path / "cache",
            network_enabled=False,
            environment_read_only=True,
            operation="catalog inspection",
        )

    assert isinstance(excinfo.value.__cause__, subprocess.TimeoutExpired)
