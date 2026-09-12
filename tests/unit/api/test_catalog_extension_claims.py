"""The deployment extension table refuses collisions and confirms by rule."""

from uuid import UUID

import pytest
from grafy_api.catalog import CatalogSnapshot
from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.plugins import Plugin, PluginRegistry

WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000041")


def _snapshot(registry: PluginRegistry) -> CatalogSnapshot:
    return CatalogSnapshot.from_registry(registry, [], [], workspace_id=WORKSPACE_ID)


def _contract(snapshot: CatalogSnapshot, artifact_type_id: str):
    return next(
        contract
        for contract in snapshot.artifact_contracts
        if contract.key.id == artifact_type_id
    )


def test_colliding_extension_claim_refuses_the_installation() -> None:
    colliding = Plugin(slug="collision", title="Collision")
    colliding.register_artifact_type(
        ArtifactTypeSpec(
            key=ArtifactTypeKey("file.plain", 1),
            title="Plain file",
            extensions=("txt",),
        )
    )
    registry = PluginRegistry()
    registry.install(colliding)
    registry.freeze()

    with pytest.raises(
        ValueError,
        match=r"file\.txt@1 and file\.plain@1 both claim extension 'txt'",
    ):
        _snapshot(registry)


def test_deployment_table_resolves_json_and_confirms_documents_only() -> None:
    snapshot = _snapshot(PluginRegistry())

    assert snapshot.extension_claims["json"] == ArtifactTypeKey("file.json", 1)
    assert snapshot.extension_claims["geojson"] == ArtifactTypeKey("file.geojson", 1)

    rule = _contract(snapshot, "file.json").confirmation_rule.to_rule()
    assert rule.confirms(b"[1, 2, 3]")
    assert not rule.confirms(b"17")


def test_deployment_table_resolves_a_rule_less_format_by_extension() -> None:
    snapshot = _snapshot(PluginRegistry())

    assert snapshot.extension_claims["csv"] == ArtifactTypeKey("file.csv", 1)
    assert _contract(snapshot, "file.csv").confirmation_rule.rule == "none"
