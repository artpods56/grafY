from uuid import uuid4

import pytest

from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.table_contracts import Table, TableColumn, TableValueType
from grafy_plugin_map_toponyms.place_matching import (
    MatchPlacesConfig,
    MatchPlacesInput,
    MatchPlacesNode,
    score_place_name,
)


@pytest.mark.parametrize(
    ("reference", "candidate", "min_expected"),
    [
        ("м. Кричевъ", "CUECmEKO KPUE8", 0.78),
        ("м. Пропойскъ", "mестесноропойси", 0.72),
        ("м. Рясна", "pяcHa", 0.95),
        ("с. Рассохи", "paccox", 0.85),
        ("м. Родня", "СЕродня", 0.95),
        ("г. Чауссы", "ЧАУСЬ", 0.80),
        ("м. Дубровна", "ПiДуоровн", 0.75),
    ],
)
def test_score_place_name_handles_homoglyphs_and_prefixes(
    reference: str, candidate: str, min_expected: float
) -> None:
    assert score_place_name(reference, candidate) >= min_expected


async def test_match_places_joins_geometry_and_prefers_expected_scope() -> None:
    reference = Table(
        columns=[
            TableColumn(id="seat_name", title="Seat", value_type=TableValueType.TEXT),
            TableColumn(
                id="expected_sheets",
                title="Expected sheets",
                value_type=TableValueType.TEXT,
            ),
        ],
        rows=[
            {"seat_name": "Корма", "expected_sheets": "336.tif,27.tif"},
            {"seat_name": "Кричевъ", "expected_sheets": "176.tif,432.tif"},
            {"seat_name": "Несуществующее", "expected_sheets": "245.tif"},
        ],
    )
    candidates = Table(
        columns=[
            TableColumn(id="name", title="OCR Name", value_type=TableValueType.TEXT),
            TableColumn(
                id="source_tiff", title="Source TIFF", value_type=TableValueType.TEXT
            ),
            TableColumn(
                id="geometry_wkt", title="Geometry", value_type=TableValueType.TEXT
            ),
        ],
        rows=[
            {
                "name": "Корма",
                "source_tiff": "16.tif",
                "geometry_wkt": "POINT (30.5 54.8)",
            },
            {
                "name": "Корма",
                "source_tiff": "336.tif",
                "geometry_wkt": "POINT (30.8 53.1)",
            },
            {
                "name": "CUECmEKO KPUE8",
                "source_tiff": "176.tif",
                "geometry_wkt": "POINT (31.7 53.7)",
            },
        ],
    )
    result = await MatchPlacesNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        MatchPlacesConfig(
            reference_column="seat_name",
            candidate_column="name",
            reference_scope_column="expected_sheets",
            candidate_scope_column="source_tiff",
        ),
        MatchPlacesInput(reference=reference, candidates=candidates),
    )

    rows = result.matched.rows
    assert len(rows) == 3
    assert rows[0]["match_id"] == 1
    assert rows[0]["match_status"] == "matched"
    assert rows[0]["ocr_source_tiff"] == "336.tif"
    assert rows[0]["in_expected_scope"] is True
    assert rows[0]["geometry_wkt"] == "POINT (30.8 53.1)"

    assert rows[1]["match_id"] == 2
    assert rows[1]["match_status"] == "matched"
    assert rows[1]["ocr_name"] == "CUECmEKO KPUE8"
    assert rows[1]["geometry_wkt"] == "POINT (31.7 53.7)"

    assert rows[2]["match_id"] == 3
    assert rows[2]["match_status"] == "unmatched"
    assert rows[2]["geometry_wkt"] is None


async def test_match_places_rejects_missing_columns() -> None:
    empty = Table(columns=[TableColumn(id="other", title="Other")], rows=[])
    with pytest.raises(UserFacingNodeError, match="Reference column"):
        await MatchPlacesNode().run(
            NodeExecutionContext(workspace_id=uuid4()),
            MatchPlacesConfig(),
            MatchPlacesInput(reference=empty, candidates=empty),
        )


async def test_match_places_sorts_by_score_hoists_key_columns_and_passes_point_wkt() -> (
    None
):
    reference = Table(
        columns=[
            TableColumn(
                id="col_1", title="gubernia_no", value_type=TableValueType.INTEGER
            ),
            TableColumn(id="col_2", title="seat_name", value_type=TableValueType.TEXT),
        ],
        rows=[
            {"col_1": 1, "col_2": "Несуществующее"},
            {"col_1": 2, "col_2": "м. Корма"},
            {"col_1": 3, "col_2": "м. Кричевъ"},
        ],
    )
    candidates = Table(
        columns=[
            TableColumn(
                id="col_1", title="source_tiff", value_type=TableValueType.TEXT
            ),
            TableColumn(id="col_2", title="name", value_type=TableValueType.TEXT),
            TableColumn(id="col_3", title="point_wkt", value_type=TableValueType.TEXT),
        ],
        rows=[
            {
                "col_1": "176.tif",
                "col_2": "CUECmEKO KPUE8",
                "col_3": "POINT (31.7 53.7)",
            },
            {"col_1": "336.tif", "col_2": "Корма", "col_3": "POINT (30.8 53.1)"},
        ],
    )
    result = await MatchPlacesNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        MatchPlacesConfig(
            reference_column="seat_name",
            candidate_column="name",
            candidate_scope_column="source_tiff",
            sort_by="score_desc",
        ),
        MatchPlacesInput(reference=reference, candidates=candidates),
    )

    col_ids = [col.id for col in result.matched.columns]
    assert col_ids[:6] == [
        "match_id",
        "match_status",
        "match_score",
        "seat_name",
        "ocr_name",
        "ocr_source_tiff",
    ]
    assert "point_wkt" in col_ids

    rows = result.matched.rows
    assert [row["match_id"] for row in rows] == [1, 2, 3]
    assert [row["seat_name"] for row in rows] == [
        "м. Корма",
        "м. Кричевъ",
        "Несуществующее",
    ]
    assert [row["match_status"] for row in rows] == ["matched", "matched", "unmatched"]
    assert rows[0]["point_wkt"] == "POINT (30.8 53.1)"
    assert rows[2]["point_wkt"] is None
