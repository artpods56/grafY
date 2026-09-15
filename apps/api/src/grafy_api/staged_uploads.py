import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.file_contracts import BLOB_FILE
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.staged_uploads import StagedUploadUnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort, SaveFileCommand
from grafy_core.staged_upload_paths import resolve_staged_upload_path
from PIL import Image as ImageModule
from PIL import ImageDraw
from starlette.concurrency import run_in_threadpool

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.settings import STAGED_UPLOAD_HARD_MAX_BYTES

_SAMPLE_PAGE_TEXTS = (
    "PAGE {index}\nParochia Sancti Floriani\nAnno Domini 1846",
    "PAGE {index}\nBaptisatorum liber\nVilla Nova, folio {index}",
    "PAGE {index}\nIndex nominum\nSeries continua",
)


class StagedUploadTooLargeError(WorkbenchOperationError):
    """A staged file exceeds the configured per-upload byte limit."""


class FileFormatMismatchError(WorkbenchOperationError):
    """A known extension's bytes disagree with the format that extension names."""

    def __init__(self, filename: str, expected: str) -> None:
        super().__init__(
            f"{filename!r} does not look like a {expected} file. "
            "Rename it or convert it, then try again."
        )


@dataclass(frozen=True, slots=True)
class StagedUploadResult:
    """A staged upload and the file format ingest resolved for its bytes."""

    upload: StagedUpload
    artifact_type: ArtifactTypeKey | None = None


class StagedUploadService:
    """Stages opaque file uploads and resolves each one to a file artifact."""

    def __init__(
        self,
        uploads_dir: Path,
        unit_of_work_factory: Callable[[], StagedUploadUnitOfWorkPort],
        artifact_unit_of_work: UnitOfWorkPort | None = None,
        storage: FileStoragePort | None = None,
        artifact_types: Mapping[tuple[str, int], ArtifactTypeSpec] | None = None,
        extension_claims: Mapping[str, ArtifactTypeKey] | None = None,
        artifact_bucket: str = "workbench-artifacts",
        artifact_storage_backend: str = "local",
        *,
        max_upload_bytes: int = STAGED_UPLOAD_HARD_MAX_BYTES,
    ) -> None:
        if max_upload_bytes < 1:
            raise ValueError("Staged upload byte limit must be positive")
        if max_upload_bytes > STAGED_UPLOAD_HARD_MAX_BYTES:
            raise ValueError(
                "Staged upload byte limit must not exceed the 64 MiB hard limit"
            )
        self._uploads_dir = uploads_dir.expanduser().resolve()
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_unit_of_work = artifact_unit_of_work
        self._storage = storage
        self._artifact_types = artifact_types or {}
        self._extension_claims = extension_claims or {}
        self._artifact_bucket = artifact_bucket
        self._artifact_storage_backend = artifact_storage_backend
        self._max_upload_bytes = max_upload_bytes

    async def save_upload(
        self,
        *,
        workspace_id: UUID,
        created_by_user_id: UUID,
        filename: str,
        stream: BinaryIO,
    ) -> StagedUploadResult:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "upload"
        upload_key = f"{uuid4().hex[:8]}-{safe_name}"
        path = self._path_for(workspace_id, upload_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await run_in_threadpool(self._write_stream, path, stream, filename)
        except StagedUploadTooLargeError:
            path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise WorkbenchOperationError(
                f"Failed to stage upload {filename!r} in {path.parent}"
            ) from exc
        try:
            item = StagedUpload(
                workspace_id=workspace_id,
                created_by_user_id=created_by_user_id,
                upload_key=upload_key,
                original_filename=filename,
                byte_size=path.stat().st_size,
            )
            artifact_type = await self._write_artifact(workspace_id, item, path)
            await self._persist_staged_uploads([item])
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return StagedUploadResult(upload=item, artifact_type=artifact_type)

    async def _write_artifact(
        self,
        workspace_id: UUID,
        item: StagedUpload,
        path: Path,
    ) -> ArtifactTypeKey | None:
        if self._artifact_unit_of_work is None or self._storage is None:
            return None
        content = path.read_bytes()
        key = self._resolve_artifact_type(item.original_filename, content)
        content_type = guess_type(item.original_filename)[0] or (
            "application/octet-stream"
        )
        digest = sha256(content).hexdigest()
        stored = await self._storage.save(
            SaveFileCommand(
                bucket=self._artifact_bucket,
                path=f"uploads/{workspace_id}/{item.upload_key}",
                stream=BytesIO(content),
                content_type=content_type,
                metadata={
                    "original_filename": item.original_filename,
                    "artifact_kind": key.id,
                    "sha256": digest,
                },
            )
        )
        artifact = ArtifactObject(
            workspace_id=workspace_id,
            artifact_type=key.id,
            schema_version=key.schema_version,
            content_type=content_type,
            storage_backend=self._artifact_storage_backend,
            bucket=self._artifact_bucket,
            object_key=stored.path,
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            metadata={"original_filename": item.original_filename},
        )
        async with self._artifact_unit_of_work as unit_of_work:
            await unit_of_work.artifacts.add(artifact)
            await unit_of_work.commit()
        return key

    def _resolve_artifact_type(
        self,
        filename: str,
        content: bytes,
    ) -> ArtifactTypeKey:
        extension = Path(filename).suffix[1:].casefold()
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
        if not spec.confirmation_rule.confirms(content):
            expected = key.id.removeprefix("file.").upper()
            raise FileFormatMismatchError(filename, expected)
        return key

    async def create_sample_images(
        self,
        *,
        workspace_id: UUID,
        created_by_user_id: UUID,
        count: int,
    ) -> list[StagedUpload]:
        items: list[StagedUpload] = []
        paths: list[Path] = []
        try:
            for index in range(count):
                text = _SAMPLE_PAGE_TEXTS[index % len(_SAMPLE_PAGE_TEXTS)].format(
                    index=index + 1
                )
                image = ImageModule.new("RGB", (420, 300), color="#f5f0e6")
                draw = ImageDraw.Draw(image)
                draw.rectangle((12, 12, 407, 287), outline="#b9ad98")
                draw.multiline_text((36, 48), text, fill="#463c2e", spacing=14)
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                content = buffer.getvalue()
                upload_key = f"{uuid4().hex[:8]}-sample-page.png"
                path = self._path_for(workspace_id, upload_key)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                paths.append(path)
                items.append(
                    StagedUpload(
                        workspace_id=workspace_id,
                        created_by_user_id=created_by_user_id,
                        upload_key=upload_key,
                        original_filename=f"sample-page-{index + 1}.png",
                        byte_size=len(content),
                    )
                )
            await self._persist_staged_uploads(items)
        except Exception:
            for path in paths:
                path.unlink(missing_ok=True)
            raise
        return items

    def _path_for(self, workspace_id: UUID, upload_key: str) -> Path:
        return resolve_staged_upload_path(
            self._uploads_dir,
            workspace_id=workspace_id,
            upload_key=upload_key,
        )

    async def _persist_staged_uploads(self, items: list[StagedUpload]) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            for item in items:
                await unit_of_work.staged_uploads.add(item)
            await unit_of_work.commit()

    def _write_stream(self, path: Path, stream: BinaryIO, filename: str) -> None:
        byte_size = 0
        with path.open("xb") as destination:
            while chunk := stream.read(1024 * 1024):
                byte_size += len(chunk)
                if byte_size > self._max_upload_bytes:
                    raise StagedUploadTooLargeError(
                        f"Upload {filename!r} exceeds the staged-upload limit of "
                        f"{self._max_upload_bytes} bytes"
                    )
                destination.write(chunk)


__all__ = [
    "FileFormatMismatchError",
    "StagedUploadResult",
    "StagedUploadService",
    "StagedUploadTooLargeError",
]
