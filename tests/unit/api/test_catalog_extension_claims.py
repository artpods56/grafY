"""The catalog's deployment extension table: who owns each upload extension."""

import pytest

from grafy_api.catalog import CatalogSnapshot
from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.file_contracts import ExtensionClaimCollisionError
from grafy_core.plugins import Plugin, PluginRegistry


def _spec(artifact_type_id: str, extensions: tuple[str, ...]) -> ArtifactTypeSpec:
    return ArtifactTypeSpec(
        key=ArtifactTypeKey(artifact_type_id, 1),
        title=f"{artifact_type_id} format",
        extensions=extensions,
    )


def _registry_with(*claims: tuple[str, tuple[str, ...]]) -> PluginRegistry:
    registry = PluginRegistry()
    for index, (artifact_type_id, extensions) in enumerate(claims):
        plugin = Plugin(slug=f"test.formats{index}", title=f"Test formats {index}")
        plugin.register_artifact_type(_spec(artifact_type_id, extensions))
        registry.install(plugin)
    registry.freeze()
    return registry


def _snapshot(registry: PluginRegistry | None = None) -> CatalogSnapshot:
    return CatalogSnapshot.from_registry(registry or PluginRegistry())


def _spec_for(snapshot: CatalogSnapshot, artifact_type_id: str) -> ArtifactTypeSpec:
    return next(spec for spec in snapshot.artifact_types if spec.key.id == artifact_type_id)


def test_deployment_table_resolves_json_and_declares_document_confirmation() -> None:
    snapshot = _snapshot()

    assert snapshot.extension_claims["json"] == ArtifactTypeKey("file.json", 1)
    assert snapshot.extension_claims["geojson"] == ArtifactTypeKey("file.geojson", 1)

    assert _spec_for(snapshot, "file.json").confirmation_rule.rule == "json_document"


def test_deployment_table_resolves_a_rule_less_format_by_extension() -> None:
    snapshot = _snapshot()

    assert snapshot.extension_claims["csv"] == ArtifactTypeKey("file.csv", 1)
    assert _spec_for(snapshot, "file.csv").confirmation_rule.rule == "none"


def test_an_installed_family_extends_the_deployment_table() -> None:
    snapshot = _snapshot(_registry_with(("file.laz", ("laz",))))

    assert snapshot.extension_claims["laz"] == ArtifactTypeKey("file.laz", 1)
    # The deployment-owned formats stay in the same table.
    assert snapshot.extension_claims["txt"] == ArtifactTypeKey("file.txt", 1)


def test_an_extension_already_claimed_by_an_installed_format_is_refused() -> None:
    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.txt@1 and file\.las@1 both claim extension 'txt'",
    ):
        _snapshot(_registry_with(("file.las", ("txt",))))


def test_two_installed_families_colliding_on_one_extension_are_refused() -> None:
    with pytest.raises(
        ExtensionClaimCollisionError,
        match=r"file\.laz@1 and file\.las@1 both claim extension 'las'",
    ):
        _snapshot(
            _registry_with(
                ("file.laz", ("las",)),
                ("file.las", ("las",)),
            )
        )
