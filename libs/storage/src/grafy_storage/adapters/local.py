import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import IO, final, override

from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.ports.storage import (
    ChunkReader,
    FileStoragePort,
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)

_TEMP_NAME_PREFIX = "."
_TEMP_NAME_MARKER = ".tmp-"


@final
class LocalFileObjectStore(FileStoragePort):
    def __init__(self, root: Path):
        self._root = root

    @override
    async def save(self, command: SaveFileCommand) -> StoredFile:
        path = self._path_for(command.bucket, command.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(
            f"{_TEMP_NAME_PREFIX}{path.name}{_TEMP_NAME_MARKER}"
            f"{os.getpid()}-{uuid.uuid4().hex}"
        )
        digest = sha256()
        byte_size = 0

        try:
            with temp_path.open("wb") as target:
                while chunk := command.stream.read(1024 * 1024):
                    digest.update(chunk)
                    byte_size += len(chunk)
                    _ = target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

            if command.allow_overwrite:
                os.replace(temp_path, path)
            else:
                _publish_create_only(temp_path, path, command.bucket, command.path)
                temp_path.unlink(missing_ok=True)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return StoredFile(
            bucket=command.bucket,
            path=command.path,
            etag=None,
            version_id=None,
            byte_size=byte_size,
            sha256=digest.hexdigest(),
        )

    @override
    async def move(self, bucket: str, source_path: str, destination_path: str) -> None:
        source = self._path_for(bucket, source_path)
        destination = self._path_for(bucket, destination_path)
        if not source.exists() and destination.exists():
            return
        if not source.exists():
            raise FileNotFoundError(
                f"Source file does not exist: {bucket}/{source_path}"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.move(str(source), str(destination))

    @override
    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        return self._path_for(bucket, path).open("rb")

    @override
    async def open_chunks(self, bucket: str, path: str) -> ChunkReader:
        return _LocalChunkReader(self._path_for(bucket, path).open("rb"))

    @override
    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        file_path = self._path_for(bucket, path)
        try:
            object_stat = file_path.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise OSError(f"Could not stat stored object: {bucket}/{path}") from exc

        if not file_path.is_file():
            return None
        return StoredObjectInfo(
            bucket=bucket,
            path=path,
            byte_size=object_stat.st_size,
            etag=None,
            version_id=None,
        )

    @override
    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        if start < 0 or end_exclusive < 0:
            raise ValueError(
                "Storage byte range bounds must be nonnegative: "
                f"start={start}, end_exclusive={end_exclusive}"
            )
        if end_exclusive < start:
            raise ValueError(
                "Storage byte range end must not precede start: "
                f"start={start}, end_exclusive={end_exclusive}"
            )
        if end_exclusive == start:
            return b""

        file_path = self._path_for(bucket, path)
        try:
            with file_path.open("rb") as source:
                _ = source.seek(start)
                return source.read(end_exclusive - start)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Stored object does not exist: {bucket}/{path}"
            ) from exc
        except OSError as exc:
            raise OSError(
                "Could not load stored object byte range "
                f"{bucket}/{path}[{start}:{end_exclusive}]"
            ) from exc

    @override
    async def delete(self, bucket: str, path: str) -> None:
        file_path = self._path_for(bucket, path)
        if file_path.exists():
            file_path.unlink()

    def cleanup_stale_temp_files(
        self,
        *,
        older_than: timedelta,
        now: datetime | None = None,
    ) -> int:
        """Remove abandoned local write temps that no longer have an active writer.

        Only names this adapter creates are eligible. The age bound must exceed
        the longest permitted upload receive window so an in-flight writer is
        never deleted.
        """

        if older_than <= timedelta(0):
            raise ValueError("Stale temporary-file age must be positive")
        cutoff = (now or datetime.now(UTC)) - older_than
        removed = 0
        if not self._root.exists():
            return 0
        for path in self._root.rglob(f"{_TEMP_NAME_PREFIX}*{_TEMP_NAME_MARKER}*"):
            if not path.is_file() or _TEMP_NAME_MARKER not in path.name:
                continue
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if modified >= cutoff:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            removed += 1
        return removed

    def _path_for(self, bucket: str, key: str) -> Path:
        _validate_segment(bucket)
        _validate_key(key)
        return self._root / bucket / Path(*PurePosixPath(key).parts)


def _publish_create_only(
    temp_path: Path,
    destination: Path,
    bucket: str,
    object_path: str,
) -> None:
    """Atomically publish ``temp_path`` only when ``destination`` is absent.

    Never deletes ``destination``. A losing writer cleans up only its own temp.
    """

    try:
        os.link(temp_path, destination)
        return
    except FileExistsError as exc:
        raise ObjectAlreadyExistsError(
            f"File already exists: {bucket}/{object_path}"
        ) from exc
    except OSError:
        pass

    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(destination, flags, 0o644)
    except FileExistsError as exc:
        raise ObjectAlreadyExistsError(
            f"File already exists: {bucket}/{object_path}"
        ) from exc
    try:
        with os.fdopen(fd, "wb") as destination_file, temp_path.open("rb") as source:
            shutil.copyfileobj(source, destination_file)
            destination_file.flush()
            os.fsync(destination_file.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise


@final
class _LocalChunkReader:
    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream

    def read(self, size: int = -1, /) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()


def _validate_segment(segment: str) -> None:
    if not segment or "/" in segment or "\\" in segment or segment in {".", ".."}:
        raise ValueError(f"Unsafe storage segment: {segment}")


def _validate_key(key: str) -> None:
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise ValueError(f"Unsafe object key: {key}")
