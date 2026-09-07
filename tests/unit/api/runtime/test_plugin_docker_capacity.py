import asyncio
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginRelease,
    PluginReleaseScope,
    PluginRuntimeArtifact,
)
from grafy_core.ports.storage import FileStoragePort

from grafy_api.plugin_egress import PluginEgressDestination
from grafy_api.plugins.profiles import runtime_profile
from grafy_api.v1.routes.executions.runtime.plugin_docker import (
    DockerPluginRuntime,
    DockerPluginRuntimeError,
    PluginRuntimeReleaseLookup,
    _Sandbox,  # pyright: ignore[reportPrivateUsage]
    _SandboxKey,  # pyright: ignore[reportPrivateUsage]
)
from grafy_api.v1.routes.executions.runtime.plugin_sandbox import (
    PluginSandboxScopeId,
)


def _key(
    scope_id: PluginSandboxScopeId,
    revision: int,
    required_capabilities: tuple[PluginRuntimeCapability, ...] = (),
) -> _SandboxKey:
    workspace_id = UUID("00000000-0000-4000-8000-000000000991")
    return _SandboxKey(
        scope_id=scope_id,
        workspace_id=workspace_id,
        release_scope=PluginReleaseScope.WORKSPACE,
        release_workspace_id=workspace_id,
        release_slug="notes",
        release_revision=revision,
        source_digest=f"{revision:064x}",
        descriptor_digest=f"{revision + 16:064x}",
        required_capabilities=required_capabilities,
    )


def _runtime(tmp_path: Path) -> DockerPluginRuntime:
    return DockerPluginRuntime(
        releases=cast(PluginRuntimeReleaseLookup, object()),
        storage=cast(FileStoragePort, object()),
        bucket="test",
        profile=runtime_profile("python-uv"),
        scratch_root=tmp_path,
        max_live_sandboxes=1,
        max_distinct_releases_per_scope=1,
    )


@pytest.mark.asyncio
async def test_live_sandbox_capacity_waits_without_holding_runtime_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    created: list[_SandboxKey] = []

    async def ensure_image(
        release: PluginRelease,
        artifact: PluginRuntimeArtifact,
    ) -> None:
        del release, artifact

    async def create_container(
        key: _SandboxKey,
        artifact: PluginRuntimeArtifact,
        scratch_root: Path,
        **_kwargs: object,
    ) -> _Sandbox:
        del artifact
        created.append(key)
        return _Sandbox(
            key=key,
            container_id=f"container-{key.release_revision}",
            scratch_root=scratch_root,
        )

    async def remove_container(container_id: str) -> None:
        del container_id

    monkeypatch.setattr(runtime, "_ensure_image", ensure_image)
    monkeypatch.setattr(runtime, "_create_container", create_container)
    monkeypatch.setattr(runtime, "_remove_container", remove_container)
    release = cast(PluginRelease, object())
    artifact = cast(PluginRuntimeArtifact, object())
    first_scope = PluginSandboxScopeId.new()
    second_scope = PluginSandboxScopeId.new()

    await runtime._sandbox_for(  # pyright: ignore[reportPrivateUsage]
        _key(first_scope, 1),
        release,
        artifact,
        tmp_path,
    )
    waiting = asyncio.create_task(
        runtime._sandbox_for(  # pyright: ignore[reportPrivateUsage]
            _key(second_scope, 2),
            release,
            artifact,
            tmp_path,
        )
    )
    await asyncio.sleep(0)
    assert waiting.done() is False
    waiting_diagnostics = await runtime.diagnostics()
    assert waiting_diagnostics.max_live_sandboxes == 1
    assert waiting_diagnostics.live_sandboxes == 1
    assert waiting_diagnostics.waiting_sandbox_requests == 1

    await runtime.close_scope(first_scope)
    await waiting

    assert [key.scope_id for key in created] == [first_scope, second_scope]
    await runtime.close_scope(second_scope)
    terminal_diagnostics = await runtime.diagnostics()
    assert terminal_diagnostics.live_sandboxes == 0
    assert terminal_diagnostics.waiting_sandbox_requests == 0


@pytest.mark.asyncio
async def test_sandbox_identity_includes_the_effective_node_capability_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DockerPluginRuntime(
        releases=cast(PluginRuntimeReleaseLookup, object()),
        storage=cast(FileStoragePort, object()),
        bucket="test",
        profile=runtime_profile("python-uv"),
        scratch_root=tmp_path,
        max_live_sandboxes=2,
        max_distinct_releases_per_scope=2,
    )
    created: list[_SandboxKey] = []

    async def ensure_image(
        release: PluginRelease,
        artifact: PluginRuntimeArtifact,
    ) -> None:
        del release, artifact

    async def create_container(
        key: _SandboxKey,
        artifact: PluginRuntimeArtifact,
        scratch_root: Path,
        **_kwargs: object,
    ) -> _Sandbox:
        del artifact
        created.append(key)
        return _Sandbox(
            key=key,
            container_id=f"container-{len(created)}",
            scratch_root=scratch_root,
        )

    async def remove_container(container_id: str) -> None:
        del container_id

    monkeypatch.setattr(runtime, "_ensure_image", ensure_image)
    monkeypatch.setattr(runtime, "_create_container", create_container)
    monkeypatch.setattr(runtime, "_remove_container", remove_container)
    scope = PluginSandboxScopeId.new()
    release = cast(PluginRelease, object())
    artifact = cast(PluginRuntimeArtifact, object())

    await runtime._sandbox_for(  # pyright: ignore[reportPrivateUsage]
        _key(scope, 1),
        release,
        artifact,
        tmp_path,
    )
    await runtime._sandbox_for(  # pyright: ignore[reportPrivateUsage]
        _key(scope, 1, (PluginRuntimeCapability.UNTRUSTED_SQL,)),
        release,
        artifact,
        tmp_path,
    )

    assert [key.required_capabilities for key in created] == [
        (),
        (PluginRuntimeCapability.UNTRUSTED_SQL,),
    ]
    await runtime.close_scope(scope)


@pytest.mark.asyncio
async def test_one_execution_cannot_deadlock_on_excess_distinct_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)

    async def ensure_image(
        release: PluginRelease,
        artifact: PluginRuntimeArtifact,
    ) -> None:
        del release, artifact

    async def create_container(
        key: _SandboxKey,
        artifact: PluginRuntimeArtifact,
        scratch_root: Path,
        **_kwargs: object,
    ) -> _Sandbox:
        del artifact
        return _Sandbox(
            key=key,
            container_id=f"container-{key.release_revision}",
            scratch_root=scratch_root,
        )

    async def remove_container(container_id: str) -> None:
        del container_id

    monkeypatch.setattr(runtime, "_ensure_image", ensure_image)
    monkeypatch.setattr(runtime, "_create_container", create_container)
    monkeypatch.setattr(runtime, "_remove_container", remove_container)
    release = cast(PluginRelease, object())
    artifact = cast(PluginRuntimeArtifact, object())
    scope = PluginSandboxScopeId.new()
    await runtime._sandbox_for(  # pyright: ignore[reportPrivateUsage]
        _key(scope, 1), release, artifact, tmp_path
    )

    with pytest.raises(
        DockerPluginRuntimeError,
        match="distinct Plugin release limit",
    ):
        await runtime._sandbox_for(  # pyright: ignore[reportPrivateUsage]
            _key(scope, 2), release, artifact, tmp_path
        )

    await runtime.close_scope(scope)


@pytest.mark.asyncio
async def test_origin_variants_use_the_variant_limit_not_the_release_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DockerPluginRuntime(
        releases=cast(PluginRuntimeReleaseLookup, object()),
        storage=cast(FileStoragePort, object()),
        bucket="test",
        profile=runtime_profile("python-uv"),
        scratch_root=tmp_path,
        max_live_sandboxes=2,
        max_distinct_releases_per_scope=2,
        max_sandbox_variants_per_scope=1,
    )

    async def ensure_image(
        release: PluginRelease,
        artifact: PluginRuntimeArtifact,
    ) -> None:
        del release, artifact

    async def create_container(
        key: _SandboxKey,
        artifact: PluginRuntimeArtifact,
        scratch_root: Path,
        **_kwargs: object,
    ) -> _Sandbox:
        del artifact
        return _Sandbox(
            key=key,
            container_id="variant-container",
            scratch_root=scratch_root,
        )

    async def remove_container(container_id: str) -> None:
        del container_id

    monkeypatch.setattr(runtime, "_ensure_image", ensure_image)
    monkeypatch.setattr(runtime, "_create_container", create_container)
    monkeypatch.setattr(runtime, "_remove_container", remove_container)
    release = cast(PluginRelease, object())
    artifact = cast(PluginRuntimeArtifact, object())
    scope = PluginSandboxScopeId.new()

    def variant_key(origin: str) -> _SandboxKey:
        base = _key(scope, 1, (PluginRuntimeCapability.NETWORK_EGRESS,))
        return replace(
            base,
            network_profile_digest="a" * 64,
            http_destinations=(PluginEgressDestination.parse(origin),),
        )

    await runtime._sandbox_for(  # pyright: ignore[reportPrivateUsage]
        variant_key("https://one.example.com:443"),
        release,
        artifact,
        tmp_path,
    )

    with pytest.raises(
        DockerPluginRuntimeError,
        match="sandbox variant limit",
    ):
        await runtime._sandbox_for(  # pyright: ignore[reportPrivateUsage]
            variant_key("https://two.example.com:443"),
            release,
            artifact,
            tmp_path,
        )

    diagnostics = await runtime.diagnostics()
    assert diagnostics.max_sandbox_variants_per_execution == 1
    await runtime.close_scope(scope)
