from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from pydantic import ValidationError

from grafy_core.artifact_collections import (
    JsonCollectionsManifest,
    load_json_collections_manifest,
)
from grafy_core.artifacts import ArtifactObject
from grafy_core.ports.storage import FileStreamProtocol, SaveFileCommand
from grafy_core.runtime.resolvers import ResolutionError
from grafy_core.runtime.table_storage import load_table_manifest
from grafy_core.table_contracts import TableManifest
from grafy_storage import LocalFileObjectStore


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["table", "collections"])
@pytest.mark.parametrize(
    "condition", ["valid", "legacy", "size", "digest", "json", "schema"]
)
async def test_manifest_read_preserves_integrity_validation_and_closes_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["table", "collections"],
    condition: Literal["valid", "legacy", "size", "digest", "json", "schema"],
) -> None:
    model = (
        TableManifest(columns=[], row_count=0, chunks=[])
        if kind == "table"
        else JsonCollectionsManifest(total_items=0, collections=[])
    )
    content = model.model_dump_json().encode()
    if condition == "json":
        content = b"not json"
    elif condition == "schema":
        content = b"{}"
    storage = LocalFileObjectStore(tmp_path)
    loaded_streams: list[FileStreamProtocol] = []
    original_load = LocalFileObjectStore.load

    async def observe_load(
        store: LocalFileObjectStore,
        bucket: str,
        path: str,
    ) -> FileStreamProtocol:
        stream = await original_load(store, bucket=bucket, path=path)
        loaded_streams.append(stream)
        return stream

    monkeypatch.setattr(LocalFileObjectStore, "load", observe_load)
    await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path="manifest.json",
            stream=BytesIO(content),
            content_type="application/json",
            metadata={},
        )
    )
    artifact = ArtifactObject(
        workspace_id=UUID(int=1),
        artifact_type=kind,
        schema_version=1,
        content_type="application/json",
        bucket="artifacts",
        object_key="manifest.json",
        metadata={
            "manifest_byte_size": len(content) + (1 if condition == "size" else 0),
            "manifest_sha256": "0" * 64
            if condition == "digest"
            else sha256(content).hexdigest(),
        },
    )
    if condition == "legacy":
        artifact.metadata = {}
    loader = load_table_manifest if kind == "table" else load_json_collections_manifest
    if condition in ("valid", "legacy"):
        assert await loader(artifact, storage) == model
    else:
        with pytest.raises(ResolutionError) as failure:
            await loader(artifact, storage)
        assert str(artifact.id) in str(failure.value)
        assert "artifacts/manifest.json" in str(failure.value)
        cause = failure.value.__cause__
        if condition in ("json", "schema"):
            assert isinstance(cause, ValidationError)
        else:
            assert isinstance(cause, ValueError)
            assert "manifest.json" in str(cause)
            assert ("bytes" if condition == "size" else "SHA-256") in str(cause)
    assert len(loaded_streams) == 1
    assert loaded_streams[0].closed
