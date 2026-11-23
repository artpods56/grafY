from uuid import uuid4

import pytest

from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.table_contracts import Table, TableColumn, TableValueType
from grafy_plugin_map_toponyms.transliteration import (
    TransliterateConfig,
    TransliterateCyrillicNode,
    TransliterateInput,
    transliterate_cyrillic,
)


@pytest.mark.parametrize(
    ("original", "latin"),
    [
        ("Бѣлыничи", "Belynichi"),
        ("Пропойскъ", "Propoysk"),
        ("ЧАУСЫ", "CHAUSY"),
        ("Чауссы", "Chaussy"),
        ("м. Кричевъ / Krychaw", "m. Krichev / Krychaw"),
        ("Іўе — Київ", "Iue — Kiyiv"),
    ],
)
def test_transliterates_old_and_modern_cyrillic(original: str, latin: str) -> None:
    assert transliterate_cyrillic(original) == latin


async def test_table_keeps_original_spellings_and_coordinates() -> None:
    table = Table(
        columns=[
            TableColumn(id="seat", title="Seat", value_type=TableValueType.TEXT),
            TableColumn(id="page", title="Page", value_type=TableValueType.INTEGER),
        ],
        rows=[{"seat": "Кричевъ", "page": 8}, {"seat": None, "page": 9}],
    )
    result = await TransliterateCyrillicNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        TransliterateConfig(source_column="seat", output_column="seat_latin"),
        TransliterateInput(table=table),
    )
    assert result.table.rows == [
        {"seat": "Кричевъ", "page": 8, "seat_latin": "Krichev"},
        {"seat": None, "page": 9, "seat_latin": None},
    ]
    assert [column.id for column in result.table.columns] == [
        "seat",
        "page",
        "seat_latin",
    ]


async def test_transliteration_does_not_overwrite_the_source_column() -> None:
    table = Table(columns=[TableColumn(id="name", title="Name")], rows=[])
    with pytest.raises(UserFacingNodeError, match="already exists"):
        await TransliterateCyrillicNode().run(
            NodeExecutionContext(workspace_id=uuid4()),
            TransliterateConfig(output_column="name"),
            TransliterateInput(table=table),
        )
