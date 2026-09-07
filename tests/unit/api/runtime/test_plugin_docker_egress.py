import asyncio
import base64
from ipaddress import ip_address
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginReleaseScope,
    PluginRuntimeArtifact,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.plugin_invocation import PluginInvocationRequest

from grafy_api.plugin_egress import (
    PluginEgressAddressScope,
    PluginEgressBrokerPlan,
    PluginEgressBrokerPolicy,
    PluginEgressDestination,
    ResolvedPluginEgressDestination,
)
from grafy_api.plugins.profiles import runtime_profile
from grafy_api.network_policy import NetworkCaBundle
from grafy_api.v1.routes.executions.runtime.plugin_docker import (
    DockerPluginRuntime,
    DockerPluginRuntimeError,
    PluginRuntimeReleaseLookup,
    _Sandbox,  # pyright: ignore[reportPrivateUsage]
    _SandboxKey,  # pyright: ignore[reportPrivateUsage]
    _sandbox_key_sha256,  # pyright: ignore[reportPrivateUsage]
)
from grafy_api.v1.routes.executions.runtime.plugin_sandbox import (
    PluginSandboxScopeId,
)


_BROKER_IMAGE = "registry.example/grafy-egress@sha256:" + "a" * 64
_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000993")


def _key(
    *capabilities: PluginRuntimeCapability,
    scope_id: PluginSandboxScopeId | None = None,
    postgresql_destination: PluginEgressDestination | None = None,
    network_profile_digest: str | None = None,
    http_destinations: tuple[PluginEgressDestination, ...] = (),
    http_address_scope: PluginEgressAddressScope = PluginEgressAddressScope.PUBLIC,
    network_ca_bundle_sha256: str | None = None,
) -> _SandboxKey:
    return _SandboxKey(
        scope_id=scope_id or PluginSandboxScopeId.new(),
        workspace_id=_WORKSPACE_ID,
        release_scope=PluginReleaseScope.WORKSPACE,
        release_workspace_id=_WORKSPACE_ID,
        release_slug="egress-test",
        release_revision=1,
        source_digest="b" * 64,
        descriptor_digest="c" * 64,
        required_capabilities=capabilities,
        postgresql_destination=postgresql_destination,
        network_profile_digest=network_profile_digest,
        http_destinations=http_destinations,
        http_address_scope=http_address_scope,
        network_ca_bundle_sha256=network_ca_bundle_sha256,
    )


def _artifact() -> PluginRuntimeArtifact:
    return PluginRuntimeArtifact(
        object_key="plugin-releases/egress-test/runtime/image.oci.tar",
        archive_digest="d" * 64,
        manifest_digest="e" * 64,
        config_digest="f" * 64,
    )


def _runtime(tmp_path: Path, *, with_egress: bool = True) -> DockerPluginRuntime:
    destinations = (
        (
            PluginEgressDestination.parse("https://api.example.com:443"),
            PluginEgressDestination.parse(
                "postgresql://database.example.com:5432"
            ),
        )
        if with_egress
        else ()
    )
    return DockerPluginRuntime(
        releases=cast(PluginRuntimeReleaseLookup, object()),
        storage=cast(FileStoragePort, object()),
        bucket="test",
        profile=runtime_profile("python-uv"),
        scratch_root=tmp_path,
        egress_policy=PluginEgressBrokerPolicy(
            broker_image=_BROKER_IMAGE if with_egress else None,
            destinations=destinations,
        ),
    )


def _public_answers(
    *_args: object,
    **_kwargs: object,
) -> list[tuple[object, ...]]:
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ]


@pytest.mark.asyncio
async def test_runtime_readiness_rejects_incompatible_egress_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.ERROR,
        logger="grafy_api.v1.routes.executions.runtime.plugin_docker",
    )
    runtime = _runtime(tmp_path)
    commands: list[tuple[str, ...]] = []

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        commands.append(arguments)
        stdout = b"28.3.3\n"
        if arguments[0:2] == ("image", "inspect"):
            stdout = b'{"io.grafy.plugin.egress-broker.policy-config-version":"1"}\n'
        return DockerPluginRuntime._Completed(0, stdout, b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(runtime, "_docker", docker)

    with pytest.raises(
        DockerPluginRuntimeError,
        match=(
            "Plugin egress broker image is incompatible: expected policy config "
            "version 2, found 1"
        ),
    ):
        await runtime.check_ready()

    assert commands == [
        ("version", "--format", "{{.Server.Version}}"),
        (
            "image",
            "inspect",
            "--format",
            "{{json .Config.Labels}}",
            _BROKER_IMAGE,
        ),
    ]
    assert not any(command[0] in {"create", "network"} for command in commands)
    failure_record = next(
        record
        for record in caplog.records
        if record.message == "plugin_egress_broker_incompatible"
    )
    assert cast(str, failure_record.__dict__["broker_image"]) == _BROKER_IMAGE
    assert cast(
        int,
        failure_record.__dict__["expected_contract_version"],
    ) == 2
    assert cast(
        str,
        failure_record.__dict__["actual_contract_version"],
    ) == "1"
    assert cast(str, failure_record.__dict__["reason"]) == "version_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inspect_returncode", "inspect_stdout", "error_match", "reason", "actual"),
    [
        (1, b"", "is not available to Docker", "image_unavailable", "unavailable"),
        (
            0,
            b"not-json\n",
            "invalid compatibility metadata",
            "metadata_invalid",
            "invalid",
        ),
    ],
)
async def test_runtime_readiness_logs_safe_broker_contract_failure_reason(
    inspect_returncode: int,
    inspect_stdout: bytes,
    error_match: str,
    reason: str,
    actual: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.ERROR,
        logger="grafy_api.v1.routes.executions.runtime.plugin_docker",
    )
    runtime = _runtime(tmp_path)

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        if arguments[0:2] == ("image", "inspect"):
            return DockerPluginRuntime._Completed(  # pyright: ignore[reportPrivateUsage]
                inspect_returncode,
                inspect_stdout,
                b"",
            )
        return DockerPluginRuntime._Completed(0, b"28.3.3\n", b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(runtime, "_docker", docker)

    with pytest.raises(DockerPluginRuntimeError, match=error_match):
        await runtime.check_ready()

    failure_record = next(
        record
        for record in caplog.records
        if record.message == "plugin_egress_broker_incompatible"
    )
    assert cast(str, failure_record.__dict__["broker_image"]) == _BROKER_IMAGE
    assert cast(str, failure_record.__dict__["reason"]) == reason
    assert cast(
        str,
        failure_record.__dict__["actual_contract_version"],
    ) == actual


@pytest.mark.asyncio
@pytest.mark.parametrize("labels", [b"null\n", b"{}\n"])
async def test_runtime_readiness_rejects_unlabelled_egress_broker(
    labels: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        stdout = labels if arguments[0:2] == ("image", "inspect") else b"28.3.3\n"
        return DockerPluginRuntime._Completed(0, stdout, b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(runtime, "_docker", docker)

    with pytest.raises(DockerPluginRuntimeError, match="found undeclared"):
        await runtime.check_ready()


@pytest.mark.asyncio
async def test_runtime_readiness_accepts_matching_egress_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        stdout = b"28.3.3\n"
        if arguments[0:2] == ("image", "inspect"):
            stdout = b'{"io.grafy.plugin.egress-broker.policy-config-version":"2"}\n'
        return DockerPluginRuntime._Completed(0, stdout, b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(runtime, "_docker", docker)

    await runtime.check_ready()


@pytest.mark.skipif(sys.platform == "win32", reason="fork is POSIX-specific")
@pytest.mark.asyncio
async def test_runtime_readiness_never_falls_back_to_fork(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker = tmp_path / "fake-docker"
    docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")

    def reject_fork(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Docker command fell back to unsafe fork")

    monkeypatch.setattr(subprocess, "_fork_exec", reject_fork)
    runtime = DockerPluginRuntime(
        releases=cast(PluginRuntimeReleaseLookup, object()),
        storage=cast(FileStoragePort, object()),
        bucket="test",
        profile=runtime_profile("python-uv"),
        scratch_root=tmp_path / "scratch",
        docker_binary="fake-docker",
    )

    await runtime.check_ready()


@pytest.mark.asyncio
async def test_egress_sandbox_uses_two_dedicated_networks_and_broker_only_outbound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    commands: list[tuple[str, ...]] = []

    async def docker(
        arguments: tuple[str, ...],
        *,
        timeout: int,
        max_stdout: int,
        max_stderr: int = 1 * 1_024 * 1_024,
        input_bytes: bytes | None = None,
        check: bool,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        del timeout, max_stdout, max_stderr, input_bytes, check
        commands.append(arguments)
        stdout = b""
        if arguments[0] == "create":
            stdout = b"broker-id\n" if _BROKER_IMAGE in arguments else b"sandbox-id\n"
        return DockerPluginRuntime._Completed(0, stdout, b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(socket, "getaddrinfo", _public_answers)
    monkeypatch.setattr(runtime, "_docker", docker)
    sandbox = await runtime._create_container(  # pyright: ignore[reportPrivateUsage]
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            PluginRuntimeCapability.POSTGRESQL_EGRESS,
            postgresql_destination=PluginEgressDestination.parse(
                "postgresql://database.example.com:5432"
            ),
            network_profile_digest="d" * 64,
            http_destinations=(
                PluginEgressDestination.parse("https://api.example.com:443"),
            ),
        ),
        _artifact(),
        tmp_path,
    )

    network_creates = [
        command for command in commands if command[:2] == ("network", "create")
    ]
    broker_create = next(
        command
        for command in commands
        if command[0] == "create" and _BROKER_IMAGE in command
    )
    sandbox_create = next(
        command
        for command in commands
        if command[0] == "create" and _BROKER_IMAGE not in command
    )
    network_connect = next(
        command for command in commands if command[:2] == ("network", "connect")
    )

    assert len(network_creates) == 2
    assert "--internal" in network_creates[0]
    assert "--internal" not in network_creates[1]
    assert broker_create[broker_create.index("--network") + 1] == sandbox.egress_network
    assert sandbox_create[sandbox_create.index("--network") + 1] == (
        sandbox.guest_network
    )
    assert sandbox.egress_network not in sandbox_create
    assert broker_create[broker_create.index("--memory-swap") + 1] == "134217728"
    assert sandbox_create[sandbox_create.index("--memory-swap") + 1] == str(
        runtime_profile("python-uv").memory_bytes
    )
    assert network_connect[-2:] == (sandbox.guest_network, "broker-id")
    assert ("--alias", "database.example.com") == (
        network_connect[network_connect.index("database.example.com") - 1],
        "database.example.com",
    )
    assert "--network=none" not in sandbox_create
    policy_environment = next(
        value
        for value in broker_create
        if value.startswith("GRAFY_PLUGIN_EGRESS_POLICY_B64=")
    )
    policy = base64.b64decode(
        policy_environment.partition("=")[2],
        validate=True,
    ).decode("utf-8")
    assert '"dns_resolution":"forbidden"' in policy
    assert '"connect_addresses":["93.184.216.34"]' in policy
    assert '"password"' not in policy

    await runtime._remove_sandbox_resources(  # pyright: ignore[reportPrivateUsage]
        sandbox
    )

    assert ("rm", "-f", "sandbox-id") in commands
    assert ("rm", "-f", "broker-id") in commands
    assert ("network", "rm", sandbox.guest_network) in commands
    assert ("network", "rm", sandbox.egress_network) in commands


@pytest.mark.asyncio
@pytest.mark.parametrize("diagnostic_probes_fail", [False, True])
async def test_broker_readiness_failure_keeps_safe_deployment_diagnostics(
    diagnostic_probes_fail: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.ERROR,
        logger="grafy_api.v1.routes.executions.runtime.plugin_docker",
    )
    runtime = _runtime(tmp_path)
    commands: list[tuple[str, ...]] = []

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        commands.append(arguments)
        if arguments[0] == "create":
            return DockerPluginRuntime._Completed(0, b"broker-id\n", b"")  # pyright: ignore[reportPrivateUsage]
        if arguments[:2] == ("exec", "broker-id"):
            return DockerPluginRuntime._Completed(137, b"", b"")  # pyright: ignore[reportPrivateUsage]
        if arguments[:2] == ("inspect", "--format"):
            if diagnostic_probes_fail:
                raise TimeoutError("diagnostic state probe timed out")
            return DockerPluginRuntime._Completed(  # pyright: ignore[reportPrivateUsage]
                0,
                b'{"Status":"exited","ExitCode":1,"OOMKilled":false}\n',
                b"",
            )
        if arguments[:2] == ("logs", "--tail"):
            if diagnostic_probes_fail:
                raise TimeoutError("diagnostic log probe timed out")
            return DockerPluginRuntime._Completed(  # pyright: ignore[reportPrivateUsage]
                0,
                b"",
                b"Broker policy config version is unsupported\n",
            )
        return DockerPluginRuntime._Completed(0, b"", b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(socket, "getaddrinfo", _public_answers)
    monkeypatch.setattr(runtime, "_docker", docker)

    error_match = (
        "broker did not become ready"
        if diagnostic_probes_fail
        else "broker rejected policy config version 2"
    )
    with pytest.raises(DockerPluginRuntimeError, match=error_match):
        await runtime._create_container(  # pyright: ignore[reportPrivateUsage]
            _key(
                PluginRuntimeCapability.NETWORK_EGRESS,
                network_profile_digest="d" * 64,
                http_destinations=(
                    PluginEgressDestination.parse("https://api.example.com:443"),
                ),
            ),
            _artifact(),
            tmp_path,
        )

    assert ("rm", "-f", "broker-id") in commands
    assert len(
        [command for command in commands if command[:2] == ("network", "rm")]
    ) == 2
    failure_record = next(
        record
        for record in caplog.records
        if record.message == "plugin_egress_broker_readiness_failed"
    )
    assert cast(str, failure_record.__dict__["broker_image"]) == _BROKER_IMAGE
    assert cast(
        int,
        failure_record.__dict__["broker_contract_version"],
    ) == 2
    assert cast(int, failure_record.__dict__["ready_exit_code"]) == 137
    expected_status = "unknown" if diagnostic_probes_fail else "exited"
    expected_exit_code = None if diagnostic_probes_fail else 1
    expected_oom_killed = None if diagnostic_probes_fail else False
    assert cast(str, failure_record.__dict__["broker_status"]) == expected_status
    assert (
        cast(int | None, failure_record.__dict__["broker_exit_code"])
        == expected_exit_code
    )
    assert (
        cast(bool | None, failure_record.__dict__["broker_oom_killed"])
        is expected_oom_killed
    )
    assert cast(
        bool,
        failure_record.__dict__["broker_state_probe_succeeded"],
    ) is (not diagnostic_probes_fail)
    assert cast(
        bool,
        failure_record.__dict__["broker_log_probe_succeeded"],
    ) is (not diagnostic_probes_fail)
    assert cast(
        bool,
        failure_record.__dict__["broker_rejected_policy_version"],
    ) is (not diagnostic_probes_fail)


@pytest.mark.asyncio
async def test_untrusted_artifact_sql_keeps_network_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path, with_egress=False)
    commands: list[tuple[str, ...]] = []

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        commands.append(arguments)
        stdout = b"sandbox-id\n" if arguments[0] == "create" else b""
        return DockerPluginRuntime._Completed(0, stdout, b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(runtime, "_docker", docker)
    sandbox = await runtime._create_container(  # pyright: ignore[reportPrivateUsage]
        _key(PluginRuntimeCapability.UNTRUSTED_SQL),
        _artifact(),
        tmp_path,
    )

    create = next(command for command in commands if command[0] == "create")
    assert "--network=none" in create
    assert not any(command[0] == "network" for command in commands)
    assert sandbox.egress_plan is None


@pytest.mark.asyncio
async def test_sandbox_variants_of_one_release_use_distinct_container_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    created_ids = 0
    names: list[str] = []

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        nonlocal created_ids
        if arguments[0] == "create":
            created_ids += 1
            if f"sha256:{_artifact().manifest_digest}" in arguments:
                names.append(arguments[arguments.index("--name") + 1])
            return DockerPluginRuntime._Completed(  # pyright: ignore[reportPrivateUsage]
                0, f"container-{created_ids}\n".encode(), b""
            )
        return DockerPluginRuntime._Completed(0, b"", b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(socket, "getaddrinfo", _public_answers)
    monkeypatch.setattr(runtime, "_docker", docker)
    scope_id = PluginSandboxScopeId.new()
    await runtime._create_container(  # pyright: ignore[reportPrivateUsage]
        _key(scope_id=scope_id),
        _artifact(),
        tmp_path,
    )
    await runtime._create_container(  # pyright: ignore[reportPrivateUsage]
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            scope_id=scope_id,
            network_profile_digest="d" * 64,
            http_destinations=(
                PluginEgressDestination.parse("https://api.example.com:443"),
            ),
        ),
        _artifact(),
        tmp_path,
    )

    assert len(names) == 2
    assert names[0] != names[1]


@pytest.mark.asyncio
async def test_cancelled_egress_creation_removes_broker_container_and_networks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    commands: list[tuple[str, ...]] = []

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        commands.append(arguments)
        if arguments == ("start", "sandbox-id"):
            raise asyncio.CancelledError
        stdout = b""
        if arguments[0] == "create":
            stdout = b"broker-id\n" if _BROKER_IMAGE in arguments else b"sandbox-id\n"
        return DockerPluginRuntime._Completed(0, stdout, b"")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(socket, "getaddrinfo", _public_answers)
    monkeypatch.setattr(runtime, "_docker", docker)

    with pytest.raises(asyncio.CancelledError):
        await runtime._create_container(  # pyright: ignore[reportPrivateUsage]
            _key(
                PluginRuntimeCapability.NETWORK_EGRESS,
                network_profile_digest="d" * 64,
                http_destinations=(
                    PluginEgressDestination.parse("https://api.example.com:443"),
                ),
            ),
            _artifact(),
            tmp_path,
        )

    assert ("rm", "-f", "sandbox-id") in commands
    assert ("rm", "-f", "broker-id") in commands
    assert (
        len([command for command in commands if command[:2] == ("network", "rm")]) == 2
    )


def test_postgresql_keeps_original_transport_identity_and_artifact_query_has_no_env(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    destination = PluginEgressDestination.parse(
        "postgresql://database.example.com:5432"
    )
    plan = PluginEgressBrokerPlan.from_resolved(
        broker_image=_BROKER_IMAGE,
        sandbox_key_sha256="a" * 64,
        destinations=(
            ResolvedPluginEgressDestination(
                destination,
                (ip_address("93.184.216.34"),),
            ),
        ),
    )
    postgresql = _Sandbox(
        key=_key(
            PluginRuntimeCapability.POSTGRESQL_EGRESS,
            postgresql_destination=destination,
        ),
        container_id="postgresql",
        scratch_root=tmp_path,
        egress_plan=plan,
    )
    artifact_query = _Sandbox(
        key=_key(PluginRuntimeCapability.UNTRUSTED_SQL),
        container_id="artifact-query",
        scratch_root=tmp_path,
        egress_plan=plan,
    )
    request = cast(
        PluginInvocationRequest,
        SimpleNamespace(config={"host": "database.example.com", "port": 5432}),
    )

    postgresql_environment = runtime._guest_egress_environment(  # pyright: ignore[reportPrivateUsage]
        postgresql,
        request,
    )

    assert postgresql_environment == ()
    assert runtime._guest_egress_environment(  # pyright: ignore[reportPrivateUsage]
        artifact_query,
        request,
    ) == ()


def test_sandbox_key_separates_capability_profiles_and_scopes() -> None:
    scope = PluginSandboxScopeId.new()

    plain = _sandbox_key_sha256(_key(scope_id=scope))
    egress = _sandbox_key_sha256(
        _key(PluginRuntimeCapability.NETWORK_EGRESS, scope_id=scope)
    )
    other_scope = _sandbox_key_sha256(
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            scope_id=PluginSandboxScopeId.new(),
        )
    )

    assert len({plain, egress, other_scope}) == 3


def test_sandbox_key_separates_origin_variants_and_profile_digests() -> None:
    scope = PluginSandboxScopeId.new()
    first_origin = PluginEgressDestination.parse("https://one.example.com:443")
    second_origin = PluginEgressDestination.parse("https://two.example.com:443")

    base = _sandbox_key_sha256(
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            scope_id=scope,
            network_profile_digest="a" * 64,
            http_destinations=(first_origin,),
        )
    )
    other_origin = _sandbox_key_sha256(
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            scope_id=scope,
            network_profile_digest="a" * 64,
            http_destinations=(second_origin,),
        )
    )
    other_profile = _sandbox_key_sha256(
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            scope_id=scope,
            network_profile_digest="b" * 64,
            http_destinations=(first_origin,),
        )
    )
    same_variant = _sandbox_key_sha256(
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            scope_id=scope,
            network_profile_digest="a" * 64,
            http_destinations=(first_origin,),
        )
    )
    other_ca = _sandbox_key_sha256(
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            scope_id=scope,
            network_profile_digest="a" * 64,
            http_destinations=(first_origin,),
            network_ca_bundle_sha256="c" * 64,
        )
    )

    assert base == same_variant
    assert len({base, other_origin, other_profile, other_ca}) == 4


@pytest.mark.asyncio
async def test_egress_plan_covers_only_effective_destinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deployment allowlist is not ambient authority for new contracts."""

    runtime = _runtime(tmp_path)
    commands: list[tuple[str, ...]] = []

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        commands.append(arguments)
        stdout = b"" if arguments[0] != "create" else (
            b"broker-id\n" if _BROKER_IMAGE in arguments else b"sandbox-id\n"
        )
        return DockerPluginRuntime._Completed(0, stdout, b"")  # pyright: ignore[reportPrivateUsage]

    def public_answers(
        host: str,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[object, ...]]:
        address = "93.184.216.34" if host == "api.example.com" else "93.184.216.35"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", public_answers)
    monkeypatch.setattr(runtime, "_docker", docker)
    sandbox = await runtime._create_container(  # pyright: ignore[reportPrivateUsage]
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            network_profile_digest="a" * 64,
            http_destinations=(
                PluginEgressDestination.parse("https://api.example.com:443"),
            ),
        ),
        _artifact(),
        tmp_path,
    )

    assert sandbox.egress_plan is not None
    plan_hosts = {
        destination.destination.host
        for destination in sandbox.egress_plan.destinations
    }
    # The deployment also allowlists database.example.com for PostgreSQL, but
    # this HTTP-only sandbox plan must not carry it.
    assert plan_hosts == {"api.example.com"}

    await runtime._remove_sandbox_resources(  # pyright: ignore[reportPrivateUsage]
        sandbox
    )


@pytest.mark.asyncio
async def test_curated_runtime_carries_rfc1918_scope_into_broker_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    commands: list[tuple[str, ...]] = []

    async def docker(
        arguments: tuple[str, ...],
        **_kwargs: object,
    ) -> DockerPluginRuntime._Completed:  # pyright: ignore[reportPrivateUsage]
        commands.append(arguments)
        stdout = b"" if arguments[0] != "create" else (
            b"broker-id\n" if _BROKER_IMAGE in arguments else b"sandbox-id\n"
        )
        return DockerPluginRuntime._Completed(0, stdout, b"")  # pyright: ignore[reportPrivateUsage]

    def private_answer(
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.18.0.5", 8443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", private_answer)
    monkeypatch.setattr(runtime, "_docker", docker)
    ca_path = tmp_path / "provider-ca.crt"
    ca_path.write_bytes(
        (
            Path(__file__).resolve().parents[4]
            / "infra"
            / "e2e"
            / "tls"
            / "ca.crt"
        ).read_bytes()
    )
    ca_bundle = NetworkCaBundle.load(ca_path)
    sandbox = await runtime._create_container(  # pyright: ignore[reportPrivateUsage]
        _key(
            PluginRuntimeCapability.NETWORK_EGRESS,
            network_profile_digest="a" * 64,
            http_destinations=(
                PluginEgressDestination.parse("https://openai-e2e:8443"),
            ),
            http_address_scope=PluginEgressAddressScope.CURATED_RFC1918,
            network_ca_bundle_sha256=ca_bundle.sha256,
        ),
        _artifact(),
        tmp_path,
        network_ca_bundle=ca_bundle,
    )

    assert sandbox.egress_plan is not None
    resolved = sandbox.egress_plan.destinations[0]
    assert resolved.address_scope is PluginEgressAddressScope.CURATED_RFC1918
    assert tuple(str(address) for address in resolved.addresses) == ("172.18.0.5",)
    sandbox_create = next(
        command
        for command in commands
        if command[0] == "create" and _BROKER_IMAGE not in command
    )
    ca_mount = sandbox_create[sandbox_create.index("--mount") + 1]
    assert ca_mount.endswith(
        ",target=/run/grafy/network-ca.pem,readonly"
    )
    staged_path = Path(ca_mount.partition("source=")[2].split(",", 1)[0])
    assert staged_path.read_bytes() == ca_bundle.content
    environment = runtime._guest_egress_environment(  # pyright: ignore[reportPrivateUsage]
        sandbox,
        cast(PluginInvocationRequest, SimpleNamespace(config={})),
    )
    assert "SSL_CERT_FILE=/run/grafy/network-ca.pem" in environment

    await runtime._remove_sandbox_resources(  # pyright: ignore[reportPrivateUsage]
        sandbox
    )
