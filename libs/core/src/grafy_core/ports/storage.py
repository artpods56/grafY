from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import BinaryIO, Protocol, TypedDict, runtime_checkable


class ReadableStream(Protocol):
    """The stream shape storage writers actually consume."""

    def read(self, size: int = -1, /) -> bytes: ...


FileStreamProtocol = BinaryIO


class ChunkReader(Protocol):
    """A bounded reader over stored object bytes."""

    def read(self, size: int = -1, /) -> bytes: ...

    def close(self) -> None: ...


class FileMetadata(TypedDict, total=False):
    original_filename: str | None
    source: str
    artifact_id: str
    artifact_kind: str
    job_id: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SaveFileCommand:
    bucket: str
    path: str
    stream: ReadableStream
    content_type: str
    metadata: FileMetadata
    allow_overwrite: bool = False


@dataclass(frozen=True, slots=True)
class StoredFile:
    bucket: str
    path: str
    etag: str | None
    version_id: str | None
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StoredObjectInfo:
    bucket: str
    path: str
    byte_size: int
    etag: str | None
    version_id: str | None


@dataclass(frozen=True, slots=True)
class PresignedUploadTarget:
    """A create-only client PUT target for one object key.

    ``required_headers`` are part of the signature. Omitting or altering them
    must invalidate the request. Default representations redact the URL and
    capability-bearing header values.
    """

    url: str
    method: str
    expires_at: datetime
    required_headers: Mapping[str, str]

    def __repr__(self) -> str:
        headers = ", ".join(
            f"{name}=<redacted>" for name in sorted(self.required_headers)
        )
        return (
            "PresignedUploadTarget("
            f"url=<redacted>, method={self.method!r}, "
            f"expires_at={self.expires_at!r}, required_headers={{{headers}}})"
        )


@runtime_checkable
class FileStoragePort(Protocol):
    async def save(self, command: SaveFileCommand) -> StoredFile: ...

    async def move(
        self, bucket: str, source_path: str, destination_path: str
    ) -> None: ...

    async def load(self, bucket: str, path: str) -> FileStreamProtocol: ...

    async def open_chunks(self, bucket: str, path: str) -> ChunkReader: ...

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None: ...

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes: ...

    async def delete(self, bucket: str, path: str) -> None: ...


@runtime_checkable
class PresigningStorage(Protocol):
    """Object storage that can sign a create-only client PUT."""

    async def create_presigned_upload(
        self,
        bucket: str,
        path: str,
        *,
        expires_in: timedelta,
    ) -> PresignedUploadTarget: ...
