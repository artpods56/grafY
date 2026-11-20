"""File and raster handles, and the declarations that store them.

A handle has no public artifact ref. ``read`` refuses a known size over the
caller's limit before storage is called.
"""

from typing import ClassVar, Self

from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.artifacts import ArtifactTypeSpec, JsonObject
from grafy_core.file_contracts import (
    BMP_FILE,
    BLOB_FILE,
    CSV_FILE,
    GEOJSON_FILE,
    JPEG_FILE,
    JSON_FILE,
    PDF_FILE,
    PNG_FILE,
    TIFF_FILE,
    TXT_FILE,
    WEBP_FILE,
    XLSX_FILE,
)
from grafy_core.ports.storage import FileStoragePort
from grafy_core.declared_values import note_declaration
from grafy_core.runtime.artifact_values import (
    Artifact,
    ArtifactFiles,
    EncodedArtifact,
    StoredArtifact,
)
from grafy_core.runtime.resolvers import ArtifactContractError

_WRITE_LIMIT = 256 * 1024 * 1024

_RASTER_SUFFIXES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
}


class _StoredBytes:
    def __init__(
        self,
        *,
        content_type: str,
        byte_size: int | None,
        filename: str | None,
        content: bytes | None,
        storage: FileStoragePort | None,
        bucket: str | None,
        object_key: str | None,
    ) -> None:
        self.content_type = content_type
        self.byte_size = byte_size
        self.filename = filename
        self._content = content
        self._storage = storage
        self._bucket = bucket
        self._object_key = object_key

    async def read(self, *, max_bytes: int) -> bytes:
        if self.byte_size is not None and self.byte_size > max_bytes:
            raise ValueError(
                f"Refusing to read {self.byte_size} bytes, over the limit of {max_bytes}"
            )
        if self._content is not None:
            if len(self._content) > max_bytes:
                raise ValueError(
                    f"Refusing to read {len(self._content)} bytes, "
                    f"over the limit of {max_bytes}"
                )
            return self._content
        if self._storage is None or self._bucket is None or self._object_key is None:
            raise ArtifactContractError("Stored handle has no bytes and no object")
        stream = await self._storage.load(bucket=self._bucket, path=self._object_key)
        try:
            if self.byte_size is None:
                content = stream.read(max_bytes + 1)
            else:
                content = stream.read()
        finally:
            stream.close()
        if len(content) > max_bytes:
            raise ValueError(
                f"Refusing to read a stream over the limit of {max_bytes} bytes"
            )
        return content


def _filename(stored: StoredArtifact) -> str | None:
    recorded = stored.row.metadata.get("original_filename")
    if isinstance(recorded, str) and recorded.strip() != "":
        return recorded
    return None


class File(_StoredBytes):
    """A stored file. The base class is not a declared artifact value."""

    media_type: ClassVar[str] = ""
    suffix: ClassVar[str] = ""

    @classmethod
    def from_stored(cls, stored: StoredArtifact) -> Self:
        row = stored.row
        if row.bucket is None or row.object_key is None:
            raise ArtifactContractError(
                f"File artifact {row.id} ({row.artifact_type}@{row.schema_version}) "
                "has no stored object"
            )
        return cls(
            content_type=row.content_type,
            byte_size=row.byte_size,
            filename=_filename(stored),
            content=None,
            storage=stored.storage,
            bucket=row.bucket,
            object_key=row.object_key,
        )

    @classmethod
    def from_content(
        cls,
        content: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> Self:
        if cls is File:
            raise TypeError("File is not a declared artifact value")
        if cls is not BlobFile and content_type != cls.media_type:
            raise ValueError(
                f"{cls.__name__} content type must be {cls.media_type}, "
                f"got {content_type}"
            )
        return cls(
            content_type=content_type,
            byte_size=len(content),
            filename=filename,
            content=content,
            storage=None,
            bucket=None,
            object_key=None,
        )


class PngFile(File):
    media_type = "image/png"
    suffix = ".png"


class JpegFile(File):
    media_type = "image/jpeg"
    suffix = ".jpg"


class TiffFile(File):
    media_type = "image/tiff"
    suffix = ".tiff"


class WebpFile(File):
    media_type = "image/webp"
    suffix = ".webp"


class BmpFile(File):
    media_type = "image/bmp"
    suffix = ".bmp"


class PdfFile(File):
    media_type = "application/pdf"
    suffix = ".pdf"


class XlsxFile(File):
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    suffix = ".xlsx"


class GeoJsonFile(File):
    media_type = "application/geo+json"
    suffix = ".geojson"


class JsonFile(File):
    media_type = "application/json"
    suffix = ".json"


class CsvFile(File):
    media_type = "text/csv"
    suffix = ".csv"


class TxtFile(File):
    media_type = "text/plain"
    suffix = ".txt"


class BlobFile(File):
    media_type = "application/octet-stream"
    suffix = ""


class RasterImage(_StoredBytes):
    @classmethod
    def from_stored(cls, stored: StoredArtifact) -> Self:
        row = stored.row
        if row.bucket is None or row.object_key is None:
            raise ArtifactContractError(
                f"Raster artifact {row.id} has no stored object"
            )
        return cls(
            content_type=row.content_type,
            byte_size=row.byte_size,
            filename=_filename(stored),
            content=None,
            storage=stored.storage,
            bucket=row.bucket,
            object_key=row.object_key,
        )

    @classmethod
    def from_content(
        cls,
        content: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> Self:
        return cls(
            content_type=content_type,
            byte_size=len(content),
            filename=filename,
            content=content,
            storage=None,
            bucket=None,
            object_key=None,
        )


def _stored_metadata(
    value: _StoredBytes, stored_sha: str, stored_size: int
) -> JsonObject:
    metadata: JsonObject = {
        "content_hash": stored_sha,
        "storage_byte_size": stored_size,
        "storage_sha256": stored_sha,
    }
    if value.filename is not None:
        metadata["original_filename"] = value.filename
    return metadata


async def _write_stored(
    spec: ArtifactTypeSpec,
    value: _StoredBytes,
    files: ArtifactFiles,
    *,
    content_type: str,
    suffix: str,
) -> EncodedArtifact:
    content = await value.read(max_bytes=_WRITE_LIMIT)
    stored = await files.save(
        spec,
        content,
        content_type=content_type,
        suffix=suffix,
    )
    return EncodedArtifact(
        content_type=content_type,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        stored=stored,
        metadata=_stored_metadata(value, stored.sha256, stored.byte_size),
    )


def file_artifact[T: File](spec: ArtifactTypeSpec, value_type: type[T]) -> Artifact[T]:
    async def resolve(stored: StoredArtifact) -> T:
        return value_type.from_stored(stored)

    async def write(value: T, files: ArtifactFiles) -> EncodedArtifact:
        content_type = (
            value.content_type if type(value) is BlobFile else value_type.media_type
        )
        return await _write_stored(
            spec,
            value,
            files,
            content_type=content_type,
            suffix=value_type.suffix,
        )

    return Artifact(spec=spec, value_type=value_type, resolve=resolve, write=write)


FILE_ARTIFACTS: tuple[Artifact[File], ...] = (
    file_artifact(PNG_FILE, PngFile),
    file_artifact(JPEG_FILE, JpegFile),
    file_artifact(TIFF_FILE, TiffFile),
    file_artifact(WEBP_FILE, WebpFile),
    file_artifact(BMP_FILE, BmpFile),
    file_artifact(PDF_FILE, PdfFile),
    file_artifact(XLSX_FILE, XlsxFile),
    file_artifact(GEOJSON_FILE, GeoJsonFile),
    file_artifact(JSON_FILE, JsonFile),
    file_artifact(CSV_FILE, CsvFile),
    file_artifact(TXT_FILE, TxtFile),
    file_artifact(BLOB_FILE, BlobFile),
)
for _file_artifact in FILE_ARTIFACTS:
    note_declaration(_file_artifact.value_type, _file_artifact.spec.key)


def raster_image_artifact() -> Artifact[RasterImage]:
    async def resolve(stored: StoredArtifact) -> RasterImage:
        return RasterImage.from_stored(stored)

    async def write(value: RasterImage, files: ArtifactFiles) -> EncodedArtifact:
        suffix = _RASTER_SUFFIXES.get(value.content_type)
        if suffix is None:
            raise ValueError(f"Unknown raster content type {value.content_type}")
        return await _write_stored(
            RASTER_IMAGE,
            value,
            files,
            content_type=value.content_type,
            suffix=suffix,
        )

    return Artifact(
        spec=RASTER_IMAGE,
        value_type=RasterImage,
        resolve=resolve,
        write=write,
    )


RASTER_IMAGE_ARTIFACT = raster_image_artifact()
note_declaration(RasterImage, RASTER_IMAGE.key)


__all__ = [
    "FILE_ARTIFACTS",
    "RASTER_IMAGE_ARTIFACT",
    "BmpFile",
    "BlobFile",
    "CsvFile",
    "File",
    "GeoJsonFile",
    "JpegFile",
    "JsonFile",
    "PdfFile",
    "PngFile",
    "RasterImage",
    "TiffFile",
    "TxtFile",
    "WebpFile",
    "XlsxFile",
    "file_artifact",
    "raster_image_artifact",
]
