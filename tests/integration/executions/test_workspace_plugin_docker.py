import asyncio
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import cast
from uuid import UUID

import pytest

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    InMemoryUnitOfWork,
    JsonObject,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.plugin_releases import (
    PluginExecutionPolicy,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.nodes import NodeExecutionContext
from grafy_core.table_contracts import (
    Table,
    TableColumn,
    TableValueType,
)
from grafy_workbench.table.persistence import TableArtifactWriter
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginReleaseNodeConfig,
    PluginReleaseNode,
)
from grafy_core.runtime.plugin_protocol import PluginInvocationLimits
from grafy_storage import LocalFileObjectStore

from grafy_api.plugins.profiles import runtime_profile
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.publication.source import PluginDirectoryPublisher
from grafy_api.v1.routes.executions.runtime.plugin_artifacts import (
    ArtifactBundlePluginInvoker,
)
from grafy_api.v1.routes.executions.runtime.plugin_docker import DockerPluginRuntime
from grafy_api.v1.routes.executions.runtime.plugin_sandbox import (
    PluginSandboxScopeId,
    activate_plugin_sandbox_scope,
    reset_plugin_sandbox_scope,
)


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000951")


@dataclass
class ReleaseLookup:
    releases: tuple[InstalledPluginRelease, ...]

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None:
        for release in self.releases:
            if (
                scope is release.scope
                and workspace_id == release.workspace_id
                and slug == release.slug
                and revision == release.revision
            ):
                return release
        return None

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        del workspace_id, slug, revision
        return None

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        del slug, revision
        return None

    async def list_runtime_artifacts(self) -> list[PluginRuntimeArtifact]:
        return [
            release.runtime_artifact
            for release in self.releases
            if release.runtime_artifact is not None
        ]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    completed = subprocess.run(
        ("docker", "version", "--format", "{{.Server.Version}}"),
        check=False,
        capture_output=True,
        timeout=10,
    )
    return completed.returncode == 0


def _canonical(payload: JsonObject) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _instrumented_plugin_project(repository: Path, destination: Path) -> Path:
    source = repository / "examples" / "plugin-notes"
    destination.mkdir()
    for entry in ("pyproject.toml", "uv.lock", "wheels", "src", "tests"):
        source_entry = source / entry
        destination_entry = destination / entry
        if source_entry.is_dir():
            shutil.copytree(source_entry, destination_entry)
        else:
            shutil.copy2(source_entry, destination_entry)

    nodes = destination / "src" / "grafy_plugin" / "nodes.py"
    nodes.write_text(
        nodes.read_text(encoding="utf-8")
        + """

import asyncio
import os
import subprocess
from typing import Literal

from grafy_core.artifacts import NodeConfig


class RuntimeProbeConfig(NodeConfig):
    mode: Literal["identity", "sleep", "log", "output", "memory", "pids"]
    value: int = Field(default=0, ge=0, le=1_000_000_000)


class RuntimeProbeInput(NodeInput):
    pass


class RuntimeProbeOutput(NodeOutput):
    text: Annotated[TextValue, OutPort(TEXT_VALUE)]


@PLUGIN.function_node(
    operator_id="notes.runtime.probe",
    version=1,
    title="Runtime probe",
    cache_policy=NodeCachePolicy.NEVER,
)
async def runtime_probe(
    config: RuntimeProbeConfig,
    _inputs: RuntimeProbeInput,
) -> RuntimeProbeOutput:
    if config.mode == "identity":
        await asyncio.sleep(config.value / 1_000)
        value = f"{os.getpid()}|{os.environ['TMPDIR']}"
    elif config.mode == "sleep":
        await asyncio.sleep(config.value / 1_000)
        value = "slept"
    elif config.mode == "log":
        print("L" * config.value, flush=True)
        value = "logged"
    elif config.mode == "output":
        value = "O" * config.value
    elif config.mode == "memory":
        blocks = []
        for _ in range(config.value):
            blocks.append(bytearray(1_024 * 1_024))
            await asyncio.sleep(0)
        value = str(len(blocks))
    else:
        children = []
        try:
            for _ in range(config.value):
                children.append(subprocess.Popen(("sleep", "30")))
            value = str(len(children))
        finally:
            for child in children:
                child.terminate()
            for child in children:
                child.wait()
    return RuntimeProbeOutput(text=TextValue(value=value))
""",
        encoding="utf-8",
    )
    plugin_init = destination / "src" / "grafy_plugin" / "__init__.py"
    plugin_init.write_text(
        plugin_init.read_text(encoding="utf-8").replace(
            "from grafy_plugin.nodes import render_summary, summarize_table",
            (
                "from grafy_plugin.nodes import (\n"
                "    render_summary,\n"
                "    runtime_probe,\n"
                "    summarize_table,\n"
                ")"
            ),
        ),
        encoding="utf-8",
    )
    return destination


@pytest.mark.asyncio
async def test_docker_runtime_restores_reuses_hardens_and_cleans_sandbox(
    tmp_path: Path,
) -> None:
    if not _docker_available():
        pytest.skip("local Docker daemon is unavailable")
    repository = Path(__file__).resolve().parents[3]
    plugin_project = _instrumented_plugin_project(
        repository,
        tmp_path / "instrumented-plugin-notes",
    )
    verified = await asyncio.to_thread(
        PluginDirectoryPublisher(
            (tmp_path,),
            runtime_profile="python-uv",
        ).verify,
        plugin_project,
    )
    source_digest = sha256(verified.source_archive).hexdigest()
    contract_digest = plugin_contract_digest(verified.catalog)
    profile_digest = plugin_profile_digest(verified.runtime_profile)
    storage = LocalFileObjectStore(tmp_path / "objects")
    profile = runtime_profile(verified.runtime_profile)
    host_sentinel = tmp_path / "host-sentinel.txt"
    host_sentinel.write_text("host-only", encoding="utf-8")
    builder = PluginOciImageBuilder(
        storage,
        bucket="runtime-test",
        profile=profile,
    )
    artifact = await builder.build_and_store(
        candidate=verified,
    )
    repeated_artifact = await builder.build_and_store(
        candidate=verified,
    )
    assert repeated_artifact == artifact
    capabilities = verified.capabilities
    release_record = PluginRelease(
        slug=verified.catalog.slug,
        revision=1,
        catalog=verified.catalog,
        contract_digest=contract_digest,
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=profile_digest,
        source_object_key="plugin-releases/notes/source.tar.gz",
        source_digest=source_digest,
        lock_digest=verified.lock_digest,
        runtime_profile=verified.runtime_profile,
        loader_target=verified.loader_target,
        runtime_image_digest=artifact.manifest_digest,
        runtime_artifact=artifact,
        published_by_user_id=WORKSPACE_ID,
    )
    second_release_record = replace(
        release_record,
        revision=2,
        descriptor_digest=None,
    )
    installation = PluginInstallation.from_release(
        release_record,
        namespace=PluginReleaseNamespace(
            scope=PluginReleaseScope.WORKSPACE,
            workspace_id=WORKSPACE_ID,
        ),
        execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
        installed_by_user_id=WORKSPACE_ID,
        installed_by_platform_actor=None,
    )
    release = InstalledPluginRelease(
        release=release_record,
        installation=installation,
    )
    second_release = InstalledPluginRelease(
        release=second_release_record,
        installation=replace(
            installation,
            release_id=second_release_record.id,
            release_revision=second_release_record.revision,
        ),
    )
    subprocess.run(
        ("docker", "image", "rm", "-f", f"sha256:{artifact.manifest_digest}"),
        check=False,
        capture_output=True,
    )
    runtime = DockerPluginRuntime(
        releases=ReleaseLookup((release, second_release)),
        storage=storage,
        bucket="runtime-test",
        profile=profile,
        scratch_root=tmp_path / "scratch",
    )
    await runtime.recover_orphans()
    artifact_unit_of_work = InMemoryUnitOfWork()
    payload: JsonObject = {
        "row_count": 2,
        "column_count": 2,
        "column_ids": ["name", "amount"],
    }
    content = _canonical(payload)
    source_artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="notes.table_summary",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload=payload,
        byte_size=len(content),
        sha256=sha256(content).hexdigest(),
    )
    async with artifact_unit_of_work as entered:
        await entered.artifacts.add(source_artifact)
        await entered.commit()
    table_ref = await TableArtifactWriter(
        storage=storage,
        uow=artifact_unit_of_work,
        bucket="runtime-test",
        storage_backend="local",
    ).write(
        Table(
            columns=[
                TableColumn(
                    id="name",
                    title="Name",
                    value_type=TableValueType.TEXT,
                ),
                TableColumn(
                    id="amount",
                    title="Amount",
                    value_type=TableValueType.INTEGER,
                ),
            ],
            rows=[{"name": f"sample-{index}", "amount": index} for index in range(205)],
        ),
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="table-source",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=artifact_unit_of_work,
        runner=runtime,
        scratch=runtime,
        storage=storage,
        bucket="runtime-test",
        storage_backend="local",
    )
    contract = next(
        node
        for node in release.catalog.nodes
        if node.operator_id == "notes.summary.render"
    )
    node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, contract, invoker)
    second_release_node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(second_release, contract, invoker)
    summarize_contract = next(
        catalog_node
        for catalog_node in release.catalog.nodes
        if catalog_node.operator_id == "notes.table.summarize"
    )
    summarize_node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, summarize_contract, invoker)
    probe_contract = next(
        catalog_node
        for catalog_node in release.catalog.nodes
        if catalog_node.operator_id == "notes.runtime.probe"
    )
    probe_node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, probe_contract, invoker)
    config = node.config_contract.model.model_validate({})
    inputs = node.input_contract.model.model_validate(
        {"summary": source_artifact.ref()}
    )
    scope = PluginSandboxScopeId.new()
    token = activate_plugin_sandbox_scope(scope)
    cold_started = time.monotonic()
    try:
        first = await node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="render-1"),
            config,
            inputs,
        )
        cold_seconds = time.monotonic() - cold_started
        containers = subprocess.run(
            (
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=io.grafy.plugin.scope={scope.value}",
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert len(containers) == 1
        container_id = containers[0]
        inspected = json.loads(
            subprocess.run(
                ("docker", "inspect", container_id),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )[0]
        host_config = inspected["HostConfig"]
        assert inspected["Config"]["User"] == "65532:65532"
        assert host_config["NetworkMode"] == "none"
        assert host_config["ReadonlyRootfs"] is True
        assert host_config["Privileged"] is False
        assert host_config["CapDrop"] == ["ALL"]
        assert host_config["NanoCpus"] == int(profile.cpu_count * 1_000_000_000)
        assert host_config["PidsLimit"] == profile.pid_limit
        assert host_config["Memory"] == profile.memory_bytes
        assert host_config["MemorySwap"] == profile.memory_bytes
        assert "no-new-privileges=true" in host_config["SecurityOpt"]
        assert any(
            option.startswith("seccomp=") for option in host_config["SecurityOpt"]
        )
        assert host_config["Devices"] == []
        assert host_config["Ulimits"] == [
            {
                "Name": "nofile",
                "Hard": profile.open_file_limit,
                "Soft": profile.open_file_limit,
            }
        ]
        assert "size=16777216" in host_config["Tmpfs"]["/tmp"]
        assert "noexec" in host_config["Tmpfs"]["/tmp"]
        assert (
            str(profile.scratch_bytes) in host_config["Tmpfs"]["/run/grafy/invocations"]
        )
        assert inspected["Mounts"] == []
        isolation_probe = subprocess.run(
            (
                "docker",
                "exec",
                container_id,
                "/opt/grafy/plugin/.venv/bin/python",
                "-I",
                "-c",
                (
                    "import pathlib,socket,sys; "
                    "assert not pathlib.Path('/var/run/docker.sock').exists(); "
                    "assert not pathlib.Path('/workspace').exists(); "
                    "assert not pathlib.Path(sys.argv[1]).exists(); "
                    "s=socket.socket(); s.settimeout(0.2); "
                    "result=0; "
                    "\ntry: s.connect(('1.1.1.1',53)); result=9\n"
                    "except OSError: pass\n"
                    "sys.exit(result)"
                ),
                str(host_sentinel),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        assert isolation_probe.returncode == 0, isolation_probe.stderr

        warm_started = time.monotonic()
        second = await node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="render-2"),
            config,
            inputs,
        )
        warm_seconds = time.monotonic() - warm_started
        reused = subprocess.run(
            (
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=io.grafy.plugin.scope={scope.value}",
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert reused == [container_id]
        summarized = await summarize_node.run(
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="summarize-table",
            ),
            summarize_node.config_contract.model.model_validate({}),
            summarize_node.input_contract.model.model_validate({"table": table_ref}),
        )
        summary_ref = cast(ArtifactRef, summarized.__dict__["summary"])
        rendered_table_summary = await node.run(
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="render-table-summary",
            ),
            config,
            node.input_contract.model.model_validate({"summary": summary_ref}),
        )
        rendered_table_ref = cast(
            ArtifactRef,
            rendered_table_summary.__dict__["text"],
        )
        async with artifact_unit_of_work as entered:
            rendered_table_artifact = await entered.artifacts.get(
                WORKSPACE_ID,
                rendered_table_ref.artifact_id,
            )
        assert rendered_table_artifact is not None
        assert rendered_table_artifact.inline_payload == {
            "value": "205 rows, 2 columns: name, amount"
        }
        other_release_output = await second_release_node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="render-3"),
            config,
            inputs,
        )
        release_containers = subprocess.run(
            (
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=io.grafy.plugin.scope={scope.value}",
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert len(release_containers) == 2
        assert container_id in release_containers
        for output in (first, second, other_release_output):
            output_values = cast(dict[str, object], output.__dict__)
            ref = cast(ArtifactRef, output_values["text"])
            async with artifact_unit_of_work as entered:
                persisted = await entered.artifacts.get(WORKSPACE_ID, ref.artifact_id)
            assert persisted is not None
            assert persisted.inline_payload == {
                "value": "2 rows, 2 columns: name, amount"
            }
        print(
            "Workspace Plugin Docker latency: "
            f"cold={cold_seconds:.3f}s warm={warm_seconds:.3f}s"
        )
        assert cold_seconds < 30
        assert warm_seconds < 10

        probe_inputs = probe_node.input_contract.model.model_validate({})
        concurrent_outputs = await asyncio.gather(
            probe_node.run(
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="runtime-identity-0",
                    invocation_index=0,
                ),
                probe_node.config_contract.model.model_validate(
                    {"mode": "identity", "value": 300}
                ),
                probe_inputs,
            ),
            probe_node.run(
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="runtime-identity-1",
                    invocation_index=1,
                ),
                probe_node.config_contract.model.model_validate(
                    {"mode": "identity", "value": 300}
                ),
                probe_inputs,
            ),
        )
        child_identities: list[tuple[int, str]] = []
        for output in concurrent_outputs:
            ref = cast(ArtifactRef, output.__dict__["text"])
            async with artifact_unit_of_work as entered:
                identity_artifact = await entered.artifacts.get(
                    WORKSPACE_ID,
                    ref.artifact_id,
                )
            assert identity_artifact is not None
            identity_payload = identity_artifact.inline_payload
            assert identity_payload is not None
            identity_value = identity_payload["value"]
            assert isinstance(identity_value, str)
            child_pid, child_tmpdir = identity_value.split("|", maxsplit=1)
            child_identities.append((int(child_pid), child_tmpdir))
        assert child_identities[0][0] != child_identities[1][0]
        assert child_identities[0][1] != child_identities[1][1]
        assert all(
            path.startswith("/run/grafy/invocations/") and path.endswith("/tmp")
            for _, path in child_identities
        )

        pid_limited_invoker = ArtifactBundlePluginInvoker(
            unit_of_work=artifact_unit_of_work,
            runner=runtime,
            limits=PluginInvocationLimits(wall_time_seconds=20),
            scratch=runtime,
            storage=storage,
            bucket="runtime-test",
            storage_backend="local",
        )
        pid_probe: PluginReleaseNode[
            PluginReleaseNodeConfig,
            NodeInput,
            NodeOutput,
        ] = PluginReleaseNode(release, probe_contract, pid_limited_invoker)
        with pytest.raises(PluginInvocationError, match="operator_failure"):
            await pid_probe.run(
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="runtime-pids",
                ),
                pid_probe.config_contract.model.model_validate(
                    {"mode": "pids", "value": profile.pid_limit + 32}
                ),
                pid_probe.input_contract.model.model_validate({}),
            )

        output_limited_invoker = ArtifactBundlePluginInvoker(
            unit_of_work=artifact_unit_of_work,
            runner=runtime,
            limits=PluginInvocationLimits(max_output_bytes=1_024),
            scratch=runtime,
            storage=storage,
            bucket="runtime-test",
            storage_backend="local",
        )
        output_probe: PluginReleaseNode[
            PluginReleaseNodeConfig,
            NodeInput,
            NodeOutput,
        ] = PluginReleaseNode(
            release,
            probe_contract,
            output_limited_invoker,
        )
        with pytest.raises(PluginInvocationError, match="output_validation"):
            await output_probe.run(
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="runtime-output",
                ),
                output_probe.config_contract.model.model_validate(
                    {"mode": "output", "value": 16 * 1_024}
                ),
                output_probe.input_contract.model.model_validate({}),
            )

        timeout_invoker = ArtifactBundlePluginInvoker(
            unit_of_work=artifact_unit_of_work,
            runner=runtime,
            limits=PluginInvocationLimits(wall_time_seconds=1),
            scratch=runtime,
            storage=storage,
            bucket="runtime-test",
            storage_backend="local",
        )
        timeout_probe: PluginReleaseNode[
            PluginReleaseNodeConfig,
            NodeInput,
            NodeOutput,
        ] = PluginReleaseNode(release, probe_contract, timeout_invoker)
        with pytest.raises(PluginInvocationError, match="timeout"):
            await timeout_probe.run(
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="runtime-timeout",
                ),
                timeout_probe.config_contract.model.model_validate(
                    {"mode": "sleep", "value": 30_000}
                ),
                timeout_probe.input_contract.model.model_validate({}),
            )
        timeout_containers = subprocess.run(
            (
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=io.grafy.plugin.scope={scope.value}",
                "--filter",
                "label=io.grafy.plugin.release=notes@1",
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert timeout_containers == []

        cancellation = asyncio.create_task(
            probe_node.run(
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="runtime-cancel",
                ),
                probe_node.config_contract.model.model_validate(
                    {"mode": "sleep", "value": 30_000}
                ),
                probe_inputs,
            )
        )
        cancellation_deadline = time.monotonic() + 15
        while True:
            cancellation_containers = subprocess.run(
                (
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    f"label=io.grafy.plugin.scope={scope.value}",
                    "--filter",
                    "label=io.grafy.plugin.release=notes@1",
                ),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.split()
            if cancellation_containers:
                top = subprocess.run(
                    ("docker", "top", cancellation_containers[0], "-eo", "pid,args"),
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                if "grafy_core.runtime.plugin_guest" in top:
                    break
            if time.monotonic() >= cancellation_deadline:
                pytest.fail("Plugin guest child did not start before cancellation")
            await asyncio.sleep(0.05)
        cancellation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancellation
        cancelled_containers = subprocess.run(
            (
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=io.grafy.plugin.scope={scope.value}",
                "--filter",
                "label=io.grafy.plugin.release=notes@1",
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert cancelled_containers == []

        log_limited_invoker = ArtifactBundlePluginInvoker(
            unit_of_work=artifact_unit_of_work,
            runner=runtime,
            limits=PluginInvocationLimits(max_log_bytes=1_024),
            scratch=runtime,
            storage=storage,
            bucket="runtime-test",
            storage_backend="local",
        )
        log_probe: PluginReleaseNode[
            PluginReleaseNodeConfig,
            NodeInput,
            NodeOutput,
        ] = PluginReleaseNode(release, probe_contract, log_limited_invoker)
        with pytest.raises(PluginInvocationError, match="internal_adapter_failure"):
            await log_probe.run(
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="runtime-log",
                ),
                log_probe.config_contract.model.model_validate(
                    {"mode": "log", "value": 32 * 1_024}
                ),
                log_probe.input_contract.model.model_validate({}),
            )

        memory_probe: PluginReleaseNode[
            PluginReleaseNodeConfig,
            NodeInput,
            NodeOutput,
        ] = PluginReleaseNode(release, probe_contract, invoker)
        with pytest.raises(PluginInvocationError, match="internal_adapter_failure"):
            await memory_probe.run(
                NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="runtime-memory",
                ),
                memory_probe.config_contract.model.model_validate(
                    {
                        "mode": "memory",
                        "value": profile.memory_bytes // (1_024 * 1_024) + 128,
                    }
                ),
                memory_probe.input_contract.model.model_validate({}),
            )
        assert not list((tmp_path / "scratch").rglob("grafy-plugin-invocation-*"))
    finally:
        await runtime.close_scope(scope)
        reset_plugin_sandbox_scope(token)
    try:
        remaining = subprocess.run(
            (
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=io.grafy.plugin.scope={scope.value}",
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert remaining == []
        assert list((tmp_path / "scratch").iterdir()) == []

        stale_runtime = DockerPluginRuntime(
            releases=ReleaseLookup(()),
            storage=storage,
            bucket="runtime-test",
            profile=profile,
            scratch_root=tmp_path / "stale-scratch",
        )
        await stale_runtime.recover_orphans()
        removed_image = subprocess.run(
            ("docker", "image", "inspect", f"sha256:{artifact.manifest_digest}"),
            check=False,
            capture_output=True,
        )
        assert removed_image.returncode != 0
    finally:
        subprocess.run(
            ("docker", "image", "rm", "-f", f"sha256:{artifact.manifest_digest}"),
            check=False,
            capture_output=True,
        )
