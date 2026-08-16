import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Barrier
from typing import override

import pytest

from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.ports.storage import SaveFileCommand, StoredFile
from grafy_storage import LocalFileObjectStore


class _BarrierStream(BytesIO):
    def __init__(self, content: bytes, barrier: Barrier) -> None:
        super().__init__(content)
        self._barrier = barrier
        self._first_read = True

    @override
    def read(self, size: int | None = -1, /) -> bytes:
        if self._first_read:
            self._first_read = False
            _ = self._barrier.wait(timeout=5)
        return super().read(size)


@pytest.mark.asyncio
async def test_local_object_store_stats_and_loads_bounded_byte_range(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path)
    await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path="runs/output.bin",
            stream=BytesIO(b"0123456789"),
            content_type="application/octet-stream",
            metadata={"source": "unit-test"},
        )
    )

    info = await storage.stat("artifacts", "runs/output.bin")
    content = await storage.load_range("artifacts", "runs/output.bin", 2, 7)

    assert info is not None
    assert info.bucket == "artifacts"
    assert info.path == "runs/output.bin"
    assert info.byte_size == 10
    assert info.etag is None
    assert info.version_id is None
    assert content == b"23456"


@pytest.mark.asyncio
async def test_local_object_store_range_validation_and_missing_object_context(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path)

    assert await storage.stat("artifacts", "runs/missing.bin") is None
    assert await storage.load_range("artifacts", "runs/missing.bin", 3, 3) == b""

    with pytest.raises(ValueError, match="nonnegative.*start=-1"):
        await storage.load_range("artifacts", "runs/missing.bin", -1, 2)
    with pytest.raises(ValueError, match="must not precede.*start=3"):
        await storage.load_range("artifacts", "runs/missing.bin", 3, 2)
    with pytest.raises(FileNotFoundError, match="artifacts/runs/missing.bin"):
        await storage.load_range("artifacts", "runs/missing.bin", 0, 1)


@pytest.mark.asyncio
async def test_local_object_store_create_rejects_existing_object_without_mutating_it(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path)
    await storage.save(_command(BytesIO(b"first")))

    with pytest.raises(ObjectAlreadyExistsError, match="artifacts/runs/output.bin"):
        await storage.save(_command(BytesIO(b"rejected")))

    loaded = await storage.load("artifacts", "runs/output.bin")
    try:
        assert loaded.read() == b"first"
    finally:
        loaded.close()
    assert list((tmp_path / "artifacts" / "runs").glob(".*.tmp-*")) == []


def test_local_object_store_concurrent_create_has_exactly_one_winner(
    tmp_path: Path,
) -> None:
    storage = LocalFileObjectStore(tmp_path)
    barrier = Barrier(2)
    contents = (b"first writer", b"second writer")
    commands = tuple(
        _command(_BarrierStream(content, barrier)) for content in contents
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures: list[Future[StoredFile]] = [
            executor.submit(asyncio.run, storage.save(command)) for command in commands
        ]
        outcomes: list[StoredFile | Exception] = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except Exception as exc:
                outcomes.append(exc)

    successes = [outcome for outcome in outcomes if isinstance(outcome, StoredFile)]
    collisions = [
        outcome for outcome in outcomes if isinstance(outcome, ObjectAlreadyExistsError)
    ]

    assert len(successes) == 1
    assert len(collisions) == 1
    assert successes[0].sha256 in {sha256(content).hexdigest() for content in contents}

    loaded = asyncio.run(storage.load("artifacts", "runs/output.bin"))
    try:
        stored_content = loaded.read()
    finally:
        loaded.close()
    assert sha256(stored_content).hexdigest() == successes[0].sha256
    assert list((tmp_path / "artifacts" / "runs").glob(".*.tmp-*")) == []


def _command(stream: BytesIO) -> SaveFileCommand:
    return SaveFileCommand(
        bucket="artifacts",
        path="runs/output.bin",
        stream=stream,
        content_type="application/octet-stream",
        metadata={"source": "unit-test"},
    )
