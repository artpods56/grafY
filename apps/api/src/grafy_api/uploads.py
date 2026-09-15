"""Presigned upload lifecycle: authorize, receive, validate, then promote.

The API never buffers a whole upload. A client first reserves one upload and
receives a short-lived target; the bytes then travel straight to object storage
(or, on the local backend, to this API's own content route). Completion is the
only step that inspects content, and it streams.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path
from typing import Protocol, cast, final, runtime_checkable
from uuid import UUID, uuid4

from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.domain.uploads import Upload, UploadStatus
from grafy_core.file_contracts import BLOB_FILE
from grafy_core.ports.storage import (
    FileStoragePort,
    FileStreamProtocol,
    SaveFileCommand,
)
from grafy_core.ports.uploads import UploadUnitOfWorkPort
from grafy_core.runtime.upload_reader import require_ready_upload
from PIL import Image as ImageModule
from PIL import ImageDraw
from starlette.concurrency import run_in_threadpool

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.settings import STAGED_UPLOAD_HARD_MAX_BYTES

_READ_CHUNK_BYTES = 1024 * 1024
_FILENAME_MAX_LENGTH = 255
_SAMPLE_PAGE_TEXTS = (
    "PAGE {index}\nParochia Sancti Floriani\nAnno Domini 1846",
    "PAGE {index}\nBaptisatorum liber\nVilla Nova, folio {index}",
    "PAGE {index}\nIndex nominum\nSeries continua",
)


class UploadTooLargeError(WorkbenchOperationError):
    """A file exceeds the configured per-upload byte limit."""


class UploadNotFoundError(WorkbenchOperationError):
    """No upload with that identifier exists in this workspace."""


class UploadStateError(WorkbenchOperationError):
    """An upload is not in a state that allows the requested operation."""


class UploadExpiredError(UploadStateError):
    """An upload was abandoned for longer than its lifetime."""


class UploadTransportUnsupportedError(WorkbenchOperationError):
    """This deployment does not accept upload bytes through the API."""


class FileFormatMismatchError(WorkbenchOperationError):
    """A known extension's bytes disagree with the format that extension names."""

    def __init__(self, filename: str, expected: str) -> None:
        super().__init__(
            f"{filename!r} does not look like a {expected} file. "
            "Rename it or convert it, then try again."
        )


@dataclass(frozen=True, slots=True)
class UploadTarget:
    """Where a client should send the bytes of one reserved upload."""

    upload_id: UUID
    url: str
    method: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UploadResult:
    """A completed upload and the file format ingest resolved for its bytes."""

    upload: Upload
    artifact_type: ArtifactTypeKey | None = None


class ByteReader(Protocol):
    """The only stream shape receiving upload bytes needs.

    ``read`` is position-only to match both ``BinaryIO`` and
    ``SpooledTemporaryFile``, the two readers this seam accepts.
    """

    def read(self, size: int = -1, /) -> bytes: ...


@runtime_checkable
class PresigningStorage(Protocol):
    """Object storage that can sign a direct client PUT."""

    async def create_presigned_upload(
        self,
        bucket: str,
        path: str,
        *,
        expires_in: timedelta,
    ) -> str: ...


@final
class _LimitedReader:
    """Stream adapter that fails once one upload exceeds its byte limit."""

    def __init__(self, stream: ByteReader, max_bytes: int, label: str) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self._label = label
        self._byte_count = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        self._byte_count += len(chunk)
        if self._byte_count > self._max_bytes:
            raise UploadTooLargeError(
                f"Upload {self._label!r} exceeds the upload limit of "
                f"{self._max_bytes} bytes"
            )
        return chunk


def _sha256_stream(stream: FileStreamProtocol) -> str:
    digest = sha256()
    while chunk := stream.read(_READ_CHUNK_BYTES):
        digest.update(chunk)
    return digest.hexdigest()


def _render_sample_page(index: int) -> bytes:
    text = _SAMPLE_PAGE_TEXTS[index % len(_SAMPLE_PAGE_TEXTS)].format(index=index + 1)
    image = ImageModule.new("RGB", (420, 300), color="#f5f0e6")
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 407, 287), outline="#b9ad98")
    draw.multiline_text((36, 48), text, fill="#463c2e", spacing=14)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class UploadService:
    """Reserve, validate, and promote uploaded files without a queue."""

    def __init__(
        self,
        *,
        storage: FileStoragePort,
        unit_of_work_factory: Callable[[], UploadUnitOfWorkPort],
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec],
        extension_claims: Mapping[str, ArtifactTypeKey],
        bucket: str,
        storage_backend: str,
        presigning: PresigningStorage | None = None,
        upload_route_prefix: str = "/v1",
        upload_lifetime: timedelta = timedelta(hours=24),
        upload_target_ttl: timedelta = timedelta(minutes=15),
        max_upload_bytes: int = STAGED_UPLOAD_HARD_MAX_BYTES,
    ) -> None:
        if max_upload_bytes < 1:
            raise ValueError("Upload byte limit must be positive")
        if max_upload_bytes > STAGED_UPLOAD_HARD_MAX_BYTES:
            raise ValueError("Upload byte limit must not exceed the 64 MiB hard limit")
        if upload_lifetime <= upload_target_ttl:
            raise ValueError("Upload lifetime must exceed its target lifetime")
        self._storage = storage
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_types = artifact_types
        self._extension_claims = extension_claims
        self._bucket = bucket
        self._storage_backend = storage_backend
        self._presigning = presigning
        self._upload_route_prefix = upload_route_prefix.rstrip("/")
        self._upload_lifetime = upload_lifetime
        self._upload_target_ttl = upload_target_ttl
        self._max_upload_bytes = max_upload_bytes

    @property
    def accepts_direct_upload(self) -> bool:
        """Whether this deployment receives bytes on its own content route."""

        return self._presigning is None

    async def create_upload(
        self,
        *,
        workspace_id: UUID,
        created_by_user_id: UUID | None,
        filename: str,
        byte_size: int,
        content_type: str | None = None,
    ) -> UploadTarget:
        original_filename = filename.strip()
        if original_filename == "":
            raise WorkbenchOperationError("Upload filename is required")
        if len(original_filename) > _FILENAME_MAX_LENGTH:
            raise WorkbenchOperationError(
                f"Upload filename must be at most {_FILENAME_MAX_LENGTH} characters"
            )
        if byte_size < 0:
            raise WorkbenchOperationError("Upload byte size must not be negative")
        if byte_size > self._max_upload_bytes:
            raise UploadTooLargeError(
                f"Upload {original_filename!r} exceeds the upload limit of "
                f"{self._max_upload_bytes} bytes"
            )
        upload_id = uuid4()
        record = Upload(
            workspace_id=workspace_id,
            upload_id=upload_id,
            original_filename=original_filename,
            bucket=self._bucket,
            object_key=self._object_key(upload_id),
            expected_size=byte_size,
            content_type=(content_type or guess_type(original_filename)[0])
            or "application/octet-stream",
            created_by_user_id=created_by_user_id,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.uploads.add(record)
            await unit_of_work.commit()
        return UploadTarget(
            upload_id=upload_id,
            url=await self._upload_target_url(record),
            method="PUT",
            expires_at=record.created_at + self._upload_target_ttl,
        )

    async def receive_content(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        stream: ByteReader,
    ) -> None:
        """Store bytes a client sent to this API's own content route."""

        if not self.accepts_direct_upload:
            raise UploadTransportUnsupportedError(
                "This deployment accepts upload bytes only through signed URLs"
            )
        record = await self._require_pending(workspace_id, upload_id)
        command = SaveFileCommand(
            bucket=record.bucket,
            path=record.object_key,
            stream=cast_object(
                _LimitedReader(
                    stream,
                    self._max_upload_bytes,
                    record.original_filename,
                )
            ),
            content_type=record.content_type or "application/octet-stream",
            metadata={"original_filename": record.original_filename},
        )
        try:
            _ = await self._storage.save(command)
        except UploadTooLargeError:
            await self._storage.delete(record.bucket, record.object_key)
            raise

    async def complete_upload(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
    ) -> UploadResult:
        record = await self._require_pending(workspace_id, upload_id)
        stored = await self._storage.stat(record.bucket, record.object_key)
        if stored is None:
            await self._mark_failed(record)
            raise UploadStateError(
                f"Upload {record.original_filename!r} has no stored bytes"
            )
        if stored.byte_size > self._max_upload_bytes:
            await self._mark_failed(record)
            raise UploadTooLargeError(
                f"Upload {record.original_filename!r} exceeds the upload limit of "
                f"{self._max_upload_bytes} bytes"
            )
        if stored.byte_size != record.expected_size:
            await self._mark_failed(record)
            raise UploadStateError(
                f"Upload {record.original_filename!r} declared "
                f"{record.expected_size} bytes but {stored.byte_size} were stored"
            )
        try:
            key = await self._resolve_artifact_type(record)
        except WorkbenchOperationError:
            await self._mark_failed(record)
            raise
        digest = await self._digest(record)
        artifact = ArtifactObject(
            workspace_id=workspace_id,
            artifact_type=key.id,
            schema_version=key.schema_version,
            content_type=record.content_type or "application/octet-stream",
            storage_backend=self._storage_backend,
            bucket=record.bucket,
            object_key=record.object_key,
            byte_size=stored.byte_size,
            sha256=digest,
            metadata={"original_filename": record.original_filename},
        )
        completed_at = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            current = await unit_of_work.uploads.get(workspace_id, upload_id)
            if current is None or current.status is not UploadStatus.PENDING:
                raise UploadStateError(
                    f"Upload {record.original_filename!r} is no longer pending"
                )
            current.status = UploadStatus.READY
            current.actual_size = stored.byte_size
            current.sha256 = digest
            current.artifact_type = key.id
            current.completed_at = completed_at
            await unit_of_work.artifacts.add(artifact)
            await unit_of_work.commit()
        return UploadResult(upload=current, artifact_type=key)

    async def create_sample_images(
        self,
        *,
        workspace_id: UUID,
        created_by_user_id: UUID | None,
        count: int,
    ) -> list[UploadResult]:
        results: list[UploadResult] = []
        for index in range(count):
            content = await run_in_threadpool(_render_sample_page, index)
            filename = f"sample-page-{index + 1}.png"
            target = await self.create_upload(
                workspace_id=workspace_id,
                created_by_user_id=created_by_user_id,
                filename=filename,
                byte_size=len(content),
                content_type="image/png",
            )
            _ = await self._storage.save(
                SaveFileCommand(
                    bucket=self._bucket,
                    path=self._object_key(target.upload_id),
                    stream=BytesIO(content),
                    content_type="image/png",
                    metadata={"original_filename": filename},
                )
            )
            results.append(
                await self.complete_upload(
                    workspace_id=workspace_id,
                    upload_id=target.upload_id,
                )
            )
        return results

    async def cleanup_abandoned(
        self,
        *,
        older_than: timedelta | None = None,
        limit: int = 500,
    ) -> int:
        """Delete abandoned uploads and their stored bytes.

        Idempotent and safe to re-run, including from several workers: an
        upload promoted while this runs keeps its row and its bytes.
        """

        resolved_older_than = (
            self._upload_lifetime if older_than is None else older_than
        )
        cutoff = datetime.now(UTC) - resolved_older_than
        async with self._unit_of_work_factory() as unit_of_work:
            abandoned = await unit_of_work.uploads.list_abandoned_before(
                cutoff,
                limit=limit,
            )
        discarded = 0
        for record in abandoned:
            async with self._unit_of_work_factory() as unit_of_work:
                removed = await unit_of_work.uploads.discard(
                    record.workspace_id,
                    record.upload_id,
                )
                await unit_of_work.commit()
            if not removed:
                continue
            await self._storage.delete(record.bucket, record.object_key)
            discarded += 1
        return discarded

    async def _upload_target_url(self, record: Upload) -> str:
        if self._presigning is None:
            return (
                f"{self._upload_route_prefix}/workspaces/{record.workspace_id}"
                f"/uploads/{record.upload_id}/content"
            )
        return await self._presigning.create_presigned_upload(
            record.bucket,
            record.object_key,
            expires_in=self._upload_target_ttl,
        )

    async def _require_pending(self, workspace_id: UUID, upload_id: UUID) -> Upload:
        async with self._unit_of_work_factory() as unit_of_work:
            record = await unit_of_work.uploads.get(workspace_id, upload_id)
        if record is None:
            raise UploadNotFoundError(
                f"Upload {upload_id} was not found in workspace {workspace_id}"
            )
        if record.status is UploadStatus.READY:
            raise UploadStateError(f"Upload {upload_id} is already complete")
        if record.status is not UploadStatus.PENDING:
            raise UploadStateError(
                f"Upload {upload_id} is {record.status.value} and cannot be used"
            )
        if datetime.now(UTC) - record.created_at > self._upload_lifetime:
            await self._mark_failed(record, status=UploadStatus.EXPIRED)
            raise UploadExpiredError(
                f"Upload {record.original_filename!r} expired before it was used"
            )
        return record

    async def _mark_failed(
        self,
        record: Upload,
        *,
        status: UploadStatus = UploadStatus.FAILED,
    ) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            current = await unit_of_work.uploads.get(
                record.workspace_id,
                record.upload_id,
            )
            if current is None or current.status is not UploadStatus.PENDING:
                return
            current.status = status
            await unit_of_work.commit()

    async def _digest(self, record: Upload) -> str:
        stream = await self._storage.load(record.bucket, record.object_key)
        try:
            return await run_in_threadpool(_sha256_stream, stream)
        finally:
            stream.close()

    async def _resolve_artifact_type(self, record: Upload) -> ArtifactTypeKey:
        extension = Path(record.original_filename).suffix[1:].casefold()
        key = self._extension_claims.get(extension)
        if key is None:
            return BLOB_FILE.key
        spec = self._artifact_types.get((key.id, key.schema_version))
        if spec is None:
            raise WorkbenchOperationError(
                f"Upload extension {extension!r} maps to artifact type "
                f"{key.id}@{key.schema_version}, which this deployment does "
                "not declare"
            )
        if not await self._confirms(spec, record):
            expected = key.id.removeprefix("file.").upper()
            raise FileFormatMismatchError(record.original_filename, expected)
        return key

    async def _confirms(self, spec: ArtifactTypeSpec, record: Upload) -> bool:
        rule = spec.confirmation_rule
        if rule.rule == "none":
            return True
        if rule.rule == "magic":
            prefix_bytes = max(
                segment.offset + len(segment.value)
                for signature in rule.signatures
                for segment in signature.segments
            )
            content = await self._storage.load_range(
                record.bucket,
                record.object_key,
                0,
                prefix_bytes,
            )
            return rule.confirms(content)
        stream = await self._storage.load(record.bucket, record.object_key)
        try:
            content = await run_in_threadpool(stream.read)
        finally:
            stream.close()
        return rule.confirms(content)

    def _object_key(self, upload_id: UUID) -> str:
        return f"objects/{upload_id}"


def cast_object(value: object) -> FileStreamProtocol:
    """Present a duck-typed reader as the storage port's stream type."""

    return cast(FileStreamProtocol, value)


@final
class StorageUploadReader:
    """Read a completed upload's bytes from object storage for one run."""

    def __init__(
        self,
        *,
        storage: FileStoragePort,
        unit_of_work_factory: Callable[[], UploadUnitOfWorkPort],
    ) -> None:
        self._storage = storage
        self._unit_of_work_factory = unit_of_work_factory

    async def read(self, workspace_id: UUID, upload_id: UUID) -> bytes:
        record = await require_ready_upload(
            self._unit_of_work_factory(),
            workspace_id,
            upload_id,
        )
        stream = await self._storage.load(record.bucket, record.object_key)
        try:
            return await run_in_threadpool(stream.read)
        finally:
            stream.close()


__all__ = [
    "ByteReader",
    "FileFormatMismatchError",
    "PresigningStorage",
    "StorageUploadReader",
    "UploadExpiredError",
    "UploadNotFoundError",
    "UploadResult",
    "UploadService",
    "UploadStateError",
    "UploadTarget",
    "UploadTooLargeError",
    "UploadTransportUnsupportedError",
]
