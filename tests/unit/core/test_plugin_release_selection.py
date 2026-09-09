from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginRelease,
    PluginReleaseError,
    PluginReleaseScope,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_identity import PluginReleaseNamespace
from grafy_core.domain.plugin_selection import (
    PluginFamilyLifecycle,
    PluginReleaseSelection,
    PluginReleaseSelectionError,
)


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000941")


def _release(
    revision: int,
    *,
    scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    slug: str = "notes",
) -> InstalledPluginRelease:
    catalog = PluginCatalogManifest(
        slug=slug,
        title=slug.title(),
        nodes=(
            PluginNodeContract(
                operator_id=f"{slug}.run",
                operator_version=1,
                title="Run",
                description="Run",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest()
    release = PluginRelease(
        slug=slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/{slug}/{revision}.tar.gz",
        source_digest=f"{revision}" * 64,
        lock_digest="9" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
    )
    installation = PluginInstallation.from_release(
        release,
        namespace=PluginReleaseNamespace(
            scope=scope,
            workspace_id=(
                WORKSPACE_ID if scope is PluginReleaseScope.WORKSPACE else None
            ),
        ),
        execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
        installed_by_user_id=(
            WORKSPACE_ID if scope is PluginReleaseScope.WORKSPACE else None
        ),
        installed_by_platform_actor=(
            "test:system" if scope is PluginReleaseScope.SYSTEM else None
        ),
    )
    return InstalledPluginRelease(release=release, installation=installation)


def test_selection_moves_exact_pointer_without_mutating_release_facts() -> None:
    first = _release(1)
    second = _release(2)
    selection = PluginReleaseSelection.from_release(first)
    changed_at = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)

    selection.deprecate()
    selection.select(second, when=changed_at)

    assert selection.selected_release_id == second.release.id
    assert selection.selected_revision == 2
    assert selection.lifecycle is PluginFamilyLifecycle.DEPRECATED
    assert selection.generation == 3
    assert selection.updated_at == changed_at
    assert first.release.revision == 1
    assert second.release.revision == 2


def test_workspace_publication_can_reselect_and_restore_family_visibility() -> None:
    first = _release(1)
    second = _release(2)
    selection = PluginReleaseSelection.from_release(first)
    selection.withdraw()

    selection.select(second, publish=True)

    assert selection.selected_revision == 2
    assert selection.lifecycle is PluginFamilyLifecycle.PUBLISHED
    assert selection.allows_new_insertion is True


def test_selection_rejects_a_release_from_another_scoped_family() -> None:
    selection = PluginReleaseSelection.from_release(_release(1))

    with pytest.raises(PluginReleaseSelectionError, match="same scoped family"):
        selection.select(_release(1, scope=PluginReleaseScope.SYSTEM))
    with pytest.raises(PluginReleaseSelectionError, match="same scoped family"):
        selection.select(_release(1, slug="tables"))


def test_withdrawn_selection_cannot_transition_to_deprecated() -> None:
    selection = PluginReleaseSelection.from_release(_release(1))
    selection.withdraw()

    with pytest.raises(PluginReleaseSelectionError, match="cannot be deprecated"):
        selection.deprecate()


@pytest.mark.parametrize("mismatch", ["release_id", "slug", "revision"])
def test_installed_release_rejects_mismatched_installation(mismatch: str) -> None:
    installed = _release(1)
    installation = replace(installed.installation)
    if mismatch == "release_id":
        installation.release_id = UUID(int=123)
    elif mismatch == "slug":
        installation.slug = "other"
    else:
        installation.release_revision = 2
    with pytest.raises(PluginReleaseError, match="does not match"):
        InstalledPluginRelease(installed.release, installation)


def test_installed_release_requires_descriptor_digest() -> None:
    installed = _release(1)
    assert installed.descriptor_digest == installed.release.descriptor.digest
    installed.release.descriptor_digest = None
    with pytest.raises(PluginReleaseError, match="no descriptor digest"):
        _ = installed.descriptor_digest
