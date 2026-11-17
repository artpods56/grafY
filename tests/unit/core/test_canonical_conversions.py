from io import BytesIO
from typing import Any, cast

from PIL import Image

import pytest

from grafy_core.artifact_contracts import (
    INTEGER_VALUE,
    TEXT_VALUE,
    IntegerValuePayload,
    TextValuePayload,
)
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
from grafy_core.conversions import ArtifactConversionKey, Conversion
from grafy_core.documents import (
    BmpFile,
    JpegFile,
    PngFile,
    RasterImage,
    TiffFile,
    TxtFile,
    WebpFile,
)
from grafy_core.file_contracts import TXT_FILE
from grafy_core.runtime.artifact_values import scalar_artifact


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
        ArtifactConversionKey(conversion.id, conversion.version): conversion
        for conversion in CANONICAL_ARTIFACT_CONVERSIONS
    }


def test_canonical_conversion_registry_is_immutable() -> None:
    mutable_view = cast(dict[object, object], CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY)
    key = ArtifactConversionKey(INTEGER_TO_TEXT.id, INTEGER_TO_TEXT.version)

    with pytest.raises(TypeError):
        mutable_view[key] = INTEGER_TO_TEXT


@pytest.mark.asyncio
async def test_integer_to_text_converts_the_declared_scalar() -> None:
    assert INTEGER_TO_TEXT.id == "builtin.scalar.integer_to_text"
    assert INTEGER_TO_TEXT.version == 1
    assert INTEGER_TO_TEXT.source.spec.key == INTEGER_VALUE.key
    assert INTEGER_TO_TEXT.target.spec.key == TEXT_VALUE.key
    assert INTEGER_TO_TEXT.source.value_type is int
    assert INTEGER_TO_TEXT.target.value_type is str
    assert INTEGER_TO_TEXT.title == "As text"
    assert await INTEGER_TO_TEXT.convert(42) == "42"


@pytest.mark.asyncio
async def test_text_file_to_text_reads_the_handle() -> None:
    assert TEXT_FILE_TO_TEXT.id == "builtin.file.txt_to_text"
    assert TEXT_FILE_TO_TEXT.version == 1
    assert TEXT_FILE_TO_TEXT.source.spec.key == TXT_FILE.key
    assert TEXT_FILE_TO_TEXT.target.spec.key == TEXT_VALUE.key
    assert TEXT_FILE_TO_TEXT.source.value_type is TxtFile
    assert TEXT_FILE_TO_TEXT.target.value_type is str

    hello = TxtFile.from_content(
        "héllo".encode(),
        content_type="text/plain",
        filename=None,
    )
    marked = TxtFile.from_content(
        b"\xef\xbb\xbfhello",
        content_type="text/plain",
        filename=None,
    )
    broken = TxtFile.from_content(
        b"\xff\xfe",
        content_type="text/plain",
        filename=None,
    )
    assert await TEXT_FILE_TO_TEXT.convert(hello) == "héllo"
    assert await TEXT_FILE_TO_TEXT.convert(marked) == "hello"
    with pytest.raises(UnicodeDecodeError):
        _ = await TEXT_FILE_TO_TEXT.convert(broken)


def test_conversion_rejects_a_blank_identity_or_title() -> None:
    source = scalar_artifact(INTEGER_VALUE, int, IntegerValuePayload)
    target = scalar_artifact(TEXT_VALUE, str, TextValuePayload)

    async def convert(value: int) -> str:
        return str(value)

    with pytest.raises(ValueError, match="id must not be blank"):
        Conversion(
            id="   ",
            version=1,
            title="As text",
            source=source,
            target=target,
            convert=convert,
        )
    with pytest.raises(ValueError, match="version must be positive"):
        Conversion(
            id="example.invalid",
            version=0,
            title="As text",
            source=source,
            target=target,
            convert=convert,
        )
    with pytest.raises(ValueError, match="title must not be blank"):
        Conversion(
            id="example.invalid",
            version=1,
            title="   ",
            source=source,
            target=target,
            convert=convert,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("conversion", "file_type", "format_name", "mime"),
    [
        (PNG_FILE_TO_RASTER, PngFile, "PNG", "image/png"),
        (JPEG_FILE_TO_RASTER, JpegFile, "JPEG", "image/jpeg"),
        (WEBP_FILE_TO_RASTER, WebpFile, "WEBP", "image/webp"),
        (TIFF_FILE_TO_RASTER, TiffFile, "TIFF", "image/tiff"),
        (BMP_FILE_TO_RASTER, BmpFile, "BMP", "image/bmp"),
    ],
)
async def test_image_conversion_validates_and_preserves_bytes(
    conversion: Conversion[Any, RasterImage],
    file_type: type[BmpFile | JpegFile | PngFile | TiffFile | WebpFile],
    format_name: str,
    mime: str,
) -> None:
    buffer = BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format=format_name)
    content = buffer.getvalue()
    handle = file_type.from_content(content, content_type=mime, filename=None)
    result = await conversion.convert(handle)
    assert result.content_type == mime
    assert await result.read(max_bytes=len(content)) == content
    broken = file_type.from_content(content[:8], content_type=mime, filename=None)
    with pytest.raises((OSError, ValueError)):
        _ = await conversion.convert(broken)
