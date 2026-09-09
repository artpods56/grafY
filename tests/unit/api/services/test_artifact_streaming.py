import asyncio
from io import BytesIO
from typing import cast
from uuid import UUID

import pytest

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.v1.routes.artifacts.services import (
    ARTIFACT_RESPONSE_CHUNK_SIZE,
    BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES,
    ArtifactResponseTooLargeError,
    ArtifactContentRead,
    ArtifactService,
)
from grafy_core.artifact_collections import JSON_COLLECTIONS_STORAGE_FORMAT
from grafy_core.artifacts import ArtifactObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.table_contracts import TABLE_DATA
from grafy_core.ports.storage import FileStoragePort, StoredObjectInfo


class TrackingStream(BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int | None] = []
        self.closed_by_response = False

    def read(self, size: int | None = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)

    def close(self) -> None:
        self.closed_by_response = True
        super().close()


class TrackingStorage:
    def __init__(self, content: bytes) -> None:
        self.stream = TrackingStream(content)
        self.load_calls = 0

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo:
        return StoredObjectInfo(
            bucket=bucket,
            path=path,
            byte_size=len(self.stream.getvalue()),
            etag=None,
            version_id=None,
        )

    async def load(self, bucket: str, path: str) -> TrackingStream:
        self.load_calls += 1
        return self.stream


async def _consume(content: ArtifactContentRead) -> bytes:
    return b"".join([chunk async for chunk in content.chunks()])


def test_stored_artifact_content_streams_fixed_chunks_and_closes_source() -> None:
    expected = b"x" * (ARTIFACT_RESPONSE_CHUNK_SIZE + 17)
    storage = TrackingStorage(expected)
    unit_of_work = InMemoryUnitOfWork()
    service = ArtifactService(
        unit_of_work,
        cast(FileStoragePort, storage),
        availability=ArtifactAvailability(unit_of_work, cast(FileStoragePort, storage)),
    )
    artifact = ArtifactObject(
        workspace_id=UUID("00000000-0000-0000-0000-000000000007"),
        artifact_type="image.raster",
        schema_version=1,
        content_type="image/png",
        bucket="artifacts",
        object_key="images/large.png",
        byte_size=len(expected),
    )

    async def read_and_close() -> bytes:
        content = await service.open_content(artifact)
        try:
            assert content.content_length == len(expected)
            return await _consume(content)
        finally:
            await service.close()

    assert asyncio.run(read_and_close()) == expected
    assert storage.load_calls == 1
    assert storage.stream.read_sizes
    assert set(storage.stream.read_sizes) == {ARTIFACT_RESPONSE_CHUNK_SIZE}
    assert storage.stream.closed_by_response


@pytest.mark.parametrize(
    ("artifact_type", "schema_version", "metadata"),
    [
        (TABLE_DATA.key.id, TABLE_DATA.key.schema_version, {}),
        (
            "geo.feature_collection",
            1,
            {"storage_format": JSON_COLLECTIONS_STORAGE_FORMAT},
        ),
    ],
)
def test_buffered_reconstruction_is_rejected_before_loading_storage(
    artifact_type: str,
    schema_version: int,
    metadata: dict[str, object],
) -> None:
    storage = TrackingStorage(b"manifest must not be loaded")
    unit_of_work = InMemoryUnitOfWork()
    service = ArtifactService(
        unit_of_work,
        cast(FileStoragePort, storage),
        availability=ArtifactAvailability(unit_of_work, cast(FileStoragePort, storage)),
    )
    artifact = ArtifactObject(
        workspace_id=UUID("00000000-0000-0000-0000-000000000007"),
        artifact_type=artifact_type,
        schema_version=schema_version,
        content_type="application/json",
        bucket="artifacts",
        object_key="tables/manifest.json",
        byte_size=BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES + 1,
        metadata=metadata,
    )

    async def open_and_close() -> None:
        try:
            with pytest.raises(ArtifactResponseTooLargeError) as error:
                await service.open_content(artifact)
            assert str(artifact.id) in str(error.value)
            assert str(BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES) in str(error.value)
        finally:
            await service.close()

    asyncio.run(open_and_close())
    assert storage.load_calls == 0


def test_small_inline_content_without_size_metadata_remains_available() -> None:
    unit_of_work = InMemoryUnitOfWork()
    service = ArtifactService(
        unit_of_work,
        cast(FileStoragePort, TrackingStorage(b"unused")),
        availability=ArtifactAvailability(
            unit_of_work, cast(FileStoragePort, TrackingStorage(b"unused"))
        ),
    )
    artifact = ArtifactObject(
        workspace_id=UUID("00000000-0000-0000-0000-000000000007"),
        artifact_type="scalar.text",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": "legacy"},
        byte_size=None,
    )

    async def open_and_close() -> bytes:
        try:
            return await _consume(await service.open_content(artifact))
        finally:
            await service.close()

    assert asyncio.run(open_and_close()) == b'{\n  "value": "legacy"\n}\n'
