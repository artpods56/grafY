"""Deployment-owned canonical artifact conversion implementations.

Canonical conversions are not Plugin release assets. Their exact key and version
identify deployment code, so any contract or implementation change requires a new
version. A snapshot test enforces that version discipline without making production
imports depend on source-file availability.
"""

from collections.abc import Mapping
from io import BytesIO
from types import MappingProxyType
from typing import Any, Final

from PIL import Image

from grafy_core.artifact_contracts import (
    INTEGER_VALUE,
    RASTER_IMAGE,
    TEXT_VALUE,
    RasterImageContent,
    RasterImageContentType,
)
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.file_contracts import (
    BMP_FILE,
    JPEG_FILE,
    PNG_FILE,
    TIFF_FILE,
    TXT_FILE,
    WEBP_FILE,
)


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


def _raster_conversion(
    content: bytes, content_type: RasterImageContentType, expected_format: str
) -> RasterImageContent:
    with Image.open(BytesIO(content)) as image:
        if image.format != expected_format:
            raise ValueError(f"Expected {expected_format} image, got {image.format}")
        image.verify()
    return RasterImageContent(content=content, content_type=content_type)


def _png_file_to_raster(content: bytes) -> RasterImageContent:
    return _raster_conversion(content, "image/png", "PNG")


PNG_FILE_TO_RASTER: Final = ArtifactConversion(
    key=ArtifactConversionKey("builtin.file.png_to_raster", 1),
    source=PNG_FILE.key,
    target=RASTER_IMAGE.key,
    source_type=bytes,
    target_type=RasterImageContent,
    title="As raster image",
    convert=_png_file_to_raster,
)


def _jpeg_file_to_raster(content: bytes) -> RasterImageContent:
    return _raster_conversion(content, "image/jpeg", "JPEG")


JPEG_FILE_TO_RASTER: Final = ArtifactConversion(
    key=ArtifactConversionKey("builtin.file.jpeg_to_raster", 1),
    source=JPEG_FILE.key,
    target=RASTER_IMAGE.key,
    source_type=bytes,
    target_type=RasterImageContent,
    title="As raster image",
    convert=_jpeg_file_to_raster,
)


def _webp_file_to_raster(content: bytes) -> RasterImageContent:
    return _raster_conversion(content, "image/webp", "WEBP")


WEBP_FILE_TO_RASTER: Final = ArtifactConversion(
    key=ArtifactConversionKey("builtin.file.webp_to_raster", 1),
    source=WEBP_FILE.key,
    target=RASTER_IMAGE.key,
    source_type=bytes,
    target_type=RasterImageContent,
    title="As raster image",
    convert=_webp_file_to_raster,
)


def _tiff_file_to_raster(content: bytes) -> RasterImageContent:
    return _raster_conversion(content, "image/tiff", "TIFF")


TIFF_FILE_TO_RASTER: Final = ArtifactConversion(
    key=ArtifactConversionKey("builtin.file.tiff_to_raster", 1),
    source=TIFF_FILE.key,
    target=RASTER_IMAGE.key,
    source_type=bytes,
    target_type=RasterImageContent,
    title="As raster image",
    convert=_tiff_file_to_raster,
)


def _bmp_file_to_raster(content: bytes) -> RasterImageContent:
    return _raster_conversion(content, "image/bmp", "BMP")


BMP_FILE_TO_RASTER: Final = ArtifactConversion(
    key=ArtifactConversionKey("builtin.file.bmp_to_raster", 1),
    source=BMP_FILE.key,
    target=RASTER_IMAGE.key,
    source_type=bytes,
    target_type=RasterImageContent,
    title="As raster image",
    convert=_bmp_file_to_raster,
)


CANONICAL_ARTIFACT_CONVERSIONS: Final = (
    INTEGER_TO_TEXT,
    TEXT_FILE_TO_TEXT,
    PNG_FILE_TO_RASTER,
    JPEG_FILE_TO_RASTER,
    WEBP_FILE_TO_RASTER,
    TIFF_FILE_TO_RASTER,
    BMP_FILE_TO_RASTER,
)


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
    "PNG_FILE_TO_RASTER",
    "JPEG_FILE_TO_RASTER",
    "WEBP_FILE_TO_RASTER",
    "TIFF_FILE_TO_RASTER",
    "BMP_FILE_TO_RASTER",
    "INTEGER_TO_TEXT",
    "TEXT_FILE_TO_TEXT",
]
