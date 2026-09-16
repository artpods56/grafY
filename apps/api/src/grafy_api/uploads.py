"""Presigned upload lifecycle: authorize, receive, validate, then promote.

The API never buffers a whole upload. A client first reserves one upload and
receives a short-lived target; the bytes then travel straight to object storage
(or, on the local backend, to this API's own content route). Completion is the
only step that inspects content, and it streams.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from mimetypes import guess_type
from typing import Literal, Protocol, Self, final
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator
from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.domain.uploads import Upload, UploadStatus
from grafy_core.ports.storage import (
    FileStoragePort,
    PresignedUploadTarget,
    PresigningStorage,
    ReadableStream,
    SaveFileCommand,
)
from grafy_core.ports.uploads import UploadUnitOfWorkPort
from grafy_storage.adapters.local import LocalFileObjectStore

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.settings import STAGED_UPLOAD_HARD_MAX_BYTES, Settings
from grafy_api.upload_inspection import (
    FileFormatMismatchError,
    UploadInspectionError,
    inspect_upload_async,
)

logger = logging.getLogger(__name__)


class UploadServiceConfig(BaseModel):
    """Deployment knobs for upload reserve / receive / cleanup."""

    max_upload_bytes: int = Field(
        default=STAGED_UPLOAD_HARD_MAX_BYTES,
        ge=1,
        le=STAGED_UPLOAD_HARD_MAX_BYTES,
    )
    upload_lifetime: timedelta = Field(default=timedelta(hours=24))
    upload_target_ttl: timedelta = Field(default=timedelta(minutes=15))
    upload_receive_timeout: timedelta = Field(default=timedelta(minutes=30))
    upload_route_prefix: str = "/v1"

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        if self.upload_lifetime <= self.upload_target_ttl:
            raise ValueError("Upload lifetime must exceed its target lifetime")
        if self.upload_receive_timeout <= timedelta(0):
            raise ValueError("Upload receive timeout must be positive")
        return self

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            max_upload_bytes=settings.staged_upload_max_bytes,
            upload_lifetime=timedelta(seconds=settings.upload_lifetime_seconds),
            upload_target_ttl=timedelta(seconds=settings.upload_target_ttl_seconds),
            upload_receive_timeout=timedelta(
                seconds=settings.upload_receive_timeout_seconds
            ),
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


@dataclass(frozen=True, slots=True)
class UploadTarget:
    """Where a client should send the bytes of one reserved upload."""

    upload_id: UUID
    url: str
    method: str
    expires_at: datetime
    kind: Literal["api", "storage"]
    headers: Mapping[str, str]

    def __repr__(self) -> str:
        headers = (
            "{}"
            if not self.headers
            else "{"
            + ", ".join(f"{name}=<redacted>" for name in sorted(self.headers))
            + "}"
        )
        url = self.url if self.kind == "api" else "<redacted>"
        return (
            "UploadTarget("
            f"upload_id={self.upload_id!r}, url={url}, method={self.method!r}, "
            f"expires_at={self.expires_at!r}, kind={self.kind!r}, "
            f"headers={headers})"
        )


@dataclass(frozen=True, slots=True)
class UploadResult:
    """A completed upload and the file format ingest resolved for its bytes."""

    upload: Upload
    artifact_type: ArtifactTypeKey | None = None


class ByteReader(Protocol):
    """The only stream shape receiving upload bytes needs."""

    def read(self, size: int = -1, /) -> bytes: ...


@final
class _LimitedReader:
    """Stream adapter that fails once one upload exceeds its byte limit."""

    def __init__(self, stream: ByteReader, max_bytes: int, label: str) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self._label = label
        self._byte_count = 0

    def read(self, size: int = -1, /) -> bytes:
        chunk = self._stream.read(size)
        self._byte_count += len(chunk)
        if self._byte_count > self._max_bytes:
            raise UploadTooLargeError(
                f"Upload {self._label!r} exceeds the upload limit of "
                f"{self._max_bytes} bytes"
            )
        return chunk


class UploadService:
    """Reserve, validate, and promote uploaded files without a queue."""

    def __init__(
        self,
        *,
        config: UploadServiceConfig,
        storage: FileStoragePort,
        unit_of_work_factory: Callable[[], UploadUnitOfWorkPort],
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec],
        extension_claims: Mapping[str, ArtifactTypeKey],
        bucket: str,
        storage_backend: str,
        presigning: PresigningStorage | None = None,
    ) -> None:
        self._config = config
        self._storage = storage
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_types = artifact_types
        self._extension_claims = extension_claims
        self._bucket = bucket
        self._storage_backend = storage_backend
        self._presigning = presigning
        self._upload_route_prefix = config.upload_route_prefix.rstrip("/")

    @classmethod
    def from_config(
        cls,
        config: UploadServiceConfig,
        *,
        storage: FileStoragePort,
        unit_of_work_factory: Callable[[], UploadUnitOfWorkPort],
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec],
        extension_claims: Mapping[str, ArtifactTypeKey],
        bucket: str,
        storage_backend: str,
        presigning: PresigningStorage | None = None,
    ) -> Self:
        return cls(
            config=config,
            storage=storage,
            unit_of_work_factory=unit_of_work_factory,
            artifact_types=artifact_types,
            extension_claims=extension_claims,
            bucket=bucket,
            storage_backend=storage_backend,
            presigning=presigning,
        )

    @property
    def accepts_direct_upload(self) -> bool:
        """Whether this deployment receives bytes on its own content route."""

        return self._presigning is None

    @property
    def max_upload_bytes(self) -> int:
        return self._config.max_upload_bytes

    async def create_upload(
        self,
        *,
        workspace_id: UUID,
        created_by_user_id: UUID | None,
        filename: str,
        byte_size: int,
        content_type: str | None = None,
    ) -> UploadTarget:
        upload_id = uuid4()
        record = Upload(
            workspace_id=workspace_id,
            upload_id=upload_id,
            original_filename=filename,
            bucket=self._bucket,
            object_key=self._object_key(upload_id),
            expected_size=byte_size,
            content_type=(content_type or guess_type(filename)[0])
            or "application/octet-stream",
            created_by_user_id=created_by_user_id,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.uploads.add(record)
            await unit_of_work.commit()

        expires_at = record.created_at + self._config.upload_target_ttl
        if self._presigning is None:
            return UploadTarget(
                upload_id=upload_id,
                url=(
                    f"{self._upload_route_prefix}/workspaces/{record.workspace_id}"
                    f"/uploads/{record.upload_id}/content"
                ),
                method="PUT",
                expires_at=expires_at,
                kind="api",
                headers={},
            )

        signed = await self._presigning.create_presigned_upload(
            record.bucket,
            record.object_key,
            expires_in=self._config.upload_target_ttl,
        )
        return UploadTarget(
            upload_id=upload_id,
            url=signed.url,
            method=signed.method,
            expires_at=signed.expires_at,
            kind="storage",
            headers=dict(signed.required_headers),
        )

    async def receive_content(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        stream: ReadableStream,
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
            stream=_LimitedReader(
                stream,
                self._config.max_upload_bytes,
                record.original_filename,
            ),
            content_type=record.content_type or "application/octet-stream",
            metadata={"original_filename": record.original_filename},
        )
        try:
            _ = await self._storage.save(command)
        except UploadTooLargeError:
            # Local create-only writes clean their own temps. Do not delete the
            # destination: another writer may have published successfully.
            raise

    async def complete_upload(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
    ) -> UploadResult:
        record = await self._load_upload(workspace_id, upload_id)
        if record.status is UploadStatus.READY:
            return self._result_from_ready(record)
        if record.status is not UploadStatus.PENDING:
            raise UploadStateError(
                f"Upload {upload_id} is {record.status.value} and cannot be used"
            )
        if self._is_past_lifetime(record):
            await self._mark_terminal(record, UploadStatus.EXPIRED)
            raise UploadExpiredError(
                f"Upload {record.original_filename!r} expired before it was used"
            )

        stored = await self._storage.stat(record.bucket, record.object_key)
        if stored is None:
            await self._mark_terminal(record, UploadStatus.FAILED)
            raise UploadStateError(
                f"Upload {record.original_filename!r} has no stored bytes"
            )
        if stored.byte_size > self._config.max_upload_bytes:
            await self._mark_terminal(record, UploadStatus.FAILED)
            raise UploadTooLargeError(
                f"Upload {record.original_filename!r} exceeds the upload limit of "
                f"{self._config.max_upload_bytes} bytes"
            )

        try:
            inspection = await inspect_upload_async(
                storage=self._storage,
                bucket=record.bucket,
                object_key=record.object_key,
                original_filename=record.original_filename,
                expected_size=record.expected_size,
                max_upload_bytes=self._config.max_upload_bytes,
                artifact_types=self._artifact_types,
                extension_claims=self._extension_claims,
                declared_byte_size=stored.byte_size,
            )
        except FileFormatMismatchError:
            await self._mark_terminal(record, UploadStatus.FAILED)
            raise
        except UploadInspectionError as exc:
            await self._mark_terminal(record, UploadStatus.FAILED)
            message = str(exc)
            if "exceeds the upload limit" in message:
                raise UploadTooLargeError(message) from exc
            if "declared" in message and "were stored" in message:
                raise UploadStateError(message) from exc
            raise UploadStateError(message) from exc

        key = inspection.artifact_type
        artifact = ArtifactObject(
            workspace_id=workspace_id,
            artifact_type=key.id,
            schema_version=key.schema_version,
            content_type=record.content_type or "application/octet-stream",
            storage_backend=self._storage_backend,
            bucket=record.bucket,
            object_key=record.object_key,
            byte_size=inspection.byte_size,
            sha256=inspection.sha256,
            metadata={"original_filename": record.original_filename},
        )
        completed_at = datetime.now(UTC)
        not_older_than = datetime.now(UTC) - self._config.upload_lifetime
        async with self._unit_of_work_factory() as unit_of_work:
            # Insert the artifact first so the upload row's foreign key is valid
            # in the same transaction. A losing finalize rolls both writes back.
            await unit_of_work.artifacts.add(artifact)
            finalized = await unit_of_work.uploads.finalize_if_pending(
                workspace_id,
                upload_id,
                actual_size=inspection.byte_size,
                sha256=inspection.sha256,
                artifact_type=key.id,
                artifact_schema_version=key.schema_version,
                artifact_id=artifact.id,
                completed_at=completed_at,
                not_older_than=not_older_than,
            )
            if finalized is not None:
                await unit_of_work.commit()
                return UploadResult(upload=finalized, artifact_type=key)

            current = await unit_of_work.uploads.get(workspace_id, upload_id)
            await unit_of_work.rollback()

        if current is not None and current.status is UploadStatus.READY:
            return self._result_from_ready(current)
        if current is not None and current.status is UploadStatus.EXPIRED:
            raise UploadExpiredError(
                f"Upload {record.original_filename!r} expired before it was used"
            )
        raise UploadStateError(
            f"Upload {record.original_filename!r} is no longer pending"
        )

    async def cleanup_abandoned(
        self,
        *,
        older_than: timedelta | None = None,
        limit: int = 500,
    ) -> int:
        """Expire abandoned uploads and retry deletion of terminal tracking rows.

        Storage IO runs outside database transactions. A failed object delete
        keeps the terminal row so a later sweep can retry. READY uploads are
        never deleted.
        """

        resolved_older_than = (
            self._config.upload_lifetime if older_than is None else older_than
        )
        now = datetime.now(UTC)
        pending_before = now - resolved_older_than
        # Retain terminal rows until the signed target and any in-flight receive
        # window have both elapsed, so a late PUT cannot recreate orphan bytes.
        # An explicit shorter ``older_than`` (tests/maintenance) may tighten that
        # grace so reclaim stays useful when the caller asks for immediate sweep.
        deletion_grace = self._config.upload_target_ttl + self._config.upload_receive_timeout
        if older_than is not None and older_than < deletion_grace:
            deletion_grace = older_than
        terminal_before = now - deletion_grace
        async with self._unit_of_work_factory() as unit_of_work:
            candidates = await unit_of_work.uploads.list_cleanup_candidates(
                pending_before=pending_before,
                terminal_before=terminal_before,
                limit=limit,
            )

        discarded = 0
        for record in candidates:
            try:
                terminal = record
                if record.status is UploadStatus.PENDING:
                    marked = await self._mark_terminal(record, UploadStatus.EXPIRED)
                    if marked is None:
                        continue
                    terminal = marked
                if terminal.status is UploadStatus.READY:
                    continue
                if terminal.created_at >= terminal_before:
                    continue
                await self._delete_stored_object(terminal)
                async with self._unit_of_work_factory() as unit_of_work:
                    removed = await unit_of_work.uploads.delete_terminal(
                        terminal.workspace_id,
                        terminal.upload_id,
                    )
                    await unit_of_work.commit()
                if removed:
                    discarded += 1
            except Exception as error:
                logger.warning(
                    "upload_cleanup_failed operation=cleanup_abandoned "
                    "workspace_id=%s upload_id=%s error_class=%s",
                    record.workspace_id,
                    record.upload_id,
                    type(error).__name__,
                )
                continue

        if isinstance(self._storage, LocalFileObjectStore):
            _ = self._storage.cleanup_stale_temp_files(
                older_than=self._config.upload_receive_timeout,
                now=now,
            )
        return discarded

    async def _load_upload(self, workspace_id: UUID, upload_id: UUID) -> Upload:
        async with self._unit_of_work_factory() as unit_of_work:
            record = await unit_of_work.uploads.get(workspace_id, upload_id)
        if record is None:
            raise UploadNotFoundError(
                f"Upload {upload_id} was not found in workspace {workspace_id}"
            )
        return record

    async def _require_pending(self, workspace_id: UUID, upload_id: UUID) -> Upload:
        record = await self._load_upload(workspace_id, upload_id)
        if record.status is UploadStatus.READY:
            raise UploadStateError(f"Upload {upload_id} is already complete")
        if record.status is not UploadStatus.PENDING:
            raise UploadStateError(
                f"Upload {upload_id} is {record.status.value} and cannot be used"
            )
        if self._is_past_lifetime(record):
            await self._mark_terminal(record, UploadStatus.EXPIRED)
            raise UploadExpiredError(
                f"Upload {record.original_filename!r} expired before it was used"
            )
        if datetime.now(UTC) > record.created_at + self._config.upload_target_ttl:
            raise UploadExpiredError(
                f"Upload {record.original_filename!r} expired before it was used"
            )
        return record

    def _is_past_lifetime(self, record: Upload) -> bool:
        return datetime.now(UTC) - record.created_at > self._config.upload_lifetime

    async def _mark_terminal(
        self,
        record: Upload,
        status: UploadStatus,
    ) -> Upload | None:
        async with self._unit_of_work_factory() as unit_of_work:
            updated = await unit_of_work.uploads.mark_terminal_if_pending(
                record.workspace_id,
                record.upload_id,
                status=status,
            )
            if updated is not None:
                await unit_of_work.commit()
            else:
                await unit_of_work.rollback()
            return updated

    async def _delete_stored_object(self, record: Upload) -> None:
        try:
            await self._storage.delete(record.bucket, record.object_key)
        except FileNotFoundError:
            return

    def _result_from_ready(self, record: Upload) -> UploadResult:
        if (
            record.artifact_type is None
            or record.artifact_schema_version is None
            or record.artifact_id is None
        ):
            raise UploadStateError(
                f"Upload {record.upload_id} is ready without an artifact association"
            )
        return UploadResult(
            upload=record,
            artifact_type=ArtifactTypeKey(
                record.artifact_type,
                record.artifact_schema_version,
            ),
        )

    def _object_key(self, upload_id: UUID) -> str:
        return f"objects/{upload_id}"


__all__ = [
    "ByteReader",
    "FileFormatMismatchError",
    "PresignedUploadTarget",
    "PresigningStorage",
    "UploadExpiredError",
    "UploadNotFoundError",
    "UploadResult",
    "UploadService",
    "UploadServiceConfig",
    "UploadStateError",
    "UploadTarget",
    "UploadTooLargeError",
    "UploadTransportUnsupportedError",
]
