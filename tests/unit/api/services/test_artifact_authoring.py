from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import pytest

from grafy_api.artifacts.authoring import (
    ArtifactAuthoringService,
    InvalidArtifactPayloadError,
)
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore


async def test_schema_only_artifacts_are_validated_and_appended(tmp_path: Path) -> None:
    spec = ArtifactTypeSpec(
        key=ArtifactTypeKey("example.document", 2),
        title="Document",
        payload_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
    )
    uow = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path)
    values = ArtifactValues(
        (), uow=uow, storage=storage, bucket="artifacts", storage_backend="local"
    )
    service = ArtifactAuthoringService(
        uow,
        storage,
        {(spec.key.id, spec.key.schema_version): spec},
        values,
        bucket="artifacts",
        storage_backend="local",
    )
    workspace = UUID(int=1)
    author = UUID(int=2)
    source = ArtifactObject(
        workspace_id=workspace,
        artifact_type=TEXT_VALUE.key.id,
        schema_version=TEXT_VALUE.key.schema_version,
        content_type="application/json",
        inline_payload={"value": "source"},
    )
    async with uow as uow:
        await uow.artifacts.add(source)
        await uow.commit()

    async def create(payload: Mapping[str, object]) -> ArtifactObject:
        artifact, created_at = await service.create(
            workspace,
            artifact_type="example.document",
            schema_version=2,
            payload=dict(payload),
            author_id=author,
            authored_by="user",
            derived_from_artifact_id=source.id,
            title="Draft",
        )
        assert artifact.metadata["created_at"] == created_at.isoformat()
        return artifact

    with pytest.raises(InvalidArtifactPayloadError):
        await create({"name": 9})
    async with uow as uow:
        assert await uow.artifacts.list_by_type(workspace, spec.key) == []

    first = await create({"name": "Test"})
    second = await create({"name": "Test"})
    assert first.id != second.id
    assert first.sha256 is not None and first.sha256 == second.sha256
    async with uow as uow:
        stored = await uow.artifacts.get(workspace, second.id)
        original = await uow.artifacts.get(workspace, source.id)
    assert original is not None and original.inline_payload == {"value": "source"}
    assert stored is not None
    assert stored.inline_payload == {"name": "Test"}
    assert stored.content_type == "application/json"
    assert stored.metadata["derived_from_artifact_id"] == str(source.id)
    assert stored.metadata["authored_by"] == "user"
    assert stored.metadata["authored_by_user_id"] == str(author)
    assert stored.metadata["title"] == "Draft"
