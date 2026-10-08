"""Real System Plugin sandbox and graph contract for Python presets."""

import asyncio
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
from typing import cast

import pytest

from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import PluginReleaseScope, plugin_contract_digest
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.plugin_invocation import PluginInvocationRequest
from grafy_core.runtime.plugin_protocol import PluginInvocationLimits
from grafy_storage import LocalFileObjectStore
from grafy_workbench.presets import PYTHON_PRESETS
from grafy_plugin_python.plugin import PYTHON

from grafy_api.execution.requests import RunEdgeRequest, RunNodeRequest, RunRequest
from grafy_api.plugins.profiles import runtime_profile
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.publication.source import PluginDirectoryPublisher
from grafy_api.plugins.runtime.docker import DockerPluginRuntime
from grafy_api.services.composition import build_workbench_components
from grafy_api.v1.models import (
    ArtifactTypeBindingModel,
    ArtifactTypeKeyResponse,
    PluginReleasePinModel,
)
from tests.support.identity import WORKSPACE_ID
from tests.support.system_plugins import (
    SelectedSystemReleaseLookup,
    build_explicit_plugin_registry,
    synthetic_system_release,
)


def _containers() -> list[str]:
    return subprocess.run(
        (
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=io.grafy.plugin.release=external.python@1",
        ),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()


@pytest.mark.asyncio
async def test_python_presets_equal_text_nodes_cache_and_clean_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        available = subprocess.run(
            ("docker", "info"), capture_output=True, timeout=10, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("local Docker daemon is unavailable")
    if available.returncode:
        pytest.skip("local Docker daemon is unavailable")
    repository = Path(__file__).resolve().parents[3]
    project = tmp_path / "python-plugin"
    shutil.copytree(
        repository / "plugins/python",
        project,
        ignore=shutil.ignore_patterns(".venv", "build", "*.egg-info", "__pycache__"),
    )
    verified = await asyncio.to_thread(
        PluginDirectoryPublisher((tmp_path,), runtime_profile="python-uv").verify,
        project,
        expected_slug="external.python",
        loader_target="grafy_plugin_python.plugin:PYTHON",
    )
    storage = LocalFileObjectStore(tmp_path / "objects")
    artifact = await PluginOciImageBuilder(
        storage, bucket="test", profile=runtime_profile("python-uv")
    ).build_and_store(candidate=verified)
    synthetic = synthetic_system_release(PYTHON)
    record = replace(
        synthetic.release,
        catalog=verified.catalog,
        contract_digest=plugin_contract_digest(verified.catalog),
        source_digest=sha256(verified.source_archive).hexdigest(),
        lock_digest=verified.lock_digest,
        loader_target=verified.loader_target,
        runtime_image_digest=artifact.manifest_digest,
        runtime_artifact=artifact,
        descriptor_digest=None,
    )
    release = InstalledPluginRelease(
        release=record,
        installation=replace(synthetic.installation, release_id=record.id),
    )
    lookup = SelectedSystemReleaseLookup((release,), ())
    sandbox = DockerPluginRuntime(
        releases=lookup,
        storage=storage,
        bucket="test",
        profile=runtime_profile("python-uv"),
        scratch_root=tmp_path / "scratch",
    )
    uow = InMemoryUnitOfWork()
    components = build_workbench_components(
        plugin_registry=build_explicit_plugin_registry(),
        workspace=tmp_path / "workbench",
        unit_of_work=uow,
        storage=storage,
        bucket="test",
        plugin_releases=cast(PluginReleaseService, lookup),
        plugin_runtime=sandbox,
    )
    presets = {preset.id: preset for preset in PYTHON_PRESETS}
    nodes = [
        RunNodeRequest(
            kind="builtin",
            id="source",
            operator_id="text.input",
            operator_version=1,
            config={"text": "first|second|first"},
        )
    ]
    for node_id, preset_id, params in (
        ("split", "split-text", {"separator": "|"}),
        ("replace", "replace-text", {"search": "first", "replacement": "changed"}),
        ("join", "join-text", {"separator": ","}),
    ):
        preset = presets[preset_id]
        nodes.append(
            RunNodeRequest(
                kind="plugin",
                id=node_id,
                operator_id="python.transform",
                operator_version=1,
                config={**preset.node_config(), "params": params},
                plugin_release=PluginReleasePinModel(
                    scope=PluginReleaseScope.SYSTEM, slug=PYTHON.slug, revision=1
                ),
                artifact_type_bindings=[
                    ArtifactTypeBindingModel(
                        variable=name,
                        artifact_type=ArtifactTypeKeyResponse(
                            id=port.artifact_type.id,
                            schema_version=port.artifact_type.schema_version,
                        ),
                    )
                    for name, port in (
                        ("input", preset.contract.input),
                        ("output", preset.contract.output),
                    )
                ],
            )
        )
    request = RunRequest(
        nodes=nodes,
        edges=[
            RunEdgeRequest(
                from_node="source", from_port="text", to_node="split", to_port="input"
            ),
            RunEdgeRequest(
                from_node="split",
                from_port="output",
                to_node="replace",
                to_port="input",
                collection_mode="map",
            ),
            RunEdgeRequest(
                from_node="replace", from_port="output", to_node="join", to_port="input"
            ),
        ],
    )
    assert components.plugin_invoker is not None
    original_run = sandbox.run
    observed_containers: list[tuple[str, ...]] = []

    async def observe_run(
        invocation_root: Path,
        limits: PluginInvocationLimits,
        invocation_request: PluginInvocationRequest,
    ) -> None:
        await original_run(invocation_root, limits, invocation_request)
        observed_containers.append(tuple(_containers()))

    monkeypatch.setattr(sandbox, "run", observe_run)
    before = set(_containers())
    try:
        first = await components.run_graph.run(WORKSPACE_ID, request)
        assert first.status == "succeeded", [
            (result.node_id, result.error) for result in first.node_results
        ]
        ref = first.outputs["join"]["output"]
        assert isinstance(ref, ArtifactRef)
        async with uow as entered:
            joined = await entered.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert joined is not None and joined.inline_payload == {
            "value": "changed,second,changed"
        }
        legacy = RunRequest(
            nodes=[
                nodes[0],
                RunNodeRequest(
                    kind="builtin",
                    id="split",
                    operator_id="text.split",
                    operator_version=1,
                    config={"separator": "|"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="replace",
                    operator_id="text.replace",
                    operator_version=1,
                    config={"search": "first", "replacement": "changed"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="join",
                    operator_id="text.join",
                    operator_version=1,
                    config={"separator": ","},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="split",
                    to_port="text",
                ),
                RunEdgeRequest(
                    from_node="split",
                    from_port="parts",
                    to_node="replace",
                    to_port="text",
                    collection_mode="map",
                ),
                RunEdgeRequest(
                    from_node="replace",
                    from_port="text",
                    to_node="join",
                    to_port="parts",
                ),
            ],
        )
        old = await components.run_graph.run(WORKSPACE_ID, legacy)
        assert old.status == "succeeded"
        old_ref = old.outputs["join"]["text"]
        assert isinstance(old_ref, ArtifactRef)
        async with uow as entered:
            old_joined = await entered.artifacts.get(WORKSPACE_ID, old_ref.artifact_id)
        assert old_joined is not None
        assert old_joined.inline_payload == joined.inline_payload
        assert len(observed_containers) == 5
        assert (
            len({container for group in observed_containers for container in group})
            == 1
        )
        assert set(_containers()) == before
        completed = components.plugin_invoker.diagnostics().total_invocations
        second = await components.run_graph.run(WORKSPACE_ID, request)
        assert second.status == "succeeded"
        for node_id, outputs in first.outputs.items():
            for port, value in outputs.items():
                repeated = second.outputs[node_id][port]
                if isinstance(value, ArtifactRefSequence):
                    assert isinstance(repeated, ArtifactRefSequence)
                    assert repeated.item_refs == value.item_refs
                else:
                    assert repeated == value, (
                        node_id,
                        repeated.model_dump(),
                        value.model_dump(),
                    )
        assert components.plugin_invoker.diagnostics().total_invocations == completed
        assert set(_containers()) == before

        assert components.python_apply is not None
        inspected = await components.python_apply.apply(
            workspace_id=WORKSPACE_ID,
            code=presets["replace-text"].code,
            scope=PluginReleaseScope.SYSTEM,
            slug=PYTHON.slug,
            revision=1,
        )
        assert inspected.contract is not None and not inspected.diagnostics
        network = await components.python_apply.apply(
            workspace_id=WORKSPACE_ID,
            code="import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=0.2)\ndef transform(text: str) -> str:\n    return text\n",
            scope=PluginReleaseScope.SYSTEM,
            slug=PYTHON.slug,
            revision=1,
        )
        assert network.contract is None
        assert network.diagnostics and network.diagnostics[0].line == 2
        assert set(_containers()) == before

        slow = request.model_copy(deep=True)
        code = "import time\ndef transform(text: str) -> list[str]:\n    time.sleep(60)\n    return [text]\n"
        slow.nodes[1].config.update(
            code=code,
            code_sha256=sha256(code.encode()).hexdigest(),
            params_schema=None,
            params={},
        )
        task = asyncio.create_task(components.run_graph.run(WORKSPACE_ID, slow))
        try:
            for _ in range(300):
                if set(_containers()) != before:
                    break
                await asyncio.sleep(0.1)
            else:
                pytest.fail("Python sandbox never started")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert set(_containers()) == before
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    finally:
        await sandbox.shutdown()
