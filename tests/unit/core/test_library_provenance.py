from datetime import UTC, datetime
from uuid import uuid4

import pytest
from grafy_core.artifacts import LibraryProvenance
from pydantic import ValidationError

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _instance_provenance() -> LibraryProvenance:
    return LibraryProvenance.from_instance(
        saved_at=NOW,
        project_id=uuid4(),
        project_title="Workspace Project",
        graph_id="main",
        graph_title="Sales",
        node_id="resize-1",
        node_title="Resize",
        result_fingerprint="a" * 64,
        output_port="value",
        name="Quarterly report",
    )


def test_instance_provenance_freezes_the_producing_facts() -> None:
    provenance = _instance_provenance()

    assert provenance.source == "instance"
    assert provenance.graph_title == "Sales"
    assert provenance.node_title == "Resize"
    assert provenance.result_fingerprint == "a" * 64
    assert provenance.project_id is not None
    assert provenance.original_filename is None
    assert provenance.name == "Quarterly report"


def test_instance_provenance_name_is_optional() -> None:
    values = _instance_provenance().model_dump(mode="json")
    values.pop("name")

    restored = LibraryProvenance.model_validate(values)

    assert restored.name is None


@pytest.mark.parametrize("name", ["", " ", "r" * 161])
def test_instance_provenance_rejects_an_invalid_name(name: str) -> None:
    with pytest.raises(ValueError):
        LibraryProvenance.from_instance(
            saved_at=NOW,
            project_id=uuid4(),
            project_title="Workspace Project",
            graph_id="main",
            graph_title="Sales",
            node_id="resize-1",
            node_title="Resize",
            result_fingerprint="a" * 64,
            output_port="value",
            name=name,
        )


def test_instance_provenance_strips_titles() -> None:
    provenance = LibraryProvenance.from_instance(
        saved_at=NOW,
        project_id=uuid4(),
        project_title="Workspace Project",
        graph_id="main",
        graph_title="  Sales  ",
        node_id="  resize-1  ",
        node_title="  Resize  ",
        result_fingerprint="a" * 64,
        output_port="value",
    )

    assert provenance.graph_id is not None
    assert provenance.graph_title == "Sales"
    assert provenance.node_id == "resize-1"
    assert provenance.node_title == "Resize"


@pytest.mark.parametrize(
    "missing",
    [
        "graph_id",
        "graph_title",
        "node_id",
        "node_title",
        "result_fingerprint",
        "output_port",
        "project_id",
        "project_title",
    ],
)
def test_instance_provenance_requires_every_producing_fact(missing: str) -> None:
    fields: dict[str, object] = {
        "saved_at": NOW,
        "project_id": uuid4(),
        "project_title": "Workspace Project",
        "graph_id": "main",
        "graph_title": "Sales",
        "node_id": "resize-1",
        "node_title": "Resize",
        "result_fingerprint": "a" * 64,
        "output_port": "value",
    }
    fields[missing] = None

    with pytest.raises(ValidationError):
        LibraryProvenance(source="instance", **fields)  # pyright: ignore[reportArgumentType]


def test_instance_provenance_rejects_an_invalid_fingerprint() -> None:
    with pytest.raises(ValidationError):
        LibraryProvenance.from_instance(
            saved_at=NOW,
            project_id=uuid4(),
            project_title="Workspace Project",
            graph_id="main",
            graph_title="Sales",
            node_id="resize-1",
            node_title="Resize",
            result_fingerprint="malformed",
            output_port="value",
        )


def test_upload_provenance_carries_only_the_filename() -> None:
    provenance = LibraryProvenance.from_upload(
        saved_at=NOW,
        original_filename="  report.csv  ",
    )

    assert provenance.source == "upload"
    assert provenance.original_filename == "report.csv"
    assert provenance.graph_id is None
    assert provenance.result_fingerprint is None


def test_upload_provenance_rejects_instance_facts() -> None:
    with pytest.raises(ValidationError):
        LibraryProvenance(
            source="upload",
            saved_at=NOW,
            original_filename="report.csv",
            project_id=uuid4(),
        )


def test_instance_provenance_rejects_an_uploaded_filename() -> None:
    with pytest.raises(ValidationError):
        LibraryProvenance(
            source="instance",
            saved_at=NOW,
            project_id=uuid4(),
            project_title="Workspace Project",
            graph_id="main",
            graph_title="Sales",
            node_id="resize-1",
            node_title="Resize",
            result_fingerprint="a" * 64,
            output_port="value",
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
    provenance = _instance_provenance()

    with pytest.raises(ValidationError):
        provenance.graph_title = "Renamed"


def test_provenance_round_trips_through_json() -> None:
    provenance = _instance_provenance()

    restored = LibraryProvenance.model_validate(
        provenance.model_dump(mode="json"),
    )

    assert restored == provenance
