import asyncio
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.services.composition import WorkbenchComponents
from grafy_api.v1.routes.artifacts import services as artifact_services
from grafy_api.v1.routes.artifacts.models import (
    ArtifactExactMatchRow,
    TableExactMatchGroup,
    TableQueryRequest,
)
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.execution.requests import RunRequest
from tests.support.system_plugins import selected_system_run_node as RunNodeRequest
from grafy_api.v1.routes.executions.services import RunResultPresenter
from grafy_core.artifacts import ArtifactObject
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.nodes import NodeExecutionContext
from grafy_core.table_contracts import (
    Table,
    TableColumn,
    TableValueType,
)
from grafy_workbench.table.persistence import TableArtifactWriter
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_storage import LocalFileObjectStore

from tests.support.clients import GrafyApi


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")


def test_full_table_content_and_download_return_413_before_reconstruction(
    table_artifact_client: tuple[
        TestClient,
        TableArtifactWriter,
        WorkbenchComponents,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, writer, _ = table_artifact_client
    table = Table(
        columns=[
            TableColumn(id="value", title="Value", value_type=TableValueType.TEXT)
        ],
        rows=[{"value": "bounded"}],
    )
    ref = asyncio.run(
        writer.write(
            table,
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="table-response-cap",
                ),
                provenance=MaterializationProvenance(refs_by_input={}),
            ),
        )
    )
    monkeypatch.setattr(
        artifact_services,
        "BUFFERED_ARTIFACT_RESPONSE_MAX_BYTES",
        1,
    )
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts

    content = artifacts.content(ref.artifact_id)
    download = artifacts.download(ref.artifact_id, format="json")

    assert content.status_code == 413
    assert str(ref.artifact_id) in content.json()["detail"]
    assert "1-byte response limit" in content.json()["detail"]
    assert download.status_code == 413
    assert str(ref.artifact_id) in download.json()["detail"]


def test_table_page_bounds_cell_previews_and_full_download(
    table_artifact_client: tuple[
        TestClient,
        TableArtifactWriter,
        WorkbenchComponents,
    ],
) -> None:
    client, writer, components = table_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    long_geometry = "MULTIPOLYGON (((" + "1 2, " * 300 + "1 2)))"
    table = Table(
        columns=[
            TableColumn(id="id", title="ID", value_type=TableValueType.INTEGER),
            TableColumn(
                id="geometry/wkt",
                title="Geometry",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="large_id",
                title="Large ID",
                value_type=TableValueType.INTEGER,
            ),
            TableColumn(
                id="metadata",
                title="Metadata",
                value_type=TableValueType.JSON,
            ),
        ],
        rows=[
            {
                "id": index,
                "geometry/wkt": f"{long_geometry}-{index}",
                "large_id": 2**60 + index,
                "metadata": {"index": index, "tags": ["table", "preview"]},
            }
            for index in range(120)
        ],
    )
    ref = asyncio.run(
        writer.write(
            table,
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="table",
                ),
                provenance=MaterializationProvenance(refs_by_input={}),
            ),
        )
    )

    page_response = artifacts.table_page(
        ref.artifact_id,
        offset=95,
        limit=10,
        max_cell_characters=32,
    )

    assert page_response.status_code == 200
    page = page_response.json()
    assert page["offset"] == 95
    assert page["limit"] == 10
    assert page["total_rows"] == 120
    assert len(page["rows"]) == 10
    assert page["rows"][0]["id"] == {
        "display": "95",
        "truncated": False,
        "original_length": None,
    }
    geometry_preview = page["rows"][0]["geometry/wkt"]
    assert geometry_preview["truncated"] is True
    assert len(geometry_preview["display"]) == 33
    geometry = table.rows[95]["geometry/wkt"]
    assert isinstance(geometry, str)
    assert geometry_preview["original_length"] == len(geometry)

    cell_response = artifacts.table_cell(
        ref.artifact_id,
        row_index=95,
        column_id="geometry/wkt",
    )
    assert cell_response.status_code == 200
    assert cell_response.json() == {
        "row_index": 95,
        "column_id": "geometry/wkt",
        "value": table.rows[95]["geometry/wkt"],
        "encoding": "native",
    }

    large_integer_response = artifacts.table_cell(
        ref.artifact_id,
        row_index=95,
        column_id="large_id",
    )
    assert large_integer_response.json() == {
        "row_index": 95,
        "column_id": "large_id",
        "value": str(2**60 + 95),
        "encoding": "integer",
    }
    nested_response = artifacts.table_cell(
        ref.artifact_id,
        row_index=95,
        column_id="metadata",
    )
    assert nested_response.json() == {
        "row_index": 95,
        "column_id": "metadata",
        "value": '{"index": 95, "tags": ["table", "preview"]}',
        "encoding": "json",
    }
    assert (
        artifacts.table_cell(
            ref.artifact_id,
            row_index=999,
            column_id="id",
        ).status_code
        == 400
    )
    assert (
        artifacts.table_cell(
            ref.artifact_id,
            row_index=0,
            column_id="missing",
        ).status_code
        == 400
    )

    column_page_response = artifacts.table_page(
        ref.artifact_id,
        column_offset=2,
        column_limit=1,
    )
    assert column_page_response.status_code == 200
    column_page = column_page_response.json()
    assert [column["id"] for column in column_page["columns"]] == ["large_id"]
    assert set(column_page["rows"][0]) == {"large_id"}
    assert column_page["column_offset"] == 2
    assert column_page["column_limit"] == 1
    assert column_page["total_columns"] == 4

    selected_columns_response = artifacts.table_page(
        ref.artifact_id,
        column_ids=["metadata", "id"],
    )
    assert selected_columns_response.status_code == 200
    selected_columns_page = selected_columns_response.json()
    assert [column["id"] for column in selected_columns_page["columns"]] == [
        "metadata",
        "id",
    ]
    assert list(selected_columns_page["rows"][0]) == ["metadata", "id"]
    assert selected_columns_page["column_offset"] == 0
    assert selected_columns_page["column_limit"] == 2
    assert selected_columns_page["total_columns"] == 4
    assert (
        artifacts.table_page(
            ref.artifact_id,
            column_ids=["missing"],
        ).status_code
        == 400
    )

    schema_response = artifacts.table_schema(ref.artifact_id)
    assert schema_response.status_code == 200
    assert schema_response.json()["total_rows"] == 120
    assert [column["id"] for column in schema_response.json()["columns"]] == [
        "id",
        "geometry/wkt",
        "large_id",
        "metadata",
    ]

    summary = asyncio.run(
        components.presenter.port_output_response(WORKSPACE_ID, "output", ref)
    ).artifacts[0]
    assert summary.byte_size is not None

    content_response = artifacts.content(ref.artifact_id)
    assert content_response.status_code == 200
    assert Table.model_validate(content_response.json()) == table
    assert len(content_response.content) == summary.byte_size
    assert sha256(content_response.content).hexdigest() == ref.content_hash

    # The summary advertises csv as a download format.
    assert [entry.format for entry in summary.download_formats] == ["json", "csv"]

    # Downloading as csv streams the full table (header + every row).
    csv_response = artifacts.download(ref.artifact_id, format="csv")
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert ".csv" in csv_response.headers["content-disposition"]
    csv_bytes = csv_response.content
    # UTF-8 BOM so spreadsheet apps decode the file as UTF-8.
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    csv_text = csv_bytes.decode("utf-8-sig")
    # RFC 4180 CRLF line terminators.
    assert "\r\n" in csv_text
    csv_lines = csv_text.splitlines()
    assert csv_lines[0] == "id,geometry/wkt,large_id,metadata"
    assert len(csv_lines) == 121  # header + 120 rows

    assert summary.text is None
    assert summary.metadata["row_count"] == 120
    assert summary.metadata["column_count"] == 4


def test_table_page_rejects_non_table_and_invalid_limits(
    table_artifact_client: tuple[
        TestClient,
        TableArtifactWriter,
        WorkbenchComponents,
    ],
) -> None:
    client, _, _ = table_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts

    run_response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="text",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "not a table"},
                )
            ]
        ).model_dump(mode="json"),
    )
    assert run_response.status_code == 200
    text_artifact_id = run_response.json()["node_runs"][0]["outputs"][0]["value"][
        "artifact_id"
    ]
    assert artifacts.table_page(UUID(text_artifact_id)).status_code == 400

    assert (
        artifacts.table_page(UUID("00000000-0000-0000-0000-000000000000")).status_code
        == 404
    )
    assert (
        artifacts.table_page(
            UUID("00000000-0000-0000-0000-000000000000"),
            limit=0,
        ).status_code
        == 422
    )
    assert (
        artifacts.table_page(
            UUID("00000000-0000-0000-0000-000000000000"),
            limit=100,
            column_limit=100,
            max_cell_characters=2_000,
        ).status_code
        == 400
    )


def test_table_query_filters_composite_keys_and_preserves_source_rows(
    table_artifact_client: tuple[
        TestClient,
        TableArtifactWriter,
        WorkbenchComponents,
    ],
) -> None:
    client, writer, _ = table_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    table = Table(
        columns=[
            TableColumn(
                id="place",
                title="Place",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="district",
                title="District",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="status",
                title="Status",
                value_type=TableValueType.TEXT,
            ),
        ],
        rows=[
            {
                "place": "Belynichi",
                "district": "Mohilev",
                "status": "accepted",
            },
            {
                "place": "Belynichi",
                "district": "Orsha",
                "status": "accepted",
            },
            {
                "place": "Kniazhitsy",
                "district": "Mohilev",
                "status": "review",
            },
            {
                "place": "Gomel",
                "district": "Gomel",
                "status": "review",
            },
        ],
    )
    ref = asyncio.run(
        writer.write(
            table,
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="table-query",
                ),
                provenance=MaterializationProvenance(refs_by_input={}),
            ),
        )
    )

    response = artifacts.table_query(
        ref.artifact_id,
        TableQueryRequest(
            filter_groups=[
                TableExactMatchGroup(
                    rows=[
                        ArtifactExactMatchRow(values={"place": "Belynichi"}),
                        ArtifactExactMatchRow(values={"place": "Kniazhitsy"}),
                    ]
                ),
                TableExactMatchGroup(
                    rows=[ArtifactExactMatchRow(values={"district": "Mohilev"})]
                ),
            ],
            highlight_groups=[
                TableExactMatchGroup(
                    rows=[ArtifactExactMatchRow(values={"status": "review"})]
                )
            ],
            offset=0,
            limit=50,
            column_offset=0,
            column_limit=25,
            max_cell_characters=256,
        ),
    )

    assert response.status_code == 200
    page = response.json()
    assert page["total_rows"] == 2
    assert page["row_indices"] == [0, 2]
    assert page["highlighted_row_indices"] == [2]
    assert [row["place"]["display"] for row in page["rows"]] == [
        "Belynichi",
        "Kniazhitsy",
    ]

    missing_field = artifacts.table_query(
        ref.artifact_id,
        TableQueryRequest(
            filter_groups=[
                TableExactMatchGroup(
                    rows=[ArtifactExactMatchRow(values={"missing": "Belynichi"})]
                )
            ],
        ),
    )
    assert missing_field.status_code == 400
    assert "missing" in missing_field.json()["detail"]


def test_table_query_matches_integer_keys_from_string_or_number(
    table_artifact_client: tuple[
        TestClient,
        TableArtifactWriter,
        WorkbenchComponents,
    ],
) -> None:
    client, writer, _ = table_artifact_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    large_id = 2**60 + 95
    table = Table(
        columns=[
            TableColumn(id="id", title="ID", value_type=TableValueType.INTEGER),
            TableColumn(
                id="large_id",
                title="Large ID",
                value_type=TableValueType.INTEGER,
            ),
            TableColumn(
                id="place",
                title="Place",
                value_type=TableValueType.TEXT,
            ),
        ],
        rows=[
            {"id": 12, "large_id": large_id, "place": "Belynichi"},
            {"id": 13, "large_id": large_id + 1, "place": "Kniazhitsy"},
        ],
    )
    ref = asyncio.run(
        writer.write(
            table,
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id="table-integer-query",
                ),
                provenance=MaterializationProvenance(refs_by_input={}),
            ),
        )
    )
    string_key = artifacts.table_query(
        ref.artifact_id,
        TableQueryRequest(
            highlight_groups=[
                TableExactMatchGroup(rows=[ArtifactExactMatchRow(values={"id": "12"})])
            ],
        ),
    )
    assert string_key.status_code == 200
    assert string_key.json()["highlighted_row_indices"] == [0]

    number_key = artifacts.table_query(
        ref.artifact_id,
        TableQueryRequest(
            highlight_groups=[
                TableExactMatchGroup(rows=[ArtifactExactMatchRow(values={"id": 12})])
            ],
        ),
    )
    assert number_key.status_code == 200
    assert number_key.json()["highlighted_row_indices"] == [0]

    large_string_key = artifacts.table_query(
        ref.artifact_id,
        TableQueryRequest(
            filter_groups=[
                TableExactMatchGroup(
                    rows=[ArtifactExactMatchRow(values={"large_id": str(large_id)})]
                )
            ],
        ),
    )
    assert large_string_key.status_code == 200
    assert large_string_key.json()["row_indices"] == [0]
    assert large_string_key.json()["total_rows"] == 1

    padded = artifacts.table_query(
        ref.artifact_id,
        TableQueryRequest(
            highlight_groups=[
                TableExactMatchGroup(rows=[ArtifactExactMatchRow(values={"id": "012"})])
            ],
        ),
    )
    assert padded.status_code == 200
    assert padded.json()["highlighted_row_indices"] == []


def test_interaction_values_equal_integers_across_json_string_encoding() -> None:
    from grafy_api.v1.routes.artifacts.services import (
        _interaction_values_equal,
    )

    assert _interaction_values_equal(12, "12")
    assert _interaction_values_equal("12", 12)
    assert not _interaction_values_equal(12, "012")
    assert not _interaction_values_equal(1, True)
    assert not _interaction_values_equal(True, "1")
    assert _interaction_values_equal("Belynichi", "Belynichi")


async def test_artifact_summaries_never_embed_unbounded_or_table_json(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    unknown_size = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="sql.result",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"table": "unbounded"},
    )
    large = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="sql.result",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"table": "x" * 70_000},
        byte_size=70_000,
    )
    legacy_table = Table(
        columns=[
            TableColumn(id="value", title="Value", value_type=TableValueType.TEXT)
        ],
        rows=[{"value": "small but paged"}],
    )
    table_artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="table.data",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload=legacy_table.model_dump(mode="json"),
        byte_size=10,
    )
    small = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="scalar.text",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"text": "bounded"},
        byte_size=18,
    )
    async with unit_of_work as uow:
        for artifact in (unknown_size, large, table_artifact, small):
            await uow.artifacts.add(artifact)
        await uow.commit()
    presenter = RunResultPresenter(
        ArtifactService(
            unit_of_work,
            LocalFileObjectStore(tmp_path / "objects"),
            availability=ArtifactAvailability(
                unit_of_work, LocalFileObjectStore(tmp_path / "objects")
            ),
        ),
        ArtifactAvailability(unit_of_work, LocalFileObjectStore(tmp_path / "objects")),
    )

    assert (
        await presenter.port_output_response(WORKSPACE_ID, "output", unknown_size.ref())
    ).artifacts[0].text is None
    assert (
        await presenter.port_output_response(WORKSPACE_ID, "output", large.ref())
    ).artifacts[0].text is None
    assert (
        await presenter.port_output_response(
            WORKSPACE_ID, "output", table_artifact.ref()
        )
    ).artifacts[0].text is None
    assert (
        await presenter.port_output_response(WORKSPACE_ID, "output", small.ref())
    ).artifacts[0].text == "bounded"


async def test_iter_table_csv_encodes_utf8_bom_crlf_and_quoting(
    tmp_path: Path,
) -> None:
    """CSV export uses a UTF-8 BOM, CRLF terminators, and RFC 4180 quoting."""
    from grafy_core.runtime.table_storage import iter_table_csv

    storage = LocalFileObjectStore(tmp_path / "objects")
    table = Table(
        columns=[
            TableColumn(id="name", title="Name", value_type=TableValueType.TEXT),
            TableColumn(id="note", title="Note", value_type=TableValueType.TEXT),
        ],
        rows=[
            {"name": "Café", "note": "plain"},
            {"name": "a,b", "note": "quoted"},
            {"name": "line\nbreak", "note": "embedded"},
            {"name": 'quoted"cell', "note": "quote"},
        ],
    )
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="table.data",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload=table.model_dump(mode="json"),
    )

    chunks = []
    async for chunk in iter_table_csv(artifact, storage):
        chunks.append(chunk)
    body = b"".join(chunks)

    # UTF-8 BOM so Excel decodes the file as UTF-8.
    assert body.startswith(b"\xef\xbb\xbf")
    # CRLF line terminators per RFC 4180.
    assert b"\r\n" in body
    text = body.decode("utf-8-sig")

    # The first cell after the BOM is the header; quoting handles delimiters,
    # quotes, and embedded newlines inside fields.
    assert text.splitlines()[0] == "name,note"
    assert '"a,b"' in text
    assert '"quoted""cell"' in text
    assert '"line\nbreak"' in text
    assert "Café" in text
