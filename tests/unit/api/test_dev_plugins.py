from pathlib import Path

import pytest

from grafy_api.dev_plugins import (
    DevPluginError,
    load_dev_plugins,
    without_shadowed_releases,
)
from grafy_api.services.composition import build_workbench_components
from grafy_core.domain.plugin_catalog import PluginCatalogRelease
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginExecutionPolicy,
    plugin_contract_digest,
    plugin_protocol_digest,
    plugin_profile_digest,
)
from grafy_plugin_image import IMAGES
from grafy_plugin_mistral import MISTRAL
from grafy_shared.config import PluginsConfig
from grafy_workbench.catalog import BUILTIN_FAMILIES, build_builtin_registry
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID


def test_load_slug_and_explicit_target() -> None:
    assert load_dev_plugins(
        ("external.image", "grafy_plugin_mistral.plugin:MISTRAL")
    ) == (IMAGES, MISTRAL)


def test_explicit_target_does_not_read_inventory(tmp_path: Path) -> None:
    assert load_dev_plugins(
        ("grafy_plugin_mistral.plugin:MISTRAL",), inventory_path=tmp_path / "missing"
    ) == (MISTRAL,)


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (("unknown.slug",), "Unknown dev Plugin slug.*known slugs:.*external.image"),
        (
            ("missing_dev_plugin_module:PLUGIN",),
            "Cannot import dev Plugin.*uv sync --all-extras",
        ),
        (("grafy_plugin_image:MISSING",), "has no attribute 'MISSING'"),
        (("grafy_plugin_image:__name__",), "must be a Plugin, got str"),
        (
            ("external.image", "external.image"),
            "Duplicate dev Plugin slug 'external.image'",
        ),
        (("external.image", "grafy_plugin_image:IMAGES"), "Duplicate dev Plugin slug"),
        (("grafy_plugin_image:",), "expected module:attribute"),
    ],
)
def test_loader_errors(entries: tuple[str, ...], message: str) -> None:
    with pytest.raises(DevPluginError, match=message):
        _ = load_dev_plugins(entries)


def test_dev_plugins_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAFY_DEV_PLUGINS", '["external.image"]')
    assert PluginsConfig().dev_plugins == ("external.image",)


def test_dev_artifact_handler_deduplication(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    registry = build_builtin_registry((*BUILTIN_FAMILIES, IMAGES, MISTRAL))
    with pytest.raises(
        ValueError, match="Output writer already registered for image.regions@1"
    ):
        _ = build_workbench_components(plugin_registry=registry, workspace=tmp_path)
    with caplog.at_level("INFO"):
        components = build_workbench_components(
            plugin_registry=registry,
            workspace=tmp_path,
            dedupe_artifact_handlers=True,
            dev_plugin_slugs=frozenset((IMAGES.slug, MISTRAL.slug)),
        )
    assert components.dev_plugin_slugs == frozenset((IMAGES.slug, MISTRAL.slug))
    assert "dev_plugin_duplicate_writer_dropped" in caplog.text


def test_without_shadowed_releases() -> None:
    entries: list[PluginCatalogRelease] = []
    for slug in ("external.image", "other"):
        catalog = PluginCatalogManifest(
            slug=slug,
            title=slug,
            nodes=(
                PluginNodeContract(
                    operator_id=f"{slug}.echo",
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
        )
        capabilities = PluginCapabilityManifest()
        release = PluginRelease(
            slug=slug,
            revision=1,
            catalog=catalog,
            contract_digest=plugin_contract_digest(catalog),
            capabilities=capabilities,
            capability_digest=capabilities.digest,
            protocol_digest=plugin_protocol_digest(),
            profile_digest=plugin_profile_digest("python-uv"),
            source_object_key=f"{slug}/source.tar.gz",
            source_digest="a" * 64,
            lock_digest="b" * 64,
            runtime_profile="python-uv",
            loader_target="test:PLUGIN",
        )
        installation = PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE, workspace_id=WORKSPACE_ID
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=TEST_USER_ID,
            installed_by_platform_actor=None,
        )
        installed = InstalledPluginRelease(release=release, installation=installation)
        entries.append(
            PluginCatalogRelease(
                installed, PluginReleaseSelection.from_release(installed), None
            )
        )
    assert without_shadowed_releases(entries, frozenset()) == entries
    filtered = without_shadowed_releases(
        entries, frozenset(("external.image", "absent"))
    )
    assert [entry.release.release.slug for entry in filtered] == ["other"]
    assert len(entries) == 2
