"""Deployment-owned canonical artifact conversion implementations.

Canonical conversions are not Plugin release assets. Their exact key and version
identify deployment code, so any contract or implementation change requires a new
version. A snapshot test enforces that version discipline without making production
imports depend on source-file availability.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.file_contracts import TXT_FILE


type CanonicalArtifactConversionMap = Mapping[
    ArtifactConversionKey,
    ArtifactConversion[Any, Any],
]


def _integer_to_text(value: int) -> str:
    return str(value)


INTEGER_TO_TEXT: Final = ArtifactConversion(
    key=ArtifactConversionKey("builtin.scalar.integer_to_text", 1),
    source=INTEGER_VALUE.key,
    target=TEXT_VALUE.key,
    source_type=int,
    target_type=str,
    title="As text",
    convert=_integer_to_text,
)


def _text_file_to_text(content: bytes) -> str:
    # utf-8-sig so a BOM written by Windows editors does not leak into the text.
    return content.decode("utf-8-sig")


TEXT_FILE_TO_TEXT: Final = ArtifactConversion(
    key=ArtifactConversionKey("builtin.file.txt_to_text", 1),
    source=TXT_FILE.key,
    target=TEXT_VALUE.key,
    source_type=bytes,
    target_type=str,
    title="As text",
    convert=_text_file_to_text,
)


CANONICAL_ARTIFACT_CONVERSIONS: Final = (INTEGER_TO_TEXT, TEXT_FILE_TO_TEXT)


def _canonical_conversions_by_key() -> CanonicalArtifactConversionMap:
    conversions: dict[
        ArtifactConversionKey,
        ArtifactConversion[Any, Any],
    ] = {}
    for conversion in CANONICAL_ARTIFACT_CONVERSIONS:
        if conversion.key in conversions:
            raise RuntimeError(
                f"Duplicate canonical artifact conversion {conversion.key.id}@"
                f"{conversion.key.version}"
            )
        conversions[conversion.key] = conversion
    return MappingProxyType(conversions)


CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY: Final = _canonical_conversions_by_key()


__all__ = [
    "CANONICAL_ARTIFACT_CONVERSIONS",
    "CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY",
    "CanonicalArtifactConversionMap",
    "INTEGER_TO_TEXT",
    "TEXT_FILE_TO_TEXT",
]
