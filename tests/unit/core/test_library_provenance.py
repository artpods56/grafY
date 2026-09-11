from datetime import UTC, datetime
from uuid import uuid4

import pytest
from grafy_core.artifacts import LibraryProvenance
from pydantic import ValidationError

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _run_provenance() -> LibraryProvenance:
    return LibraryProvenance.from_run(
        saved_at=NOW,
        graph_id=uuid4(),
        graph_title="Sales",
        node_id="resize-1",
        node_title="Resize",
        graph_revision=4,
        execution_id=uuid4(),
    )


def test_run_provenance_freezes_the_producing_facts() -> None:
    provenance = _run_provenance()

    assert provenance.source == "run"
    assert provenance.graph_title == "Sales"
    assert provenance.node_title == "Resize"
    assert provenance.graph_revision == 4
    assert provenance.execution_id is not None
    assert provenance.original_filename is None


def test_run_provenance_strips_titles() -> None:
    provenance = LibraryProvenance.from_run(
        saved_at=NOW,
        graph_id=uuid4(),
        graph_title="  Sales  ",
        node_id="  resize-1  ",
        node_title="  Resize  ",
        graph_revision=1,
        execution_id=uuid4(),
    )

    assert provenance.graph_id is not None
    assert provenance.graph_title == "Sales"
    assert provenance.node_id == "resize-1"
    assert provenance.node_title == "Resize"


@pytest.mark.parametrize(
    "missing",
    ["graph_id", "graph_title", "node_id", "node_title", "graph_revision", "execution_id"],
)
def test_run_provenance_requires_every_producing_fact(missing: str) -> None:
    fields: dict[str, object] = {
        "saved_at": NOW,
        "graph_id": uuid4(),
        "graph_title": "Sales",
        "node_id": "resize-1",
        "node_title": "Resize",
        "graph_revision": 4,
        "execution_id": uuid4(),
    }
    fields[missing] = None

    with pytest.raises(ValidationError):
        LibraryProvenance(source="run", **fields)  # pyright: ignore[reportArgumentType]


def test_run_provenance_rejects_a_non_positive_revision() -> None:
    with pytest.raises(ValidationError):
        LibraryProvenance.from_run(
            saved_at=NOW,
            graph_id=uuid4(),
            graph_title="Sales",
            node_id="resize-1",
            node_title="Resize",
            graph_revision=0,
            execution_id=uuid4(),
        )


def test_upload_provenance_carries_only_the_filename() -> None:
    provenance = LibraryProvenance.from_upload(
        saved_at=NOW,
        original_filename="  report.csv  ",
    )

    assert provenance.source == "upload"
    assert provenance.original_filename == "report.csv"
    assert provenance.graph_id is None
    assert provenance.execution_id is None


def test_upload_provenance_rejects_run_facts() -> None:
    with pytest.raises(ValidationError):
        LibraryProvenance(
            source="upload",
            saved_at=NOW,
            original_filename="report.csv",
            execution_id=uuid4(),
        )


def test_run_provenance_rejects_an_uploaded_filename() -> None:
    with pytest.raises(ValidationError):
        LibraryProvenance(
            source="run",
            saved_at=NOW,
            graph_id=uuid4(),
            graph_title="Sales",
            node_id="resize-1",
            node_title="Resize",
            graph_revision=4,
            execution_id=uuid4(),
            original_filename="report.csv",
        )


def test_provenance_requires_an_aware_save_time() -> None:
    with pytest.raises(ValidationError):
        LibraryProvenance.from_upload(
            saved_at=datetime(2026, 9, 11, 12, 0),
            original_filename="report.csv",
        )


def test_provenance_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        LibraryProvenance.model_validate(
            {
                "source": "upload",
                "saved_at": NOW,
                "original_filename": "report.csv",
                "staleness": "gone",
            }
        )


def test_provenance_is_frozen() -> None:
    provenance = _run_provenance()

    with pytest.raises(ValidationError):
        provenance.graph_title = "Renamed"


def test_provenance_round_trips_through_json() -> None:
    provenance = _run_provenance()

    restored = LibraryProvenance.model_validate(
        provenance.model_dump(mode="json"),
    )

    assert restored == provenance
