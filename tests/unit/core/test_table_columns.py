import pytest

from grafy_core.table_contracts import (
    TableColumn,
    TableColumnLookupError,
    resolve_table_column,
)

COLUMNS = [
    TableColumn(id="column_1", title="name"),
    TableColumn(id="name", title="Name in the source"),
    TableColumn(id="column_3", title="wkt"),
    TableColumn(id="column_4", title="note"),
    TableColumn(id="column_5", title="note"),
]


def test_an_exact_id_wins_over_another_columns_title() -> None:
    assert resolve_table_column(COLUMNS, "name") == "name"
    assert resolve_table_column(COLUMNS, "column_4") == "column_4"


def test_a_unique_title_names_its_column() -> None:
    assert resolve_table_column(COLUMNS, "wkt") == "column_3"


def test_titles_match_exactly() -> None:
    with pytest.raises(TableColumnLookupError, match="no column id or title 'WKT'"):
        resolve_table_column(COLUMNS, "WKT")


def test_a_shared_title_is_refused_and_names_the_ids_to_use() -> None:
    with pytest.raises(
        TableColumnLookupError,
        match=r"'note' is ambiguous; use one of the column ids \['column_4', 'column_5'\]",
    ):
        resolve_table_column(COLUMNS, "note")
