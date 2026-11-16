from io import BytesIO
from typing import cast

from PIL import Image

import pytest

from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.canonical_conversions import (
    CANONICAL_ARTIFACT_CONVERSIONS,
    CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
    INTEGER_TO_TEXT,
    PNG_FILE_TO_RASTER,
    JPEG_FILE_TO_RASTER,
    WEBP_FILE_TO_RASTER,
    TIFF_FILE_TO_RASTER,
    BMP_FILE_TO_RASTER,
    TEXT_FILE_TO_TEXT,
)
from grafy_core.artifact_contracts import RasterImageContent
from grafy_core.conversions import ArtifactConversion
from grafy_core.file_contracts import TXT_FILE


def test_integer_to_text_is_an_exact_deployment_owned_conversion() -> None:
    assert CANONICAL_ARTIFACT_CONVERSIONS == (
        INTEGER_TO_TEXT,
        TEXT_FILE_TO_TEXT,
        PNG_FILE_TO_RASTER,
        JPEG_FILE_TO_RASTER,
        WEBP_FILE_TO_RASTER,
        TIFF_FILE_TO_RASTER,
        BMP_FILE_TO_RASTER,
    )
    assert CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY == {
        conversion.key: conversion for conversion in CANONICAL_ARTIFACT_CONVERSIONS
    }
    assert INTEGER_TO_TEXT.key.id == "builtin.scalar.integer_to_text"
    assert INTEGER_TO_TEXT.key.version == 1
    assert INTEGER_TO_TEXT.source == INTEGER_VALUE.key
    assert INTEGER_TO_TEXT.target == TEXT_VALUE.key
    assert INTEGER_TO_TEXT.source_type is int
    assert INTEGER_TO_TEXT.target_type is str
    assert INTEGER_TO_TEXT.title == "As text"
    assert INTEGER_TO_TEXT.convert(42) == "42"


def test_text_file_to_text_is_an_exact_deployment_owned_conversion() -> None:
    assert TEXT_FILE_TO_TEXT.key.id == "builtin.file.txt_to_text"
    assert TEXT_FILE_TO_TEXT.key.version == 1
    assert TEXT_FILE_TO_TEXT.source == TXT_FILE.key
    assert TEXT_FILE_TO_TEXT.target == TEXT_VALUE.key
    assert TEXT_FILE_TO_TEXT.source_type is bytes
    assert TEXT_FILE_TO_TEXT.target_type is str
    assert TEXT_FILE_TO_TEXT.convert("héllo".encode()) == "héllo"
    assert TEXT_FILE_TO_TEXT.convert(b"\xef\xbb\xbfhello") == "hello"
    with pytest.raises(UnicodeDecodeError):
        _ = TEXT_FILE_TO_TEXT.convert(b"\xff\xfe")


def test_canonical_conversion_registry_is_immutable() -> None:
    mutable_view = cast(dict[object, object], CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY)

    with pytest.raises(TypeError):
        mutable_view[INTEGER_TO_TEXT.key] = INTEGER_TO_TEXT


@pytest.mark.parametrize(
    "conversion,format_name,mime",
    [
        (PNG_FILE_TO_RASTER, "PNG", "image/png"),
        (JPEG_FILE_TO_RASTER, "JPEG", "image/jpeg"),
        (WEBP_FILE_TO_RASTER, "WEBP", "image/webp"),
        (TIFF_FILE_TO_RASTER, "TIFF", "image/tiff"),
        (BMP_FILE_TO_RASTER, "BMP", "image/bmp"),
    ],
)
def test_image_conversion_validates_and_preserves_bytes(
    conversion: ArtifactConversion[bytes, RasterImageContent],
    format_name: str,
    mime: str,
) -> None:
    buffer = BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format=format_name)
    content = buffer.getvalue()
    result = conversion.convert(content)
    assert result.content == content
    assert result.content_type == mime
    with pytest.raises((OSError, ValueError)):
        _ = conversion.convert(content[:8])
