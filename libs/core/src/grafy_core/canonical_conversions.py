"""Deployment-owned canonical artifact conversions.

Canonical conversions are not plugin assets. The id and version name one
deployment implementation. A change to that implementation takes a new version.
These seven stay at version 1.
"""

from collections.abc import Mapping
from io import BytesIO
from types import MappingProxyType
from typing import Any, Final, cast

from PIL import Image

from grafy_core.artifact_contracts import (
    INTEGER_VALUE,
    TEXT_VALUE,
    IntegerValuePayload,
    TextValuePayload,
)
from grafy_core.conversions import ArtifactConversionKey, Conversion
from grafy_core.documents import (
    FILE_ARTIFACTS,
    RASTER_IMAGE_ARTIFACT,
    BmpFile,
    File,
    JpegFile,
    PngFile,
    RasterImage,
    TiffFile,
    TxtFile,
    WebpFile,
)
from grafy_core.runtime.artifact_values import Artifact, scalar_artifact


type CanonicalArtifactConversionMap = Mapping[
    ArtifactConversionKey,
    Conversion[Any, Any],
]

_READ_LIMIT = 256 * 1024 * 1024

_INTEGER = scalar_artifact(INTEGER_VALUE, int, IntegerValuePayload)
_TEXT = scalar_artifact(TEXT_VALUE, str, TextValuePayload)


def _file_declaration[T: File](value_type: type[T]) -> Artifact[T]:
    for artifact in FILE_ARTIFACTS:
        if artifact.value_type is value_type:
            return cast(Artifact[T], artifact)
    raise RuntimeError(f"No file declaration for {value_type.__name__}")


async def _file_bytes(handle: File) -> bytes:
    limit = handle.byte_size if handle.byte_size is not None else _READ_LIMIT
    return await handle.read(max_bytes=limit)


async def _integer_to_text(value: int) -> str:
    return str(value)


INTEGER_TO_TEXT: Final = Conversion(
    id="builtin.scalar.integer_to_text",
    version=1,
    title="As text",
    source=_INTEGER,
    target=_TEXT,
    convert=_integer_to_text,
)


async def _text_file_to_text(text_file: TxtFile) -> str:
    # utf-8-sig so a BOM written by Windows editors does not leak into the text.
    content = await _file_bytes(text_file)
    return content.decode("utf-8-sig")


TEXT_FILE_TO_TEXT: Final = Conversion(
    id="builtin.file.txt_to_text",
    version=1,
    title="As text",
    source=_file_declaration(TxtFile),
    target=_TEXT,
    convert=_text_file_to_text,
)


async def _image_file_to_raster(image_file: File, content_type: str) -> RasterImage:
    expected = {
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/webp": "WEBP",
        "image/tiff": "TIFF",
        "image/bmp": "BMP",
    }[content_type]
    content = await _file_bytes(image_file)
    with Image.open(BytesIO(content)) as image:
        if image.format != expected:
            raise ValueError(f"Expected {expected} image, got {image.format}")
        image.verify()
    return RasterImage.from_content(
        content,
        content_type=content_type,
        filename=image_file.filename,
    )


async def _png_file_to_raster(image_file: PngFile) -> RasterImage:
    return await _image_file_to_raster(image_file, PngFile.media_type)


async def _jpeg_file_to_raster(image_file: JpegFile) -> RasterImage:
    return await _image_file_to_raster(image_file, JpegFile.media_type)


async def _webp_file_to_raster(image_file: WebpFile) -> RasterImage:
    return await _image_file_to_raster(image_file, WebpFile.media_type)


async def _tiff_file_to_raster(image_file: TiffFile) -> RasterImage:
    return await _image_file_to_raster(image_file, TiffFile.media_type)


async def _bmp_file_to_raster(image_file: BmpFile) -> RasterImage:
    return await _image_file_to_raster(image_file, BmpFile.media_type)


PNG_FILE_TO_RASTER: Final = Conversion(
    id="builtin.file.png_to_raster",
    version=1,
    title="As raster image",
    source=_file_declaration(PngFile),
    target=RASTER_IMAGE_ARTIFACT,
    convert=_png_file_to_raster,
)
JPEG_FILE_TO_RASTER: Final = Conversion(
    id="builtin.file.jpeg_to_raster",
    version=1,
    title="As raster image",
    source=_file_declaration(JpegFile),
    target=RASTER_IMAGE_ARTIFACT,
    convert=_jpeg_file_to_raster,
)
WEBP_FILE_TO_RASTER: Final = Conversion(
    id="builtin.file.webp_to_raster",
    version=1,
    title="As raster image",
    source=_file_declaration(WebpFile),
    target=RASTER_IMAGE_ARTIFACT,
    convert=_webp_file_to_raster,
)
TIFF_FILE_TO_RASTER: Final = Conversion(
    id="builtin.file.tiff_to_raster",
    version=1,
    title="As raster image",
    source=_file_declaration(TiffFile),
    target=RASTER_IMAGE_ARTIFACT,
    convert=_tiff_file_to_raster,
)
BMP_FILE_TO_RASTER: Final = Conversion(
    id="builtin.file.bmp_to_raster",
    version=1,
    title="As raster image",
    source=_file_declaration(BmpFile),
    target=RASTER_IMAGE_ARTIFACT,
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
    conversions: dict[ArtifactConversionKey, Conversion[Any, Any]] = {}
    for conversion in CANONICAL_ARTIFACT_CONVERSIONS:
        key = ArtifactConversionKey(conversion.id, conversion.version)
        if key in conversions:
            raise RuntimeError(
                f"Duplicate canonical artifact conversion {key.id}@{key.version}"
            )
        conversions[key] = conversion
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
