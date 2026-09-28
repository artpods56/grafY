"""The Library folder rows and placements the panel reads, in the SQL adapter.

The API integration tests drive the folder routes through the in-memory unit of
work, so they prove the service's rules. Only these tests touch what the shipped
adapter owes: that a nested folder comes back nested, that the unique sibling
index is the thing refusing a clash, and that a placement follows the artifact.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.errors import LibraryFolderNameConflictError
from grafy_core.domain.library import LibraryFolder
from grafy_persistence import schema
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


def _folder(
    name: str,
    parent_id: UUID | None = None,
    workspace_id: UUID = WORKSPACE_ONE,
) -> LibraryFolder:
    return LibraryFolder(
        workspace_id=workspace_id,
        name=name,
        parent_id=parent_id,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_a_nested_folder_comes_back_with_its_place_in_the_tree(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    fieldwork = _folder("Fieldwork")
    september = _folder("September", parent_id=fieldwork.id)
    reports = _folder("Reports", workspace_id=WORKSPACE_TWO)

    async with unit_of_work as entered:
        await entered.library_folders.add(fieldwork)
        await entered.library_folders.add(september)
        await entered.library_folders.add(reports)
        await entered.commit()

    async with unit_of_work as entered:
        listed = await entered.library_folders.list(WORKSPACE_ONE)
        by_id = await entered.library_folders.get(WORKSPACE_ONE, september.id)
        by_sibling_name = await entered.library_folders.get_by_name(
            WORKSPACE_ONE,
            fieldwork.id,
            september.name_key,
        )
        other_workspace = await entered.library_folders.list(WORKSPACE_TWO)

    assert [folder.name for folder in listed] == ["Fieldwork", "September"]
    assert [(folder.id, folder.parent_id) for folder in listed] == [
        (fieldwork.id, None),
        (september.id, fieldwork.id),
    ]
    assert by_id is not None
    assert by_id.parent_id == fieldwork.id
    assert by_id.created_at == NOW
    assert by_sibling_name is not None
    assert by_sibling_name.id == september.id
    assert [folder.id for folder in other_workspace] == [reports.id]


@pytest.mark.asyncio
async def test_a_rename_and_a_move_are_both_read_back(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    fieldwork = _folder("Fieldwork")
    reports = _folder("Reports")
    september = _folder("September", parent_id=fieldwork.id)

    async with unit_of_work as entered:
        await entered.library_folders.add(fieldwork)
        await entered.library_folders.add(reports)
        await entered.library_folders.add(september)
        await entered.commit()

    async with unit_of_work as entered:
        moved = await entered.library_folders.get(WORKSPACE_ONE, september.id)
        assert moved is not None
        moved.rename("Raw photos", updated_at=NOW)
        moved.parent_id = reports.id
        await entered.library_folders.save(moved)
        await entered.commit()

    async with unit_of_work as entered:
        listed = await entered.library_folders.list(WORKSPACE_ONE)
        under_reports = await entered.library_folders.get_by_name(
            WORKSPACE_ONE,
            reports.id,
            "raw photos",
        )
        left_in_fieldwork = await entered.library_folders.count_children(
            WORKSPACE_ONE,
            fieldwork.id,
        )

    assert under_reports is not None
    assert under_reports.name == "Raw photos"
    assert under_reports.parent_id == reports.id
    assert left_in_fieldwork == 0
    assert [folder.name for folder in listed] == ["Fieldwork", "Raw photos", "Reports"]


@pytest.mark.asyncio
async def test_the_unique_sibling_index_is_what_refuses_a_repeated_name(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    fieldwork = _folder("Fieldwork")

    async with unit_of_work as entered:
        await entered.library_folders.add(fieldwork)
        await entered.commit()

    with pytest.raises(LibraryFolderNameConflictError):
        async with unit_of_work as entered:
            await entered.library_folders.add(_folder("  FIELDWORK  "))
            await entered.commit()

    # The same name under a different parent is a different folder, and the
    # index that refused the sibling must still let it through.
    async with unit_of_work as entered:
        await entered.library_folders.add(_folder("FIELDWORK", parent_id=fieldwork.id))
        await entered.commit()

    async with unit_of_work as entered:
        listed = await entered.library_folders.list(WORKSPACE_ONE)

    # Both rows casefold to the same key, so `list` breaks the tie by id and the
    # pair is what says the nested one was allowed through.
    assert len(listed) == 2
    assert {(folder.name, folder.parent_id) for folder in listed} == {
        ("Fieldwork", None),
        ("FIELDWORK", fieldwork.id),
    }


# U+0390 GREEK SMALL LETTER IOTA WITH DIALYTIKA AND TONOS casefolds to iota plus
# combining diaeresis plus combining acute: three characters for one.
_WIDEST_CASEFOLD_CHARACTER = "\u0390"


def test_the_stored_sibling_key_is_wide_enough_for_the_widest_casefold() -> None:
    """The longest valid name has to fit the column once the domain folds it.

    A 160-character name is valid and casefolding can triple it, so `name_key`
    has to be wider than `name`. SQLite ignores column widths, so this is the
    check that catches a narrowed column on every machine; the Postgres half of
    the round-trip test below is what catches a database that disagrees.
    """
    widest_fold = max(
        len(chr(codepoint).casefold())
        for codepoint in range(0x110000)
        if not 0xD800 <= codepoint <= 0xDFFF
    )
    assert widest_fold == 3, "Unicode's widest casefolding changed; widen name_key with it"

    with pytest.raises(ValueError, match="at most 160 characters"):
        LibraryFolder(
            workspace_id=WORKSPACE_ONE,
            name="x" * 161,
            created_at=NOW,
            updated_at=NOW,
        )
    longest_valid_name = _WIDEST_CASEFOLD_CHARACTER * 160
    folder = LibraryFolder(
        workspace_id=WORKSPACE_ONE,
        name=longest_valid_name,
        created_at=NOW,
        updated_at=NOW,
    )

    assert len(folder.name) == 160
    assert len(folder.name_key) == 160 * widest_fold
    assert len(folder.name_key) <= schema.library_folders.c.name_key.type.length


@pytest.mark.asyncio
async def test_a_name_that_casefold_lengthens_is_stored_and_keyed_in_full(
    database: Database,
) -> None:
    """A folded 480-character key is written, read back, and refused when repeated.

    This is the test that only Postgres can really pass: it is the one backend
    here that enforces a VARCHAR width, so a `name_key` column narrower than the
    folded key raises before the second insert ever reaches the unique index.
    """
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    widest_valid_name = _WIDEST_CASEFOLD_CHARACTER * 160
    fieldwork = _folder(widest_valid_name)

    async with unit_of_work as entered:
        await entered.library_folders.add(fieldwork)
        await entered.commit()

    async with unit_of_work as entered:
        stored = await entered.library_folders.get(WORKSPACE_ONE, fieldwork.id)
        by_key = await entered.library_folders.get_by_name(
            WORKSPACE_ONE,
            None,
            fieldwork.name_key,
        )

    assert stored is not None
    assert stored.name == widest_valid_name
    assert len(fieldwork.name_key) == 480
    assert by_key is not None and by_key.id == fieldwork.id

    # The full key is what the unique index compares, so the twin is refused
    # rather than quietly filed beside it.
    with pytest.raises(LibraryFolderNameConflictError):
        async with unit_of_work as entered:
            await entered.library_folders.add(_folder(widest_valid_name))
            await entered.commit()


@pytest.mark.asyncio
async def test_a_placement_follows_the_artifact_it_files(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    fieldwork = _folder("Fieldwork")
    reports = _folder("Reports")
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ONE,
        artifact_type="text.plain",
        schema_version=1,
        content_type="text/csv",
        inline_payload={"text": "station,salinity\nA,34.2\n"},
    )

    async with unit_of_work as entered:
        await entered.library_folders.add(fieldwork)
        await entered.library_folders.add(reports)
        await entered.artifacts.add(artifact)
        await entered.commit()

    # The artifact is a row the placement points at, so it exists first.
    async with unit_of_work as entered:
        await entered.library_folders.place(
            WORKSPACE_ONE,
            [artifact.id],
            fieldwork.id,
        )
        await entered.commit()

    async with unit_of_work as entered:
        assert await entered.library_folders.placements(WORKSPACE_ONE) == {
            artifact.id: fieldwork.id,
        }
        assert (
            await entered.library_folders.count_placements(
                WORKSPACE_ONE,
                fieldwork.id,
            )
            == 1
        )
        # One drop onto another folder re-files the same artifact rather than
        # filing it twice, and dropping it on the background takes it out again.
        await entered.library_folders.place(WORKSPACE_ONE, [artifact.id], reports.id)
        assert await entered.library_folders.placements(WORKSPACE_ONE) == {
            artifact.id: reports.id,
        }
        await entered.library_folders.place(WORKSPACE_ONE, [artifact.id], None)
        assert await entered.library_folders.placements(WORKSPACE_ONE) == {}
        await entered.commit()

    async with unit_of_work as entered:
        assert await entered.library_folders.placements(WORKSPACE_ONE) == {}
        assert (
            await entered.library_folders.count_placements(WORKSPACE_ONE, reports.id)
            == 0
        )
