from datetime import UTC, datetime
from uuid import uuid4

import pytest
from grafy_core.artifacts import ArtifactObject, LibraryProvenance
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.unit.persistence.test_execution_history_persistence import (
    WORKSPACE_ONE,
    WORKSPACE_TWO,
)
from tests.unit.persistence.test_execution_history_persistence import (
    database as _database_fixture,
)

database = _database_fixture


NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _artifact(workspace_id: object, **metadata: object) -> ArtifactObject:
    return ArtifactObject(
        workspace_id=workspace_id,  # pyright: ignore[reportArgumentType]
        artifact_type="text.plain",
        schema_version=1,
        content_type="application/json",
        inline_payload={"text": "hello"},
        metadata=dict(metadata),
    )


@pytest.mark.asyncio
async def test_library_provenance_round_trips_on_the_artifact_row(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    artifact = _artifact(WORKSPACE_ONE, download_name="report.json")
    provenance = LibraryProvenance.from_run(
        saved_at=NOW,
        graph_id=uuid4(),
        graph_title="Sales",
        node_id="resize-1",
        node_title="Resize",
        graph_revision=4,
        execution_id=uuid4(),
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()

    async with unit_of_work as entered:
        loaded = await entered.artifacts.get(WORKSPACE_ONE, artifact.id)
        assert loaded is not None
        assert loaded.library_provenance is None
        loaded.library_provenance = provenance
        await entered.commit()

    async with unit_of_work as entered:
        reloaded = await entered.artifacts.get(WORKSPACE_ONE, artifact.id)
        listed = await entered.artifacts.list_library(WORKSPACE_ONE)

    assert reloaded is not None
    assert reloaded.library_provenance == provenance
    assert [candidate.id for candidate in listed] == [artifact.id]


@pytest.mark.asyncio
async def test_an_uploaded_provenance_round_trips(database: Database) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    artifact = _artifact(WORKSPACE_ONE, download_name="measurements.csv")
    provenance = LibraryProvenance.from_upload(
        saved_at=NOW,
        original_filename="measurements.csv",
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    async with unit_of_work as entered:
        loaded = await entered.artifacts.get(WORKSPACE_ONE, artifact.id)
        assert loaded is not None
        loaded.library_provenance = provenance
        await entered.commit()

    async with unit_of_work as entered:
        reloaded = await entered.artifacts.get(WORKSPACE_ONE, artifact.id)

    assert reloaded is not None
    assert reloaded.library_provenance == provenance


@pytest.mark.asyncio
async def test_library_listing_stays_scoped_to_its_workspace_and_membership(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    library_artifact = _artifact(WORKSPACE_ONE)
    plain_artifact = _artifact(WORKSPACE_ONE)
    other_workspace_artifact = _artifact(WORKSPACE_TWO)
    async with unit_of_work as entered:
        await entered.artifacts.add(library_artifact)
        await entered.artifacts.add(plain_artifact)
        await entered.artifacts.add(other_workspace_artifact)
        await entered.commit()
    async with unit_of_work as entered:
        for artifact, workspace_id in (
            (library_artifact, WORKSPACE_ONE),
            (other_workspace_artifact, WORKSPACE_TWO),
        ):
            loaded = await entered.artifacts.get(workspace_id, artifact.id)
            assert loaded is not None
            loaded.library_provenance = LibraryProvenance.from_upload(
                saved_at=NOW,
                original_filename="measurements.csv",
            )
        await entered.commit()

    async with unit_of_work as entered:
        listed = await entered.artifacts.list_library(WORKSPACE_ONE)

    assert [candidate.id for candidate in listed] == [library_artifact.id]
