from datetime import UTC, datetime
from uuid import UUID

import pytest

from grafy_core.artifacts import ArtifactObject, ArtifactRef, ArtifactRefSequence
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
from grafy_core.domain.artifact_outputs import (
    artifact_outputs_from_storage,
    artifact_outputs_to_storage,
)
from grafy_core.domain.invocation_cache import InvocationCacheEntry


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


def _artifact(artifact_id: str) -> ArtifactObject:
    return ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID(artifact_id),
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 3},
        sha256="3" * 64,
    )


def test_invocation_cache_entry_normalizes_and_copies_artifact_outputs() -> None:
    artifact = _artifact("00000000-0000-0000-0000-000000000101")
    source_ref = artifact.ref()
    entry = InvocationCacheEntry(
        workspace_id=WORKSPACE_ID,
        key_sha256="a" * 64,
        outputs={" value ": source_ref},
        generation=UUID("00000000-0000-0000-0000-000000000102"),
        created_at=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
    )

    source_ref.content_hash = "4" * 64

    assert set(entry.outputs) == {"value"}
    cached_ref = entry.outputs["value"]
    assert isinstance(cached_ref, ArtifactRef)
    assert cached_ref.content_hash == "3" * 64


@pytest.mark.parametrize(
    "key_sha256",
    [
        "a" * 63,
        "A" * 64,
        "g" * 64,
        " a" + "a" * 62,
    ],
)
def test_invocation_cache_entry_requires_canonical_sha256(key_sha256: str) -> None:
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        InvocationCacheEntry(
            workspace_id=WORKSPACE_ID,
            key_sha256=key_sha256,
            outputs={},
        )


def test_shared_artifact_output_storage_preserves_sequence_envelope() -> None:
    first = _artifact("00000000-0000-0000-0000-000000000111")
    second = _artifact("00000000-0000-0000-0000-000000000112")
    sequence = ArtifactRefSequence(
        sequence_id=UUID("00000000-0000-0000-0000-000000000113"),
        artifact_type="scalar.integer",
        schema_version=1,
        item_refs=[first.ref(), second.ref()],
        ordered=False,
        index_key="source_order",
        metadata={"source_sequence_id": "upstream"},
    )

    stored = artifact_outputs_to_storage({"single": first.ref(), "sequence": sequence})
    loaded = artifact_outputs_from_storage(stored)

    assert loaded["single"] == first.ref()
    assert loaded["sequence"] == sequence


@pytest.mark.asyncio
async def test_in_memory_cache_follows_commit_and_first_writer_wins() -> None:
    store = InMemoryDataStore()
    unit_of_work = InMemoryUnitOfWork(store)
    first = InvocationCacheEntry(
        workspace_id=WORKSPACE_ID,
        key_sha256="b" * 64,
        outputs={"first": _artifact("00000000-0000-0000-0000-000000000121").ref()},
    )
    replacement = InvocationCacheEntry(
        workspace_id=WORKSPACE_ID,
        key_sha256=first.key_sha256,
        outputs={
            "replacement": _artifact("00000000-0000-0000-0000-000000000122").ref()
        },
    )

    async with unit_of_work as entered:
        assert await entered.invocation_cache.put_if_absent(first)
        await entered.commit()
    async with unit_of_work as entered:
        assert not await entered.invocation_cache.put_if_absent(replacement)
        await entered.commit()
    async with unit_of_work as entered:
        loaded = await entered.invocation_cache.get(
            WORKSPACE_ID,
            first.key_sha256,
        )

    assert loaded is not None
    assert loaded.generation == first.generation
    assert loaded.outputs == first.outputs


@pytest.mark.asyncio
async def test_in_memory_cache_removes_only_the_observed_generation() -> None:
    unit_of_work = InMemoryUnitOfWork()
    entry = InvocationCacheEntry(
        workspace_id=WORKSPACE_ID,
        key_sha256="c" * 64,
        outputs={},
    )
    async with unit_of_work as entered:
        assert await entered.invocation_cache.put_if_absent(entry)
        await entered.commit()

    async with unit_of_work as entered:
        assert not await entered.invocation_cache.remove_if_current(
            WORKSPACE_ID,
            entry.key_sha256,
            UUID("00000000-0000-0000-0000-000000000130"),
        )
        assert await entered.invocation_cache.remove_if_current(
            WORKSPACE_ID,
            entry.key_sha256,
            entry.generation,
        )

    async with unit_of_work as entered:
        assert (
            await entered.invocation_cache.get(WORKSPACE_ID, entry.key_sha256)
            is not None
        )


@pytest.mark.asyncio
async def test_in_memory_artifact_batch_lookup_deduplicates_and_omits_missing() -> None:
    unit_of_work = InMemoryUnitOfWork()
    artifact = _artifact("00000000-0000-0000-0000-000000000141")
    missing_id = UUID("00000000-0000-0000-0000-000000000142")
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()

    async with unit_of_work as entered:
        loaded = await entered.artifacts.get_many(
            WORKSPACE_ID, [artifact.id, artifact.id, missing_id]
        )

    assert loaded == {artifact.id: artifact}
