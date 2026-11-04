from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.projects import Project
from grafy_core.domain.uploads import Upload
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

WORKSPACE_ONE = UUID("00000000-0000-0000-0000-000000000201")
WORKSPACE_TWO = UUID("00000000-0000-0000-0000-000000000202")


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'tenant.sqlite3'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            text(
                "INSERT INTO workspaces "
                "(id, slug, name, kind, created_at, updated_at) VALUES "
                "(:one, 'one', 'One', 'shared', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(:two, 'two', 'Two', 'shared', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"one": WORKSPACE_ONE.hex, "two": WORKSPACE_TWO.hex},
        )
    try:
        yield database
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_sql_repositories_require_workspace_for_projects_artifacts_and_uploads(
    database: Database,
) -> None:
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ONE,
        id=UUID("00000000-0000-0000-0000-000000000203"),
        artifact_type="test.value",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 1},
        metadata={},
    )
    artifact_two = ArtifactObject(
        workspace_id=WORKSPACE_TWO,
        id=UUID("00000000-0000-0000-0000-000000000207"),
        artifact_type="test.value",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 2},
        metadata={},
    )
    upload = Upload(
        workspace_id=WORKSPACE_ONE,
        upload_id=UUID("00000000-0000-0000-0000-00000000020a"),
        original_filename="source.csv",
        bucket="artifacts",
        object_key="objects/source",
        expected_size=4,
    )
    project = Project(workspace_id=WORKSPACE_ONE, name="Tenant Project")

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.projects.add(project)
        await unit_of_work.artifacts.add(artifact)
        await unit_of_work.artifacts.add(artifact_two)
        await unit_of_work.uploads.add(upload)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.artifacts.get(WORKSPACE_ONE, artifact.id) is not None
        assert await unit_of_work.artifacts.get(WORKSPACE_TWO, artifact.id) is None
        assert await unit_of_work.projects.get(WORKSPACE_ONE, project.id) is not None
        assert await unit_of_work.projects.get(WORKSPACE_TWO, project.id) is None
        assert (
            await unit_of_work.uploads.get(
                WORKSPACE_TWO,
                upload.upload_id,
            )
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("object_key", "expected_size", "status", "actual_size", "completed_at"),
    [
        ("", 0, "pending", None, None),
        ("objects/" + "x" * 1025, 0, "pending", None, None),
        ("objects/source", -1, "pending", None, None),
        ("objects/source", 0, "ready", None, datetime.now(UTC)),
        ("objects/source", 0, "ready", 4, None),
    ],
)
async def test_sql_uploads_reject_unbounded_or_unconfirmed_rows(
    database: Database,
    object_key: str,
    expected_size: int,
    status: str,
    actual_size: int | None,
    completed_at: datetime | None,
) -> None:
    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO uploads "
                    "(workspace_id, upload_id, original_filename, bucket, "
                    "object_key, expected_size, status, actual_size, completed_at, "
                    "created_at) "
                    "VALUES (:workspace_id, :upload_id, 'input.csv', 'artifacts', "
                    ":object_key, :expected_size, :status, :actual_size, "
                    ":completed_at, CURRENT_TIMESTAMP)"
                ),
                {
                    "workspace_id": WORKSPACE_ONE.hex,
                    "upload_id": UUID(int=1).hex,
                    "object_key": object_key,
                    "expected_size": expected_size,
                    "status": status,
                    "actual_size": actual_size,
                    "completed_at": completed_at,
                },
            )
