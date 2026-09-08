from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginRelease,
    PluginReleaseIdentity,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginExecutionPolicy,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationReason,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.plugin_invocation import PluginInvocationRequest
from grafy_core.runtime.plugin_protocol import (
    PluginFailureCode,
    PluginInvocationEnvelope,
    PluginInvocationLimits,
    PluginInvocationRelease,
)

from grafy_api.plugins.profiles import runtime_profile
from grafy_api.plugins.runtime.artifacts import PluginGuestRunError
from grafy_api.plugins.runtime.docker import DockerPluginRuntime
from grafy_api.plugins.runtime.sandbox import (
    PluginSandboxScopeId,
    activate_plugin_sandbox_scope,
    reset_plugin_sandbox_scope,
)


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000992")


class _ReleaseLookup:
    def __init__(
        self,
        release: InstalledPluginRelease,
        revocation: PluginReleaseRevocation | None = None,
    ) -> None:
        self._release = release
        self._revocation = revocation

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None:
        release = self._release
        if (
            workspace_id == WORKSPACE_ID
            and scope is release.scope
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
        revocation = self._revocation
        if (
            revocation is not None
            and revocation.workspace_id == workspace_id
            and revocation.slug == slug
            and revocation.revision == revision
        ):
            return revocation
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
        artifact = self._release.runtime_artifact
        return [] if artifact is None else [artifact]


def test_native_capability_cannot_be_enabled_without_exact_pinned_profile(
    tmp_path: Path,
) -> None:
    release = _unsupported_release()
    runtime = DockerPluginRuntime(
        releases=_ReleaseLookup(release),
        storage=cast(FileStoragePort, object()),
        bucket="test",
        profile=runtime_profile("python-uv"),
        scratch_root=tmp_path / "scratch",
        supported_capabilities=frozenset(
            {
                PluginRuntimeCapability.NATIVE_GDAL,
                PluginRuntimeCapability.NATIVE_TESSERACT,
            }
        ),
    )

    assert PluginRuntimeCapability.NATIVE_GDAL not in (
        runtime.release_admission.supported_capabilities
    )
    assert PluginRuntimeCapability.NATIVE_TESSERACT not in (
        runtime.release_admission.supported_capabilities
    )

    native_runtime = DockerPluginRuntime(
        releases=_ReleaseLookup(release),
        storage=cast(FileStoragePort, object()),
        bucket="test",
        profile=runtime_profile(
            "python-uv-gdal",
            native_base_image="registry.example/grafy-python-gdal",
            native_base_image_digest="d" * 64,
        ),
        scratch_root=tmp_path / "native-scratch",
    )
    assert PluginRuntimeCapability.NATIVE_GDAL in (
        native_runtime.release_admission.supported_capabilities
    )


def _unsupported_release() -> InstalledPluginRelease:
    catalog = PluginCatalogManifest(
        slug="notes",
        title="Notes",
        nodes=(
            PluginNodeContract(
                operator_id="notes.noop",
                operator_version=1,
                title="No-op",
                description="No-op",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
                required_capabilities=(
                    PluginRuntimeCapability.NETWORK_EGRESS,
                ),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest(
        capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,)
    )
    artifact = PluginRuntimeArtifact(
        object_key="plugin-releases/notes/runtime/image.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/notes/source.tar.gz",
        source_digest="d" * 64,
        lock_digest="e" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=artifact.manifest_digest,
        runtime_artifact=artifact,
        published_by_user_id=WORKSPACE_ID,
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=WORKSPACE_ID,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=WORKSPACE_ID,
            installed_by_platform_actor=None,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revoked", "expected_reason"),
    [(False, "unsupported_capabilities"), (True, "revoked")],
)
async def test_docker_runtime_rechecks_release_admission_before_starting_guest(
    tmp_path: Path,
    revoked: bool,
    expected_reason: str,
) -> None:
    release = _unsupported_release()
    revocation = (
        PluginReleaseRevocation.from_release(
            release,
            reason=PluginReleaseRevocationReason.SECURITY,
            revoked_by_user_id=uuid4(),
        )
        if revoked
        else None
    )
    contract = release.catalog.nodes[0]
    request = PluginInvocationRequest(
        release=PluginReleaseIdentity.from_release(release),
        contract=contract,
        artifact_type_bindings={},
        config={},
        inputs={},
        workspace_id=WORKSPACE_ID,
        node_id="noop",
    )
    limits = PluginInvocationLimits()
    invocation_root = tmp_path / "invocation"
    invocation_root.mkdir()
    envelope = PluginInvocationEnvelope(
        invocation_id=uuid4(),
        execution_scope_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        node_id=request.node_id,
        release=PluginInvocationRelease(
            scope=release.scope,
            workspace_id=release.workspace_id,
            slug=release.slug,
            revision=release.revision,
            source_digest=release.source_digest,
            contract_digest=release.contract_digest,
            protocol_digest=release.protocol_digest,
            descriptor_digest=release.descriptor.digest,
        ),
        operator_id=contract.operator_id,
        operator_version=contract.operator_version,
        required_capabilities=contract.required_capabilities,
        config={},
        inputs=(),
        outputs=(),
        limits=limits,
    )
    (invocation_root / "invocation.json").write_bytes(envelope.canonical_json_bytes())
    runtime = DockerPluginRuntime(
        releases=_ReleaseLookup(release, revocation),
        storage=cast(FileStoragePort, object()),
        bucket="test",
        profile=runtime_profile("python-uv"),
        scratch_root=tmp_path / "scratch",
    )
    token = activate_plugin_sandbox_scope(PluginSandboxScopeId.new())
    try:
        with pytest.raises(PluginGuestRunError) as error:
            await runtime.run(invocation_root, limits, request)
    finally:
        reset_plugin_sandbox_scope(token)

    assert error.value.code is PluginFailureCode.CONTRACT_FAILURE
    assert expected_reason in str(error.value)
