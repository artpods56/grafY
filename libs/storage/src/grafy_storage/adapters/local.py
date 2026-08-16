import os
import shutil
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import final, override

from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.ports.storage import (
    FileStoragePort,
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)


@final
class LocalFileObjectStore(FileStoragePort):
    def __init__(self, root: Path):
        self._root = root

    @override
    async def save(self, command: SaveFileCommand) -> StoredFile:
        path = self._path_for(command.bucket, command.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256()
        byte_size = 0
        temp_path: Path | None = None

        try:
            with NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.tmp-",
                delete=False,
            ) as target:
                temp_path = Path(target.name)
                while chunk := command.stream.read(1024 * 1024):
                    digest.update(chunk)
                    byte_size += len(chunk)
                    _ = target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

            if command.allow_overwrite:
                os.replace(temp_path, path)
                temp_path = None
            else:
                try:
                    # Linking publishes the fully written inode only when the
                    # destination is still absent, without a check-then-write race.
                    os.link(temp_path, path)
                except FileExistsError as exc:
                    raise ObjectAlreadyExistsError(
                        f"File already exists: {command.bucket}/{command.path}"
                    ) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass

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
            raise FileNotFoundError(f"Source file does not exist: {bucket}/{source_path}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.move(str(source), str(destination))

    @override
    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        return self._path_for(bucket, path).open("rb")

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

    @override
    def exists(self, bucket: str, path: str) -> bool:
        return self._path_for(bucket, path).is_file()

    def _path_for(self, bucket: str, key: str) -> Path:
        _validate_segment(bucket)
        _validate_key(key)
        return self._root / bucket / Path(*PurePosixPath(key).parts)


def _validate_segment(segment: str) -> None:
    if not segment or "/" in segment or "\\" in segment or segment in {".", ".."}:
        raise ValueError(f"Unsafe storage segment: {segment}")


def _validate_key(key: str) -> None:
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise ValueError(f"Unsafe object key: {key}")
#
