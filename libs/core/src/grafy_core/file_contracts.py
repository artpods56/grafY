"""Builtin file format artifact contracts and the deployment extension table.

The confirmation rule set is closed so ingest imports no format library:
``magic`` matches declared signatures, ``json`` requires a JSON object,
``json_document`` requires a JSON object or array, and ``none`` trusts the
extension alone. A magic signature agrees on a prefix, not a full parse; a
truncated or corrupt file fails later in the visible decode or import node.
"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from grafy_core.artifacts import (
    ArtifactConfirmationRule,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    MagicSegment,
    MagicSignature,
)


class ExtensionClaimCollisionError(ValueError):
    """Two artifact types in one deployment claim the same extension."""


def _magic(*signatures: tuple[tuple[int, bytes], ...]) -> ArtifactConfirmationRule:
    return ArtifactConfirmationRule(
        rule="magic",
        signatures=tuple(
            MagicSignature(
                segments=tuple(
                    MagicSegment(offset=offset, value=value)
                    for offset, value in signature
                )
            )
            for signature in signatures
        ),
    )


PNG_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.png", 1),
    title="PNG image",
    extensions=("png",),
    confirmation_rule=_magic(((0, b"\x89PNG\r\n\x1a\n"),)),
)

JPEG_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.jpeg", 1),
    title="JPEG image",
    extensions=("jpg", "jpeg"),
    confirmation_rule=_magic(((0, b"\xff\xd8\xff"),)),
)

TIFF_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.tiff", 1),
    title="TIFF image",
    extensions=("tif", "tiff"),
    confirmation_rule=_magic(
        ((0, b"II*\x00"),),
        ((0, b"MM\x00*"),),
    ),
)

WEBP_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.webp", 1),
    title="WebP image",
    extensions=("webp",),
    confirmation_rule=_magic(((0, b"RIFF"), (8, b"WEBP"))),
)

BMP_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.bmp", 1),
    title="BMP image",
    extensions=("bmp",),
    confirmation_rule=_magic(((0, b"BM"),)),
)

XLSX_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.xlsx", 1),
    title="Excel workbook",
    extensions=("xlsx",),
    confirmation_rule=_magic(((0, b"PK\x03\x04"),)),
)

GEOJSON_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.geojson", 1),
    title="GeoJSON document",
    extensions=("geojson",),
    confirmation_rule=ArtifactConfirmationRule(rule="json"),
)

JSON_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.json", 1),
    title="JSON document",
    extensions=("json",),
    confirmation_rule=ArtifactConfirmationRule(rule="json_document"),
)

CSV_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.csv", 1),
    title="CSV file",
    extensions=("csv",),
)

TXT_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.txt", 1),
    title="Text file",
    extensions=("txt",),
)

BLOB_FILE = ArtifactTypeSpec(
    key=ArtifactTypeKey("file.blob", 1),
    title="Binary blob",
)


BUILTIN_FILE_FORMATS: tuple[ArtifactTypeSpec, ...] = (
    PNG_FILE,
    JPEG_FILE,
    TIFF_FILE,
    WEBP_FILE,
    BMP_FILE,
    XLSX_FILE,
    GEOJSON_FILE,
    JSON_FILE,
    CSV_FILE,
    TXT_FILE,
    BLOB_FILE,
)


def build_extension_table(
    claims: Iterable[tuple[ArtifactTypeKey, tuple[str, ...]]],
) -> Mapping[str, ArtifactTypeKey]:
    """Build the deployment extension table, refusing any colliding claim."""

    table: dict[str, ArtifactTypeKey] = {}
    for key, extensions in claims:
        for extension in extensions:
            existing = table.get(extension)
            if existing is not None and existing != key:
                raise ExtensionClaimCollisionError(
                    f"Artifact types {existing.id}@{existing.schema_version} and "
                    f"{key.id}@{key.schema_version} both claim extension "
                    f"{extension!r}"
                )
            table[extension] = key
    return MappingProxyType(table)


__all__ = [
    "BLOB_FILE",
    "BMP_FILE",
    "BUILTIN_FILE_FORMATS",
    "CSV_FILE",
    "ExtensionClaimCollisionError",
    "GEOJSON_FILE",
    "JPEG_FILE",
    "JSON_FILE",
    "PNG_FILE",
    "TIFF_FILE",
    "TXT_FILE",
    "WEBP_FILE",
    "XLSX_FILE",
    "build_extension_table",
]
