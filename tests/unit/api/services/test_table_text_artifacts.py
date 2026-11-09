"""Rows of a table become text artifacts a person can drag out of a tool result."""

from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_core.artifacts import ArtifactObject
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.in_memory import InMemoryUnitOfWork

WORKSPACE = UUID(int=7)
OTHER_TABLE = UUID(int=9)


def harness(
    rows: list[dict[str, object]],
) -> tuple[ArtifactService, InMemoryUnitOfWork, ArtifactObject]:
    unit_of_work = InMemoryUnitOfWork()
    storage = cast(FileStoragePort, object())
    service = ArtifactService(
        unit_of_work,
        storage,
        availability=ArtifactAvailability(unit_of_work),
    )
    table = ArtifactObject(
        workspace_id=WORKSPACE,
        artifact_type="table.data",
        schema_version=1,
        content_type="application/json",
    )

    async def page(_artifact: ArtifactObject, *, offset: int, limit: int):
        return SimpleNamespace(
            columns=[SimpleNamespace(id="text"), SimpleNamespace(id="page")],
            rows=rows[offset : offset + limit],
            total_rows=len(rows),
        )

    service.load_table_page = page  # type: ignore[method-assign]
    return service, unit_of_work, table


async def test_each_row_with_text_gets_an_artifact_holding_that_text() -> None:
    service, unit_of_work, table = harness(
        [{"text": "<table>x</table>", "page": 0}, {"text": "", "page": 1}]
    )

    rows, total = await service.text_artifacts_for_column(
        table, column_id="text", offset=0, limit=10
    )

    assert total == 2
    assert [index for index, _ in rows] == [0, 1]
    ref = rows[0][1]
    # An empty cell has nothing to take out.
    assert ref is not None and rows[1][1] is None
    assert (ref.artifact_type, ref.schema_version) == ("scalar.text", 1)
    async with unit_of_work as uow:
        stored = await uow.artifacts.get(WORKSPACE, ref.artifact_id)
    assert stored is not None
    assert stored.inline_payload == {"value": "<table>x</table>"}
    assert stored.metadata["source_artifact_id"] == str(table.id)
    assert (stored.metadata["row_index"], stored.metadata["column_id"]) == (0, "text")


async def test_asking_again_makes_nothing_new() -> None:
    service, _, table = harness([{"text": "same", "page": 0}])

    first, _ = await service.text_artifacts_for_column(
        table, column_id="text", offset=0, limit=10
    )
    second, _ = await service.text_artifacts_for_column(
        table, column_id="text", offset=0, limit=10
    )

    assert first == second


async def test_a_row_past_the_first_page_keeps_its_own_index() -> None:
    service, _, table = harness([{"text": "a"}, {"text": "b"}, {"text": "c"}])

    rows, _ = await service.text_artifacts_for_column(
        table, column_id="text", offset=2, limit=1
    )

    assert [index for index, _ in rows] == [2]


async def test_a_number_column_offers_no_text() -> None:
    service, _, table = harness([{"text": "a", "page": 3}])

    rows, _ = await service.text_artifacts_for_column(
        table, column_id="page", offset=0, limit=10
    )

    assert rows == [(0, None)]


async def test_an_unknown_column_is_refused() -> None:
    service, _, table = harness([{"text": "a"}])

    with pytest.raises(WorkbenchOperationError, match="no column"):
        await service.text_artifacts_for_column(
            table, column_id="nope", offset=0, limit=10
        )
