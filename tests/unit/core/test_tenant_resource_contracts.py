from uuid import UUID

import pytest
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.domain.uploads import Upload
from grafy_core.runtime.in_memory import (
    InMemoryUnitOfWork,
)

WORKSPACE_ONE = UUID("00000000-0000-0000-0000-000000000101")
WORKSPACE_TWO = UUID("00000000-0000-0000-0000-000000000102")


@pytest.mark.asyncio
async def test_in_memory_artifacts_require_matching_workspace_identity() -> None:
    unit_of_work = InMemoryUnitOfWork()
    artifact_id = UUID("00000000-0000-0000-0000-000000000115")
    first = ArtifactObject(
        workspace_id=WORKSPACE_ONE,
        id=artifact_id,
        artifact_type="test.value",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"workspace": "one"},
    )
    duplicate_id = ArtifactObject(
        workspace_id=WORKSPACE_TWO,
        id=artifact_id,
        artifact_type="test.value",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"workspace": "duplicate"},
    )

    async with unit_of_work as entered:
        await entered.artifacts.add(first)
        with pytest.raises(ObjectAlreadyExistsError, match="Artifact already exists"):
            await entered.artifacts.add(duplicate_id)
        await entered.commit()

    async with unit_of_work as entered:
        assert await entered.artifacts.get(WORKSPACE_ONE, artifact_id) == first
        assert await entered.artifacts.get(WORKSPACE_TWO, artifact_id) is None
        await entered.artifacts.remove(WORKSPACE_TWO, first)
        await entered.commit()

    async with unit_of_work as entered:
        assert await entered.artifacts.get(WORKSPACE_ONE, artifact_id) == first


def test_upload_rejects_unbounded_or_negative_metadata() -> None:
    with pytest.raises(ValueError, match="expected size"):
        Upload(
            workspace_id=WORKSPACE_ONE,
            upload_id=UUID(int=1),
            original_filename="input.csv",
            bucket="artifacts",
            object_key="objects/one",
            expected_size=-1,
        )
    with pytest.raises(ValueError, match="at most 255"):
        Upload(
            workspace_id=WORKSPACE_ONE,
            upload_id=UUID(int=1),
            original_filename="x" * 256,
            bucket="artifacts",
            object_key="objects/one",
            expected_size=0,
        )
    with pytest.raises(ValueError, match="object key must not be blank"):
        Upload(
            workspace_id=WORKSPACE_ONE,
            upload_id=UUID(int=1),
            original_filename="input.csv",
            bucket="artifacts",
            object_key="",
            expected_size=0,
        )
    with pytest.raises(ValueError, match="at most 1024"):
        Upload(
            workspace_id=WORKSPACE_ONE,
            upload_id=UUID(int=1),
            original_filename="input.csv",
            bucket="artifacts",
            object_key="x" * 1025,
            expected_size=0,
        )
    with pytest.raises(ValueError, match="digest must be 64 characters"):
        Upload(
            workspace_id=WORKSPACE_ONE,
            upload_id=UUID(int=1),
            original_filename="input.csv",
            bucket="artifacts",
            object_key="objects/one",
            expected_size=0,
            sha256="short",
        )
