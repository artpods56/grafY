"""Admission contracts for retained historical release-runtime helpers."""

from uuid import UUID

import pytest
from grafy_api.plugins.runtime.admission import (
    ReleaseExecutionAdmission,
    ReleaseExecutionRejection,
    ReleaseExecutionRoute,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginPortContract,
    PluginPortDirection,
    PluginRelease,
    PluginReleaseNamespace,
    PluginRuntimeArtifact,
    PluginSecretInputContract,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationReason,
)
from grafy_core.domain.plugin_selection import (
    PluginFamilyLifecycle,
    PluginReleaseSelection,
)
from grafy_core.nodes import PortShape
from grafy_workbench.text import TEXT as TEXT_PLUGIN


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000871")
TEXT = PluginArtifactTypeKey(id="scalar.text", schema_version=1)
HOST_LOADER_TARGET = "grafy_workbench.text.plugin:TEXT"
HOST_BUILD_DIGEST = "f" * 64
_RELEASE_ADMISSION = ReleaseExecutionAdmission(
    isolated_adapter_available=True,
    runtime_profile="python-uv",
)


def _text_port(
    name: str,
    direction: PluginPortDirection,
) -> PluginPortContract:
    return PluginPortContract(
        name=name,
        title=name.title(),
        direction=direction,
        artifact_type=TEXT,
        shape=PortShape.ONE,
        accepted_shapes=(PortShape.ONE,),
    )


def _echo_contract(operator_version: int = 1) -> PluginNodeContract:
    return PluginNodeContract(
        operator_id="notes.echo",
        operator_version=operator_version,
        title="Echo",
        description="Echoes one text reference.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(_text_port("text", "input"),),
        outputs=(_text_port("text", "output"),),
    )


def _release(
    revision: int,
    nodes: tuple[PluginNodeContract, ...] = (_echo_contract(),),
    *,
    executable: bool = True,
    declared_capabilities: tuple[PluginRuntimeCapability, ...] = (),
    execution_policy: PluginExecutionPolicy = PluginExecutionPolicy.ISOLATED_ONLY,
    artifact_types: tuple[PluginArtifactTypeContract, ...] = (),
    artifact_type_dependencies: tuple[PluginArtifactTypeContract, ...] | None = None,
) -> InstalledPluginRelease:
    dependencies = artifact_type_dependencies
    if dependencies is None:
        dependencies = tuple(
            PluginArtifactTypeContract.from_spec(spec)
            for spec in TEXT_PLUGIN.artifact_types
        )
    catalog = PluginCatalogManifest(
        slug="notes",
        title="Notes",
        artifact_types=artifact_types,
        artifact_type_dependencies=dependencies,
        nodes=nodes,
    )
    capabilities = PluginCapabilityManifest(capabilities=declared_capabilities)
    runtime_artifact = (
        PluginRuntimeArtifact(
            object_key=f"plugin-releases/notes/runtime/r{revision}.oci.tar",
            archive_digest="a" * 64,
            manifest_digest="b" * 64,
            config_digest="c" * 64,
        )
        if executable
        else None
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/notes/r{revision}.tar.gz",
        source_digest=f"{revision}" * 64,
        lock_digest="9" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=(
            runtime_artifact.manifest_digest if runtime_artifact is not None else None
        ),
        runtime_artifact=runtime_artifact,
        published_by_platform_actor="test:system",
    )
    installation = PluginInstallation.from_release(
        release,
        namespace=PluginReleaseNamespace(),
        execution_policy=execution_policy,
        installed_by_platform_actor="test:system",
    )
    return InstalledPluginRelease(release=release, installation=installation)


def _host_text_release(revision: int) -> InstalledPluginRelease:
    catalog = PluginCatalogManifest.from_plugin(TEXT_PLUGIN)
    capabilities = PluginCapabilityManifest()
    runtime_artifact = PluginRuntimeArtifact(
        object_key=f"plugin-releases/system/builtin.text/runtime/r{revision}.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/system/builtin.text/r{revision}.tar.gz",
        source_digest=f"{revision}" * 64,
        lock_digest="9" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_workbench.text.plugin:TEXT",
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor="test:system",
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(),
            execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
            installed_by_platform_actor="test:system",
        ),
    )


def test_an_unselected_release_never_selects_host_route() -> None:
    admission = ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile="python-uv",
    )
    isolated_system = _release(1)
    isolated_selection = PluginReleaseSelection.from_release(isolated_system)

    assert (
        admission.decide(isolated_system, selection=isolated_selection)
        is ReleaseExecutionRoute.ISOLATED
    )
    assert admission.decide(isolated_system) is ReleaseExecutionRoute.ISOLATED


def test_non_published_system_selection_never_selects_host_route() -> None:
    release = _host_text_release(1)
    selection = PluginReleaseSelection.from_release(release)
    selection.lifecycle = PluginFamilyLifecycle.DEPRECATED

    assert (
        ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
        ).decide(release, selection=selection)
        is ReleaseExecutionRoute.ISOLATED
    )


@pytest.mark.parametrize(
    ("execution_policy", "revoked"),
    [
        (PluginExecutionPolicy.ISOLATED_ONLY, False),
        (PluginExecutionPolicy.HOST_ELIGIBLE, False),
        (PluginExecutionPolicy.ISOLATED_ONLY, True),
        (PluginExecutionPolicy.HOST_ELIGIBLE, True),
    ],
)
@pytest.mark.parametrize("runtime_available", [False, True])
def test_historical_policy_and_revocation_cannot_bypass_isolation(
    execution_policy: PluginExecutionPolicy,
    runtime_available: bool,
    revoked: bool,
) -> None:
    release = _release(1, execution_policy=execution_policy)
    revocation = (
        PluginReleaseRevocation.from_release(
            release,
            reason=PluginReleaseRevocationReason.SECURITY,
            revoked_by_platform_actor="test:system",
        )
        if revoked
        else None
    )
    decision = ReleaseExecutionAdmission(
        isolated_adapter_available=runtime_available,
        runtime_profile="python-uv",
    ).decide(release, revocation=revocation)

    if revoked:
        assert isinstance(decision, ReleaseExecutionRejection)
        assert decision.reason == "revoked"
    elif not runtime_available:
        assert isinstance(decision, ReleaseExecutionRejection)
        assert decision.reason == "plugin_runtime_unavailable"
    else:
        assert decision is ReleaseExecutionRoute.ISOLATED


def test_admission_requires_an_exact_artifact_bundle_adapter() -> None:
    decision = ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile="python-uv",
        supported_bundle_adapters=frozenset({("table-bundle", 1)}),
    ).decide(_release(1))

    assert isinstance(decision, ReleaseExecutionRejection)
    assert decision.reason == "unsupported_artifact_type"
    assert "inline-json@1" in decision.detail


def test_admission_enables_only_wired_bundle_adapters_by_default() -> None:
    assert _RELEASE_ADMISSION.supported_bundle_adapters == frozenset(
        {
            ("binary-file", 1),
            ("inline-json", 1),
            ("object-set", 1),
            ("table-bundle", 1),
        }
    )


def test_admission_uses_the_selected_node_capability_profile() -> None:
    artifact_query = _echo_contract().model_copy(
        update={
            "operator_id": "sql.artifacts.query",
            "required_capabilities": (PluginRuntimeCapability.UNTRUSTED_SQL,),
        }
    )
    postgresql = _echo_contract().model_copy(
        update={
            "operator_id": "sql.postgresql.execute",
            "secret_inputs": (
                PluginSecretInputContract(
                    name="database_url",
                    title="Database URL",
                    config_dependencies=("secret_name",),
                ),
            ),
            "required_capabilities": (
                PluginRuntimeCapability.NODE_SECRETS,
                PluginRuntimeCapability.POSTGRESQL_EGRESS,
                PluginRuntimeCapability.UNTRUSTED_SQL,
            ),
        }
    )
    release = _release(
        1,
        nodes=(artifact_query, postgresql),
        declared_capabilities=(
            PluginRuntimeCapability.NODE_SECRETS,
            PluginRuntimeCapability.POSTGRESQL_EGRESS,
            PluginRuntimeCapability.UNTRUSTED_SQL,
        ),
    )
    admission = ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile="python-uv",
        supported_capabilities=frozenset({PluginRuntimeCapability.UNTRUSTED_SQL}),
    )

    assert (
        admission.decide(release, node_contract=artifact_query)
        is ReleaseExecutionRoute.ISOLATED
    )
    postgresql_decision = admission.decide(
        release,
        node_contract=postgresql,
    )
    assert isinstance(postgresql_decision, ReleaseExecutionRejection)
    assert postgresql_decision.reason == "unsupported_capabilities"
    assert "postgresql.egress" in postgresql_decision.detail


def test_admission_rejects_an_exact_revocation_with_the_stable_reason() -> None:
    release = _release(1)
    revocation = PluginReleaseRevocation.from_release(
        release,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_platform_actor="test:system",
    )

    decision = _RELEASE_ADMISSION.decide(release, revocation=revocation)

    assert isinstance(decision, ReleaseExecutionRejection)
    assert decision.reason == "revoked"
    assert "security" in decision.detail
