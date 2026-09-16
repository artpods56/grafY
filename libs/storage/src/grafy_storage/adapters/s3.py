import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, cast, final, override
from urllib.parse import urlsplit

import botocore.session
from botocore.client import BaseClient, Config
from obstore.exceptions import AlreadyExistsError
from obstore.store import S3Store

from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.ports.storage import (
    ChunkReader,
    FileStoragePort,
    FileStreamProtocol,
    PresignedUploadTarget,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)

if TYPE_CHECKING:
    from obstore.store import ClientConfig, S3Config

_IF_NONE_MATCH = "*"
_REQUIRED_UPLOAD_HEADERS = {"If-None-Match": _IF_NONE_MATCH}


@final
class S3ObjectStore(FileStoragePort):
    def __init__(
        self,
        endpoint_url: str | None,
        region: str,
        access_key_id: str | None,
        secret_access_key: str | None,
        force_path_style: bool,
        *,
        signing_endpoint_url: str | None = None,
    ) -> None:
        self._stores: dict[str, S3Store] = {}
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._force_path_style = force_path_style
        self._endpoint_url = endpoint_url
        self._signing_endpoint_url = (
            signing_endpoint_url
            if signing_endpoint_url not in (None, "")
            else endpoint_url
        )
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
        self._signer_client: BaseClient | None = None

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
    async def open_chunks(self, bucket: str, path: str) -> ChunkReader:
        try:
            result = await self._store_for(bucket).get_async(path)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Stored object does not exist: {bucket}/{path}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Could not open stored object chunks: {bucket}/{path}"
            ) from exc
        return _S3ChunkReader(result)

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
    ) -> PresignedUploadTarget:
        """Sign a create-only client PUT whose condition is part of the signature."""

        if expires_in <= timedelta(0):
            raise ValueError("Presigned upload lifetime must be positive")
        expires_seconds = int(expires_in.total_seconds())
        if expires_seconds < 1:
            raise ValueError("Presigned upload lifetime must be at least one second")

        url = await asyncio.to_thread(
            self._sign_conditional_put,
            bucket,
            path,
            expires_seconds,
        )
        return PresignedUploadTarget(
            url=url,
            method="PUT",
            expires_at=datetime.now(UTC) + expires_in,
            required_headers=dict(_REQUIRED_UPLOAD_HEADERS),
        )

    def _sign_conditional_put(
        self,
        bucket: str,
        path: str,
        expires_seconds: int,
    ) -> str:
        client = self._botocore_signer()
        return client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": path,
                "IfNoneMatch": _IF_NONE_MATCH,
            },
            ExpiresIn=expires_seconds,
            HttpMethod="PUT",
        )

    def _botocore_signer(self) -> BaseClient:
        if self._signer_client is not None:
            return self._signer_client
        session = botocore.session.get_session()
        self._signer_client = session.create_client(
            "s3",
            region_name=self._region,
            endpoint_url=self._signing_endpoint_url,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if self._force_path_style else "auto"},
            ),
        )
        return self._signer_client

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


@final
class _S3ChunkReader:
    def __init__(self, result: object) -> None:
        self._result = result
        stream = getattr(result, "stream")(1024 * 1024)
        self._chunks: Iterator[object] = iter(stream)
        self._pending = b""
        self._closed = False

    def read(self, size: int = -1, /) -> bytes:
        if self._closed:
            raise ValueError("I/O operation on closed chunk reader")
        if size == 0:
            return b""
        if size < 0:
            parts = [self._pending]
            self._pending = b""
            for chunk in self._chunks:
                parts.append(bytes(chunk))
            return b"".join(parts)

        while len(self._pending) < size:
            try:
                chunk = next(self._chunks)
            except StopIteration:
                break
            self._pending += bytes(chunk)
        out = self._pending[:size]
        self._pending = self._pending[size:]
        return out

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pending = b""
        closer = getattr(self._result, "close", None)
        if callable(closer):
            closer()
