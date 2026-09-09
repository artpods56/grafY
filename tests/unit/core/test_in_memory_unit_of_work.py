import asyncio
from uuid import UUID, uuid4
from datetime import UTC, datetime
from grafy_core.domain.execution_history import TransientExecution

import pytest

from grafy_core.artifacts import ArtifactObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


def _artifact(artifact_id: str) -> ArtifactObject:
    return ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID(artifact_id),
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 1},
    )


@pytest.mark.asyncio
async def test_concurrent_tasks_commit_without_losing_artifacts() -> None:
    unit_of_work = InMemoryUnitOfWork()
    first = _artifact("00000000-0000-0000-0000-000000000201")
    second = _artifact("00000000-0000-0000-0000-000000000202")
    first_entered = asyncio.Event()
    second_waiting = asyncio.Event()

    async def write_first() -> None:
        async with unit_of_work as entered:
            await entered.artifacts.add(first)
            first_entered.set()
            await second_waiting.wait()
            await entered.commit()

    async def write_second() -> None:
        await first_entered.wait()
        second_waiting.set()
        async with unit_of_work as entered:
            assert await entered.artifacts.get(WORKSPACE_ID, first.id) == first
            await entered.artifacts.add(second)
            await entered.commit()

    await asyncio.gather(write_first(), write_second())

    async with unit_of_work as entered:
        stored = await entered.artifacts.get_many(WORKSPACE_ID, [first.id, second.id])

    assert stored == {first.id: first, second.id: second}
    assert unit_of_work.commit_count == 2


@pytest.mark.asyncio
async def test_nested_entry_rejects_without_corrupting_outer_transaction() -> None:
    unit_of_work = InMemoryUnitOfWork()
    artifact = _artifact("00000000-0000-0000-0000-000000000203")

    async with unit_of_work as entered:
        with pytest.raises(RuntimeError, match="already entered in this task"):
            async with unit_of_work:
                pass
        await entered.artifacts.add(artifact)
        await entered.commit()

    async with unit_of_work as entered:
        assert await entered.artifacts.get(WORKSPACE_ID, artifact.id) == artifact


@pytest.mark.asyncio
async def test_transient_activity_rollback_and_owner_bound_deletion() -> None:
    unit_of_work = InMemoryUnitOfWork()
    marker = TransientExecution(
        execution_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        owner_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    async with unit_of_work as transaction:
        await transaction.execution_history.add_transient(marker)
    async with unit_of_work as transaction:
        assert await transaction.execution_history.list_transient() == ()
        await transaction.execution_history.add_transient(marker)
        await transaction.commit()
    async with unit_of_work as transaction:
        await transaction.execution_history.remove_transient(
            marker.execution_id, uuid4()
        )
        await transaction.commit()
    async with unit_of_work as transaction:
        assert await transaction.execution_history.list_transient() == (marker,)
        await transaction.execution_history.remove_transient(
            marker.execution_id, marker.owner_id
        )
        await transaction.commit()
    async with unit_of_work as transaction:
        assert await transaction.execution_history.list_transient() == ()
