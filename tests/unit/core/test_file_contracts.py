"""The builtin file format contract, its confirmation rules, and the table."""

from typing import cast

import pytest
from grafy_core.artifacts import (
    ArtifactConfirmationRule,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    ConfirmationRule,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
)
from grafy_core.file_contracts import (
    BUILTIN_FILE_FORMATS,
    ExtensionClaimCollisionError,
    build_extension_table,
)
from pydantic import ValidationError


def _spec(artifact_type_id: str) -> ArtifactTypeSpec:
    return next(
        spec for spec in BUILTIN_FILE_FORMATS if spec.key.id == artifact_type_id
    )


def _claims(*specs: ArtifactTypeSpec) -> list[tuple[ArtifactTypeKey, tuple[str, ...]]]:
    return [(spec.key, spec.extensions) for spec in specs]


def test_builtin_table_maps_every_claim_to_its_format_type() -> None:
    table = build_extension_table(_claims(*BUILTIN_FILE_FORMATS))

    assert table["json"] == ArtifactTypeKey("file.json", 1)
    assert table["geojson"] == ArtifactTypeKey("file.geojson", 1)
    assert table["tif"] == ArtifactTypeKey("file.tiff", 1)
    assert table["jpeg"] == ArtifactTypeKey("file.jpeg", 1)
    assert "blob" not in table


def test_extension_table_refuses_a_colliding_claim() -> None:
    with pytest.raises(ExtensionClaimCollisionError, match=r"file\.txt@1.*both claim"):
        build_extension_table(
            _claims(
                _spec("file.txt"),
                ArtifactTypeSpec(
                    key=ArtifactTypeKey("file.plain", 1),
                    title="Plain text",
                    extensions=("txt",),
                ),
            )
        )


def test_a_format_without_a_rule_still_resolves_by_extension() -> None:
    table = build_extension_table(_claims(*BUILTIN_FILE_FORMATS))

    assert table["csv"] == ArtifactTypeKey("file.csv", 1)
    assert _spec("file.csv").confirmation_rule.rule == "none"
    assert _spec("file.csv").confirmation_rule.confirms(b"\x00\x01\x02")


def test_json_document_confirms_objects_and_arrays_but_not_primitives() -> None:
    rule = _spec("file.json").confirmation_rule

    assert rule.rule == "json_document"
    assert rule.confirms(b'{"a": 1}')
    assert rule.confirms(b"[1, 2, 3]")
    assert not rule.confirms(b"17")
    assert not rule.confirms(b'"text"')
    assert not rule.confirms(b"not json")


def test_geojson_confirmation_stays_object_only() -> None:
    rule = _spec("file.geojson").confirmation_rule

    assert rule.rule == "json"
    assert rule.confirms(b"{}")
    assert not rule.confirms(b"[]")


def test_magic_confirmation_matches_the_declared_signatures() -> None:
    png = _spec("file.png").confirmation_rule
    assert png.confirms(b"\x89PNG\r\n\x1a\nrest")
    assert not png.confirms(b"\x89PNG")

    webp = _spec("file.webp").confirmation_rule
    assert webp.confirms(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    assert not webp.confirms(b"RIFX\x00\x00\x00\x00WEBP")

    tiff = _spec("file.tiff").confirmation_rule
    assert tiff.confirms(b"II*\x00")
    assert tiff.confirms(b"MM\x00*")
    assert not tiff.confirms(b"II\x2a\x01")


def test_extension_claim_validation_refuses_invalid_specs() -> None:
    with pytest.raises(ValueError, match="only file.* types claim extensions"):
        ArtifactTypeSpec(
            key=ArtifactTypeKey("scalar.text", 1),
            title="Text",
            extensions=("txt",),
        )
    with pytest.raises(ValueError, match="file.blob may not declare extensions"):
        ArtifactTypeSpec(
            key=ArtifactTypeKey("file.blob", 1),
            title="Blob",
            extensions=("blob",),
        )
    with pytest.raises(ValueError, match="must be unique"):
        ArtifactTypeSpec(
            key=ArtifactTypeKey("file.png", 1),
            title="PNG",
            extensions=("png", "png"),
        )
    with pytest.raises(ValueError, match="lowercase"):
        ArtifactTypeSpec(
            key=ArtifactTypeKey("file.png", 1),
            title="PNG",
            extensions=("PNG",),
        )


def test_release_contract_mirrors_and_round_trips_the_confirmation_rule() -> None:
    contract = PluginArtifactTypeContract.from_spec(_spec("file.png"))

    assert contract.extensions == ("png",)
    assert contract.confirmation_rule.rule == "magic"
    assert [segment.value for segment in contract.confirmation_rule.signatures[0].segments] == [
        "89504e470d0a1a0a"
    ]
    assert contract.confirmation_rule.to_rule() == _spec("file.png").confirmation_rule

    with pytest.raises(ValidationError, match="only file.* types claim extensions"):
        PluginArtifactTypeContract(
            key=PluginArtifactTypeKey(id="scalar.text", schema_version=1),
            title="Text",
            extensions=("txt",),
        )


def test_confirmation_rule_requires_a_signature_only_for_magic() -> None:
    with pytest.raises(ValueError, match="requires a signature"):
        ArtifactConfirmationRule(rule="magic")
    with pytest.raises(ValueError, match="Only a magic"):
        ArtifactConfirmationRule(
            rule=cast(ConfirmationRule, "json"),
            signatures=_spec("file.png").confirmation_rule.signatures,
        )
