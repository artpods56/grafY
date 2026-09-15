import asyncio
from datetime import timedelta
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, cast, final, override
from urllib.parse import urlsplit

from obstore import sign_async
from obstore.exceptions import AlreadyExistsError
from obstore.store import S3Store

from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.ports.storage import (
    FileStoragePort,
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)

if TYPE_CHECKING:
    from obstore.store import ClientConfig, S3Config


@final
class S3ObjectStore(FileStoragePort):
    def __init__(
        self,
        endpoint_url: str | None,
        region: str,
        access_key_id: str | None,
        secret_access_key: str | None,
        force_path_style: bool,
    ) -> None:
        self._stores: dict[str, S3Store] = {}
        self._config: S3Config = {
            "region": region,
            "virtual_hosted_style_request": not force_path_style,
        }
        if endpoint_url is not None:
            self._config["endpoint"] = endpoint_url
        if access_key_id is not None:
            self._config["access_key_id"] = access_key_id
        if secret_access_key is not None:
            self._config["secret_access_key"] = secret_access_key

        self._client_options: ClientConfig | None = (
            {"allow_http": True}
            if endpoint_url is not None and urlsplit(endpoint_url).scheme == "http"
            else None
        )

    @override
    async def save(self, command: SaveFileCommand) -> StoredFile:
        return await asyncio.to_thread(self._save_sync, command)

    @override
    async def move(self, bucket: str, source_path: str, destination_path: str) -> None:
        await asyncio.to_thread(self._move_sync, bucket, source_path, destination_path)

    @override
    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        return await asyncio.to_thread(self._load_sync, bucket, path)

    @override
    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        try:
            metadata = await self._store_for(bucket).head_async(path)
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise RuntimeError(
                f"Could not stat stored object: {bucket}/{path}"
            ) from exc

        return StoredObjectInfo(
            bucket=bucket,
            path=path,
            byte_size=metadata["size"],
            etag=metadata["e_tag"],
            version_id=metadata["version"],
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

        try:
            content = await self._store_for(bucket).get_range_async(
                path,
                start=start,
                end=end_exclusive,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Stored object does not exist: {bucket}/{path}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                "Could not load stored object byte range "
                f"{bucket}/{path}[{start}:{end_exclusive}]"
            ) from exc
        return bytes(content)

    @override
    async def delete(self, bucket: str, path: str) -> None:
        await self._store_for(bucket).delete_async(path)

    async def create_presigned_upload(
        self,
        bucket: str,
        path: str,
        *,
        expires_in: timedelta,
    ) -> str:
        """Sign a direct client PUT for one server-chosen object key."""

        signed = await sign_async(
            self._store_for(bucket),
            "PUT",
            path,
            expires_in,
        )
        return signed

    def _save_sync(self, command: SaveFileCommand) -> StoredFile:
        digest = sha256()
        byte_size = 0
        attributes: dict[str, str] = {}
        for key, value in command.metadata.items():
            if isinstance(value, str):
                attributes[key] = value
        attributes["Content-Type"] = command.content_type

        with SpooledTemporaryFile(max_size=32 * 1024 * 1024) as temp:
            while chunk := command.stream.read(1024 * 1024):
                digest.update(chunk)
                byte_size += len(chunk)
                _ = temp.write(chunk)
            _ = temp.seek(0)
            try:
                result = self._store_for(command.bucket).put(
                    command.path,
                    temp,
                    attributes=attributes,
                    mode="overwrite" if command.allow_overwrite else "create",
                )
            except AlreadyExistsError as exc:
                raise ObjectAlreadyExistsError(
                    f"File already exists: {command.bucket}/{command.path}"
                ) from exc

        return StoredFile(
            bucket=command.bucket,
            path=command.path,
            etag=result.get("e_tag"),
            version_id=result.get("version"),
            byte_size=byte_size,
            sha256=digest.hexdigest(),
        )

    def _move_sync(self, bucket: str, source_path: str, destination_path: str) -> None:
        store = self._store_for(bucket)
        source_exists = self._file_exists(store, source_path)
        destination_exists = self._file_exists(store, destination_path)
        if not source_exists and destination_exists:
            return
        if not source_exists:
            raise FileNotFoundError(
                f"Source file does not exist: {bucket}/{source_path}"
            )

        store.copy(source_path, destination_path, overwrite=True)
        store.delete(source_path)

    def _load_sync(self, bucket: str, path: str) -> FileStreamProtocol:
        response = self._store_for(bucket).get(path)
        temp = SpooledTemporaryFile(max_size=32 * 1024 * 1024)  # noqa: SIM115
        try:
            for chunk in response:
                _ = temp.write(chunk)
            _ = temp.seek(0)
            return cast(FileStreamProtocol, cast(object, temp))
        except Exception:
            temp.close()
            raise

    def _file_exists(self, store: S3Store, path: str) -> bool:
        try:
            _ = store.head(path)
        except FileNotFoundError:
            return False
        return True

    def _store_for(self, bucket: str) -> S3Store:
        if bucket not in self._stores:
            self._stores[bucket] = S3Store(
                bucket,
                config=self._config,
                client_options=self._client_options,
            )
        return self._stores[bucket]
